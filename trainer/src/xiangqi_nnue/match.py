from __future__ import annotations

import argparse
import json
import math
import queue
import random
import re
import subprocess
import threading
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Sequence

from .rules import NativeRulesClient, RulesProtocolError

INITIAL_FEN = "rnbakabnr/9/1c5c1/p1p1p1p1p/9/9/P1P1P1P1P/1C5C1/9/RNBAKABNR w - - 0 1"

BESTMOVE_PATTERN = re.compile(r"^bestmove\s+(\S+)(?:\s+ponder\s+\S+)?\s*$")

RESULT_TO_PGN = {"red_win": "1-0", "black_win": "0-1", "draw": "1/2-1/2"}


class EngineTimeout(RuntimeError):
    """The engine did not answer within the configured deadline."""


class EngineCrash(RuntimeError):
    """The engine process exited or its pipe broke mid-search."""


@dataclass
class SearchResult:
    move: str = ""
    depth: int = 0
    nodes: int = 0
    nps: int = 0
    score_cp: int = 0
    info_lines: list[str] = field(default_factory=list)

    def to_json(self) -> dict[str, Any]:
        return asdict(self)


class UciEngine:
    """Long-lived UCI engine adapter for node-limited match play.

    Owns one engine subprocess for its whole lifetime. Deterministic search is
    achieved with ``Threads 1``, a fixed hash size and ``go nodes`` limits;
    ``ucinewgame`` is sent before every game to clear the transposition table.
    """

    def __init__(
        self,
        executable: str | Path | Sequence[str | Path],
        *,
        name: str | None = None,
        eval_file: str | Path | None = None,
        threads: int = 1,
        hash_mb: int = 16,
        timeout: float = 30.0,
    ) -> None:
        if timeout <= 0:
            raise ValueError("timeout must be positive")
        argv = [str(x) for x in executable] if not isinstance(executable, (str, Path)) else [str(executable)]
        if not argv:
            raise ValueError("engine command must not be empty")
        engine_path = Path(argv[0])
        if not engine_path.is_file():
            raise FileNotFoundError(f"engine not found: {engine_path}")
        if eval_file is not None and not Path(eval_file).is_file():
            raise FileNotFoundError(f"eval file not found: {eval_file}")
        self.name = name or engine_path.stem
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
        try:
            self._handshake(eval_file, threads, hash_mb)
        except Exception:
            self.close()
            raise

    def _read_output(self) -> None:
        assert self._process.stdout is not None
        try:
            for line in self._process.stdout:
                self._lines.put(line.rstrip("\r\n"))
        finally:
            self._lines.put(None)

    def _send(self, value: str) -> None:
        if self._process.poll() is not None:
            raise EngineCrash(f"{self.name} exited with code {self._process.returncode}")
        assert self._process.stdin is not None
        try:
            self._process.stdin.write(value + "\n")
            self._process.stdin.flush()
        except (BrokenPipeError, OSError) as error:
            raise EngineCrash(f"{self.name} pipe closed: {error}") from error

    def _next_line(self, deadline: float) -> str:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise EngineTimeout(f"{self.name} timed out waiting for output")
        try:
            line = self._lines.get(timeout=remaining)
        except queue.Empty as error:
            raise EngineTimeout(f"{self.name} timed out waiting for output") from error
        if line is None:
            raise EngineCrash(f"{self.name} exited while waiting for output (code {self._process.poll()})")
        return line

    def _wait_for(self, expected: str) -> None:
        deadline = time.monotonic() + self.timeout
        while True:
            line = self._next_line(deadline)
            if line == expected:
                return
            if "ERROR" in line:
                raise RuntimeError(f"{self.name}: {line}")

    def _handshake(self, eval_file: str | Path | None, threads: int, hash_mb: int) -> None:
        self._send("uci")
        self._wait_for("uciok")
        if eval_file is not None:
            self._send(f"setoption name EvalFile value {Path(eval_file).resolve()}")
        self._send(f"setoption name Threads value {max(1, int(threads))}")
        self._send(f"setoption name Hash value {max(1, int(hash_mb))}")
        self._send("isready")
        self._wait_for("readyok")

    def new_game(self) -> None:
        """Clear transposition-table state between games (UCI ``ucinewgame``)."""
        with self._lock:
            self._send("ucinewgame")
            self._send("isready")
            self._wait_for("readyok")

    def search(self, fen: str, nodes: int) -> SearchResult:
        """Search ``fen`` for exactly ``nodes`` nodes and return the best move."""
        if "\n" in fen or "\r" in fen or not fen.strip():
            raise ValueError("FEN must be a non-empty single line")
        if nodes <= 0:
            raise ValueError("nodes must be positive")
        with self._lock:
            self._send("position fen " + fen)
            self._send(f"go nodes {int(nodes)}")
            deadline = time.monotonic() + self.timeout
            result = SearchResult()
            while True:
                line = self._next_line(deadline)
                if line.startswith("info "):
                    result.info_lines.append(line)
                    self._merge_info(result, line)
                else:
                    match = BESTMOVE_PATTERN.match(line)
                    if match:
                        result.move = match.group(1)
                        return result

    @staticmethod
    def _merge_info(result: SearchResult, line: str) -> None:
        tokens = line.split()
        for index, token in enumerate(tokens):
            if token == "depth" and index + 1 < len(tokens):
                result.depth = int(tokens[index + 1])
            elif token == "nodes" and index + 1 < len(tokens):
                result.nodes = int(tokens[index + 1])
            elif token == "nps" and index + 1 < len(tokens):
                result.nps = int(tokens[index + 1])
            elif token == "score" and index + 2 < len(tokens):
                if tokens[index + 1] == "cp":
                    result.score_cp = int(tokens[index + 2])

    def close(self) -> None:
        with self._lock:
            if self._process.poll() is None:
                try:
                    self._send("quit")
                    self._process.wait(timeout=2)
                except (BrokenPipeError, subprocess.TimeoutExpired, EngineCrash):
                    self._process.kill()
                    self._process.wait(timeout=2)
            if self._process.stdin is not None:
                self._process.stdin.close()
            if self._process.stdout is not None:
                self._process.stdout.close()

    def __enter__(self) -> UciEngine:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()


