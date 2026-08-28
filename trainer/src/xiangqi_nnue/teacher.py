from __future__ import annotations

import argparse
import queue
import re
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence


MATE_SCORE = 32_000
SCORE_PATTERN = re.compile(r"\bscore (cp|mate) (-?\d+)")
NODES_PATTERN = re.compile(r"\bnodes (\d+)")
FAIRY_MOVE = re.compile(r"^([a-i])(10|[1-9])([a-i])(10|[1-9])$")


def fairy_move_to_ucci(move: str) -> str:
    """Convert Fairy-Stockfish's files/1..10 ranks to UCCI files/0..9 ranks."""
    match = FAIRY_MOVE.fullmatch(move)
    if match is None:
        raise ValueError(f"invalid Fairy-Stockfish Xiangqi move {move}")
    return (
        match.group(1)
        + str(int(match.group(2)) - 1)
        + match.group(3)
        + str(int(match.group(4)) - 1)
    )


class TeacherProtocolError(RuntimeError):
    pass


@dataclass(frozen=True)
class TeacherEvaluation:
    score_cp: int
    bestmove: str
    nodes: int
    mate_ply: int | None = None


class FairyStockfishTeacher:
    """Long-lived UCI client for the pinned Fairy-Stockfish CC0 teacher."""

    def __init__(
        self,
        command: str | Path | Sequence[str | Path],
        *,
        threads: int = 1,
        hash_mb: int = 128,
        timeout: float = 60.0,
    ) -> None:
        if threads <= 0 or hash_mb <= 0 or timeout <= 0:
            raise ValueError("threads, hash_mb, and timeout must be positive")
        argv = [str(command)] if isinstance(command, (str, Path)) else [str(x) for x in command]
        if not argv:
            raise ValueError("teacher command cannot be empty")
        self.timeout = timeout
        self._process = subprocess.Popen(
            argv,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
        )
        self._lines: queue.Queue[str | None] = queue.Queue()
        self._lock = threading.Lock()
        threading.Thread(target=self._read_output, daemon=True).start()
        self._send("uci")
        self._wait_for("uciok")
        self._send("setoption name UCI_Variant value xiangqi")
        self._send(f"setoption name Threads value {threads}")
        self._send(f"setoption name Hash value {hash_mb}")
        self._send("isready")
        self._wait_for("readyok")

    def _read_output(self) -> None:
        assert self._process.stdout is not None
        try:
            for line in self._process.stdout:
                self._lines.put(line.rstrip("\r\n"))
        finally:
            self._lines.put(None)

    def _send(self, value: str) -> None:
        if self._process.poll() is not None:
            raise TeacherProtocolError(f"teacher exited with code {self._process.returncode}")
        assert self._process.stdin is not None
        self._process.stdin.write(value + "\n")
        self._process.stdin.flush()

    def _next_line(self, deadline: float) -> str:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError("timed out waiting for teacher output")
        try:
            line = self._lines.get(timeout=remaining)
        except queue.Empty as error:
            raise TimeoutError("timed out waiting for teacher output") from error
        if line is None:
            raise TeacherProtocolError(
                f"teacher exited while waiting for output (code {self._process.poll()})"
            )
        return line

    def _wait_for(self, expected: str) -> None:
        deadline = time.monotonic() + self.timeout
        while self._next_line(deadline) != expected:
            pass

    @staticmethod
    def _score(kind: str, value: int) -> tuple[int, int | None]:
        if kind == "cp":
            return value, None
        distance = min(abs(value), 1_000)
        score = MATE_SCORE - distance
        return (score if value > 0 else -score), value

    def evaluate_fen(self, fen: str, nodes: int) -> TeacherEvaluation:
        if "\n" in fen or "\r" in fen or not fen.strip():
            raise ValueError("FEN must be a non-empty single line")
        if nodes <= 0:
            raise ValueError("nodes must be positive")
        with self._lock:
            self._send("position fen " + fen)
            self._send(f"go nodes {nodes}")
            deadline = time.monotonic() + self.timeout
            latest: tuple[int, int | None, int] | None = None
            while True:
                line = self._next_line(deadline)
                score_match = SCORE_PATTERN.search(line)
                if score_match:
                    score, mate = self._score(score_match.group(1), int(score_match.group(2)))
                    nodes_match = NODES_PATTERN.search(line)
                    latest = (score, mate, int(nodes_match.group(1)) if nodes_match else 0)
                if line.startswith("bestmove "):
                    if latest is None:
                        raise TeacherProtocolError("teacher returned bestmove without a score")
                    bestmove = fairy_move_to_ucci(line.split(maxsplit=2)[1])
                    return TeacherEvaluation(latest[0], bestmove, latest[2], latest[1])

    def close(self) -> None:
        with self._lock:
            if self._process.poll() is None:
                try:
                    self._send("quit")
                    self._process.wait(timeout=2)
                except (BrokenPipeError, subprocess.TimeoutExpired):
                    self._process.kill()
                    self._process.wait(timeout=2)
            if self._process.stdin is not None:
                self._process.stdin.close()
            if self._process.stdout is not None:
                self._process.stdout.close()

    def __enter__(self) -> FairyStockfishTeacher:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Query the pinned CC0 Xiangqi teacher")
    parser.add_argument("--engine", type=Path, required=True)
    parser.add_argument("--fen", required=True)
    parser.add_argument("--nodes", type=int, default=10_000)
    args = parser.parse_args()
    with FairyStockfishTeacher(args.engine) as teacher:
        print(teacher.evaluate_fen(args.fen, args.nodes))


if __name__ == "__main__":
    main()
