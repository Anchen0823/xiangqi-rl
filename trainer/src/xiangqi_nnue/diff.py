from __future__ import annotations

import argparse
import json
import queue
import random
import re
import subprocess
import threading
import time
from pathlib import Path

from .rules import NativeRulesClient

PERFT_NODES = re.compile(r"Nodes searched:\s*(\d+)")


class PerftReference:
    """UCI client for the ``go perft`` legal-move count of the reference engine.

    Pikafish (and Stockfish-family engines) implement ``go perft N``, which
    counts legal move paths of length N from the current position. perft(1)
    equals the number of legal moves; perft(2) additionally exercises reply
    legality. The native rules engine exposes the same counts through its JSON
    protocol, so the two implementations can be differenced.
    """

    def __init__(self, executable: str | Path | list[str | Path], *,
                 eval_file: str | Path | None = None, timeout: float = 30.0) -> None:
        if timeout <= 0:
            raise ValueError("timeout must be positive")
        argv = [str(x) for x in executable] if isinstance(executable, list) else [str(executable)]
        if not argv:
            raise ValueError("engine command must not be empty")
        self.timeout = timeout
        self._process = subprocess.Popen(
            argv,
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding="utf-8", errors="replace", bufsize=1,
        )
        self._lines: queue.Queue[str | None] = queue.Queue()
        self._lock = threading.Lock()
        threading.Thread(target=self._read_output, daemon=True).start()
        self._send("uci")
        self._wait_for("uciok")
        if eval_file is not None:
            self._send(f"setoption name EvalFile value {Path(eval_file).resolve()}")
        self._send("setoption name Threads value 1")
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
        assert self._process.stdin is not None
        self._process.stdin.write(value + "\n")
        self._process.stdin.flush()

    def _next_line(self, deadline: float) -> str | None:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError("perft reference timed out")
        try:
            line = self._lines.get(timeout=remaining)
        except queue.Empty as error:
            raise TimeoutError("perft reference timed out") from error
        if line is None:
            raise RuntimeError(f"perft reference exited (code {self._process.poll()})")
        return line

    def _wait_for(self, expected: str) -> None:
        deadline = time.monotonic() + self.timeout
        while True:
            line = self._next_line(deadline)
            if line == expected:
                return

    def perft(self, fen: str, depth: int) -> int:
        if "\n" in fen or "\r" in fen or not fen.strip():
            raise ValueError("FEN must be a non-empty single line")
        if depth <= 0:
            raise ValueError("depth must be positive")
        with self._lock:
            self._send("position fen " + fen)
            self._send(f"go perft {depth}")
            deadline = time.monotonic() + self.timeout
            while True:
                line = self._next_line(deadline)
                match = PERFT_NODES.search(line)
                if match:
                    return int(match.group(1))

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

    def __enter__(self) -> PerftReference:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()


def random_positions(
    rules: NativeRulesClient,
    *,
    count: int,
    min_plies: int,
    max_plies: int,
    seed: int,
) -> list[str]:
    """Deterministic random legal positions for the differential.

    Each position is produced by playing a seeded number of random legal moves
    from the initial position, so every FEN is guaranteed legal and reachable.
    """
    if count <= 0 or min_plies < 0 or max_plies < min_plies:
        raise ValueError("count must be positive and 0 <= min_plies <= max_plies")
    rng = random.Random(seed)
    positions: list[str] = []
    for _ in range(count):
        rules.new_game()
        plies = rng.randint(min_plies, max_plies)
        for _ in range(plies):
            snapshot = rules.snapshot()
            if snapshot["result"]["kind"] != "ongoing":
                break
            legal = snapshot["legalMoves"]
            if not legal:
                break
            rules.play_move(legal[rng.randrange(len(legal))])
        positions.append(rules.snapshot()["fen"])
    return positions


def native_perft(rules: NativeRulesClient, fen: str, depth: int) -> int:
    """Legal-move path count from the native rules engine.

    Uses the snapshot legal-move list directly (depth 1) and expands replies
    for depth 2, matching the reference engine's perft semantics. Repetition
    adjudication is intentionally excluded, per the plan.
    """
    rules.load_fen(fen)
    if depth == 1:
        return len(rules.snapshot()["legalMoves"])
    snapshot = rules.snapshot()
    total = 0
    for move in snapshot["legalMoves"]:
        rules.play_move(move)
        total += len(rules.snapshot()["legalMoves"])
        rules.undo()
    return total


def diff_positions(
    *,
    rules: NativeRulesClient,
    reference: PerftReference,
    positions: list[str],
    depth: int,
    sample: int | None = None,
) -> dict:
    """Compare native vs reference perft counts on a FEN list.

    Returns counts and a list of mismatches (fen, native, reference). ``sample``
    limits how many positions are actually compared (for large runs).
    """
    checked = native_ok = 0
    mismatches: list[dict] = []
    for index, fen in enumerate(positions):
        if sample is not None and index >= sample:
            break
        expected = native_perft(rules, fen, depth)
        actual = reference.perft(fen, depth)
        checked += 1
        if expected == actual:
            native_ok += 1
        else:
            mismatches.append({"fen": fen, "native": expected, "reference": actual})
    return {
        "depth": depth,
        "checked": checked,
        "matched": native_ok,
        "match_ratio": native_ok / checked if checked else 0.0,
        "mismatches": mismatches,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Differential rules check: native legal moves vs reference go perft"
    )
    parser.add_argument("--rules-engine", type=Path, required=True)
    parser.add_argument("--reference-engine", type=Path, required=True)
    parser.add_argument("--eval-file", type=Path)
    parser.add_argument("--positions", type=int, default=100_000)
    parser.add_argument("--min-plies", type=int, default=8)
    parser.add_argument("--max-plies", type=int, default=80)
    parser.add_argument("--depth", type=int, default=1)
    parser.add_argument("--sample", type=int, default=10_000,
                        help="how many positions to compare (large runs are slow)")
    parser.add_argument("--seed", type=int, default=20260828)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    with NativeRulesClient(args.rules_engine) as rules:
        positions = random_positions(
            rules, count=args.positions, min_plies=args.min_plies,
            max_plies=args.max_plies, seed=args.seed,
        )
        with PerftReference(args.reference_engine, eval_file=args.eval_file) as reference:
            report = diff_positions(
                rules=rules, reference=reference, positions=positions,
                depth=args.depth, sample=args.sample,
            )
    report["positions_generated"] = len(positions)
    report["seed"] = args.seed
    payload = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload, encoding="utf-8")
    print(payload)
    if report["mismatches"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