@dataclass(frozen=True)
class Opening:
    fen: str
    moves: tuple[str, ...]


class NativeEnginePlayer:
    """JSON-protocol player for the native rules engine's ``analyze`` method.

    Lets the depth-limited baseline (or the greedy fallback) take part in
    matches through the same interface as :class:`UciEngine`: ``name``,
    ``new_game``, ``search`` and ``close``. ``search`` ignores the node budget
    (the baseline is depth-limited) and returns a single-move PV.
    """

    def __init__(
        self,
        executable: str | Path,
        *,
        name: str | None = None,
        difficulty: str = "baseline",
        depth: int = 3,
        timeout: float = 30.0,
    ) -> None:
        self.name = name or Path(executable).stem
        self.difficulty = difficulty
        self.depth = max(1, int(depth))
        self._rules = NativeRulesClient(executable, timeout=timeout)

    def new_game(self) -> None:
        self._rules.new_game()

    def search(self, fen: str, nodes: int) -> SearchResult:
        if "\n" in fen or "\r" in fen or not fen.strip():
            raise ValueError("FEN must be a non-empty single line")
        self._rules.load_fen(fen)
        data = self._rules._request(
            "analyze", difficulty=self.difficulty, depth=self.depth
        )
        pv = data.get("pv") or []
        result = SearchResult(
            move=pv[0] if pv else "",
            depth=int(data.get("depth", 0)),
            nodes=int(data.get("nodes", 0)),
            score_cp=int(data.get("scoreCp", 0)),
        )
        return result

    def close(self) -> None:
        self._rules.close()

    def __enter__(self) -> NativeEnginePlayer:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()


def generate_openings(
    rules: NativeRulesClient,
    *,
    seed: int,
    count: int,
    plies: int,
    initial_fen: str = INITIAL_FEN,
) -> list[Opening]:
    """Deterministic legal openings from a fixed seed.

    Each opening is produced by playing ``plies`` random legal moves from the
    initial position, validated by the rules referee, and archived as both the
    resulting FEN and the UCCI move sequence. Same seed => same openings.
    """
    if count <= 0 or plies < 0:
        raise ValueError("count must be positive and plies non-negative")
    rng = random.Random(seed)
    openings: list[Opening] = []
    for _ in range(count):
        rules.new_game()
        moves: list[str] = []
        fen = initial_fen
        for _ in range(plies):
            snapshot = rules.snapshot()
            if snapshot["result"]["kind"] != "ongoing":
                break
            legal = snapshot["legalMoves"]
            if not legal:
                break
            move = legal[rng.randrange(len(legal))]
            rules.play_move(move)
            moves.append(move)
            fen = rules.snapshot()["fen"]
        openings.append(Opening(fen=fen, moves=tuple(moves)))
    return openings


@dataclass
class GameRecord:
    game_id: int
    opening: Opening
    nodes: int
    moves: list[str] = field(default_factory=list)
    result: str = "ongoing"
    reason: str = ""
    engine_red: str = ""
    engine_black: str = ""
    searches: list[SearchResult] = field(default_factory=list)

    def to_json(self) -> dict[str, Any]:
        return {
            "game_id": self.game_id,
            "opening_fen": self.opening.fen,
            "opening_moves": list(self.opening.moves),
            "nodes": self.nodes,
            "moves": self.moves,
            "result": self.result,
            "reason": self.reason,
            "engine_red": self.engine_red,
            "engine_black": self.engine_black,
        }


def play_game(
    rules: NativeRulesClient,
    engines: dict[str, UciEngine | NativeEnginePlayer],
    opening: Opening,
    *,
    nodes: int,
    max_plies: int,
    game_id: int,
) -> GameRecord:
    """Play one game from ``opening`` with the referee adjudicating legality and the result.

    ``engines`` maps "red"/"black" to UCI engine adapters (the same engine may
    serve both sides). Timeouts, crashes and illegal moves forfeit the mover.
    """
    record = GameRecord(
        game_id=game_id,
        opening=opening,
        nodes=nodes,
        engine_red=engines["red"].name,
        engine_black=engines["black"].name,
    )
    rules.new_game()
    rules.load_fen(opening.fen)
    for engine in engines.values():
        engine.new_game()

    def forfeit(side: str, reason: str) -> GameRecord:
        record.result = "black_win" if side == "red" else "red_win"
        record.reason = reason
        return record

    for _ in range(max_plies):
        snapshot = rules.snapshot()
        result = snapshot["result"]
        if result["kind"] != "ongoing":
            record.result = result["kind"]
            record.reason = result["reason"]
            return record
        side = snapshot["sideToMove"]
        try:
            search = engines[side].search(snapshot["fen"], nodes)
        except EngineTimeout as error:
            return forfeit(side, f"timeout: {error}")
        except EngineCrash as error:
            return forfeit(side, f"crash: {error}")
        record.searches.append(search)
        if not search.move or search.move == "(none)":
            return forfeit(side, "no move")
        try:
            rules.play_move(search.move)
        except RulesProtocolError:
            return forfeit(side, f"illegal move: {search.move}")
        record.moves.append(search.move)
    record.result = "draw"
    record.reason = "max_plies"
    return record


def wilson_lower_bound(wins: int, draws: int, losses: int, z: float = 1.96) -> float:
    """Two-sided Wilson 95% (default) lower bound on score rate.

    Score counts a draw as half a point, matching chess convention. Returns 0.0
    for an empty sample.
    """
    total = wins + draws + losses
    if total <= 0:
        return 0.0
    score = (wins + 0.5 * draws) / total
    centre = (score + z * z / (2 * total)) / (1 + z * z / total)
    margin = z * math.sqrt(score * (1 - score) / total + z * z / (4 * total * total)) / (
        1 + z * z / total
    )
    return max(0.0, centre - margin)


def summarize_records(records: Sequence[GameRecord], candidate: str) -> dict[str, Any]:
    """Aggregate game records from the ``candidate`` engine's perspective."""
    wins = draws = losses = 0
    for record in records:
        if record.result == "draw":
            draws += 1
        elif (record.result == "red_win") == (candidate == record.engine_red):
            wins += 1
        else:
            losses += 1
    total = wins + draws + losses
    return {
        "candidate": candidate,
        "games": total,
        "wins": wins,
        "draws": draws,
        "losses": losses,
        "score_rate": (wins + 0.5 * draws) / total if total else 0.0,
        "wilson_95_lower_bound": wilson_lower_bound(wins, draws, losses),
    }


def write_pgn(record: GameRecord, path: Path) -> None:
    """Write a Xiangqi UCCI-move PGN-style archive for one game."""
    lines = [
        "[Event \"xiangqi-rl match\"]",
        "[Site \"?\"]",
        f"[Date \"{time.strftime('%Y.%m.%d')}\"]",
        f"[Round \"{record.game_id + 1}\"]",
        f"[White \"{record.engine_red}\"]",
        f"[Black \"{record.engine_black}\"]",
        f"[Result \"{RESULT_TO_PGN.get(record.result, '*')}\"]",
        f"[FEN \"{record.opening.fen}\"]",
        f"[SetUp \"1\"]",
        f"[Reason \"{record.reason}\"]",
        "",
        " ".join(record.moves) + " " + RESULT_TO_PGN.get(record.result, "*"),
        "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")


def write_ucci_log(record: GameRecord, path: Path) -> None:
    """Write the raw UCI ``info`` traffic plus best moves for audit."""
    lines = [
        f"# game {record.game_id} opening {record.opening.fen}",
        f"# moves: {' '.join(record.moves)}",
        f"# result: {record.result} ({record.reason})",
    ]
    for index, search in enumerate(record.searches):
        lines.append(f"# --- ply {index} ---")
        lines.extend(search.info_lines)
        lines.append(f"# bestmove {search.move}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def run_match(
    *,
    rules_command: str | Path,
    engines: dict[str, UciEngine | NativeEnginePlayer],
    seed: int,
    games: int,
    opening_plies: int,
    nodes: int,
    max_plies: int,
    out_dir: str | Path,
    candidate: str,
) -> dict[str, Any]:
    """Run ``games`` games with color reversal and archive everything to ``out_dir``.

    Opening ``i`` uses seed-derived opening ``i % len(openings)``; engine sides
    swap every game so each opening is played from both colors. Returns the
    aggregated summary for the ``candidate`` engine.
    """
    if games <= 0:
        raise ValueError("games must be positive")
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    with NativeRulesClient(rules_command) as rules:
        openings = generate_openings(rules, seed=seed, count=games, plies=opening_plies)
        records: list[GameRecord] = []
        for index in range(games):
            opening = openings[index % len(openings)]
            red, black = (engines["red"], engines["black"]) if index % 2 == 0 else (
                engines["black"],
                engines["red"],
            )
            record = play_game(
                rules,
                {"red": red, "black": black},
                opening,
                nodes=nodes,
                max_plies=max_plies,
                game_id=index,
            )
            records.append(record)
            write_pgn(record, out / f"game-{index:04d}.pgn")
            write_ucci_log(record, out / f"game-{index:04d}.ucci.log")
    summary = summarize_records(records, candidate)
    (out / "summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    with (out / "games.jsonl").open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record.to_json(), sort_keys=True) + "\n")
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Play deterministic UCI-engine Xiangqi matches with a rules referee"
    )
    parser.add_argument("--engine", action="append", help="UCI engine path (repeat for red/black)")
    parser.add_argument("--baseline", action="append", help="native engine used as baseline player (repeat for red/black)")
    parser.add_argument("--baseline-depth", type=int, default=3, help="depth for --baseline players")
    parser.add_argument("--eval-file", action="append", default=[], help="NNUE eval file per engine")
    parser.add_argument("--engine-name", action="append", default=[], help="engine display name")
    parser.add_argument("--rules-engine", required=True, help="native rules referee path")
    parser.add_argument("--seed", type=int, default=20260828)
    parser.add_argument("--games", type=int, default=800)
    parser.add_argument("--opening-plies", type=int, default=8)
    parser.add_argument("--nodes", type=int, default=5000)
    parser.add_argument("--max-plies", type=int, default=240)
    parser.add_argument("--threads", type=int, default=1)
    parser.add_argument("--hash-mb", type=int, default=16)
    parser.add_argument("--timeout", type=float, default=60.0)
    parser.add_argument("--candidate", default="", help="which engine the summary counts for")
    parser.add_argument("--out-dir", required=True)
    args = parser.parse_args()

    uci_paths = [Path(value) for value in args.engine or []]
    baseline_paths = [Path(value) for value in args.baseline or []]
    # A single entry duplicates to both sides (self-play / baseline mirror).
    if len(uci_paths) == 1 and not baseline_paths:
        uci_paths = [uci_paths[0], uci_paths[0]]
    if len(baseline_paths) == 1 and not uci_paths:
        baseline_paths = [baseline_paths[0], baseline_paths[0]]
    if len(uci_paths) + len(baseline_paths) != 2:
        parser.error("provide two players total: --engine and/or --baseline, each 1 or 2 entries")

    eval_files = list(args.eval_file) or [None, None]
    if len(eval_files) == 1:
        eval_files = [eval_files[0], eval_files[0]]
    if len(eval_files) != 2:
        parser.error("provide zero, one, or two --eval-file values")
    names = list(args.engine_name) or []
    if len(names) == 1:
        names = [names[0], names[0]]

    # Red is the first player listed, black the second. One UCI engine paired
    # with one baseline is the canonical candidate-vs-baseline setup.
    specs: list[tuple[str, Path]] = []
    for index in range(2):
        if index < len(uci_paths):
            specs.append(("uci", uci_paths[index]))
        else:
            specs.append(("baseline", baseline_paths[0]))
    if len(uci_paths) == 2:
        specs = [("uci", uci_paths[0]), ("uci", uci_paths[1])]
    if len(baseline_paths) == 2:
        specs = [("baseline", baseline_paths[0]), ("baseline", baseline_paths[1])]

    engines: dict[str, UciEngine | NativeEnginePlayer] = {}
    for index, (kind, path) in enumerate(specs):
        display = names[index] if index < len(names) and names[index] else path.stem
        side = ("red", "black")[index]
        if kind == "baseline":
            engines[side] = NativeEnginePlayer(
                path, name=display, difficulty="baseline",
                depth=args.baseline_depth, timeout=args.timeout,
            )
        else:
            engines[side] = UciEngine(
                path, name=display, eval_file=eval_files[index],
                threads=args.threads, hash_mb=args.hash_mb, timeout=args.timeout,
            )
    try:
        summary = run_match(
            rules_command=args.rules_engine,
            engines=engines,
            seed=args.seed,
            games=args.games,
            opening_plies=args.opening_plies,
            nodes=args.nodes,
            max_plies=args.max_plies,
            out_dir=args.out_dir,
            candidate=args.candidate or names[0],
        )
    finally:
        for engine in engines.values():
            engine.close()
    print(json.dumps(summary, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
