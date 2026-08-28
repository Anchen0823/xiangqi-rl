import json
import math
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

from xiangqi_nnue.match import (
    INITIAL_FEN,
    BESTMOVE_PATTERN,
    EngineCrash,
    EngineTimeout,
    GameRecord,
    NativeEnginePlayer,
    Opening,
    UciEngine,
    generate_openings,
    play_game,
    sprt_llr,
    summarize_records,
    wilson_lower_bound,
    write_pgn,
    write_ucci_log,
)
from xiangqi_nnue.rules import NativeRulesClient

RULES_ENGINE = Path(__file__).resolve().parents[2] / "build" / "native" / "xiangqi-engine.exe"
PIKAFISH = Path(__file__).resolve().parents[2] / "native" / "bin" / "pikafish.exe"
CANDIDATE_NNUE = Path(__file__).resolve().parents[2] / "checkpoints" / "candidate-101.nnue"
HAVE_REAL_ENGINES = (
    RULES_ENGINE.is_file() and PIKAFISH.is_file() and CANDIDATE_NNUE.is_file()
)

FAKE_ENGINE_SCRIPT = textwrap.dedent(
    """
    import hashlib, sys
    pool = ["a0a1", "b0b1", "c0c1", "d0d1", "e0e1", "f0f1", "g0g1", "h0h1"]
    fen = ""
    for line in sys.stdin:
        parts = line.split()
        if not parts:
            continue
        command = parts[0]
        if command == "uci":
            print("id name fake-engine")
            print("uciok", flush=True)
        elif command == "isready":
            print("readyok", flush=True)
        elif command == "ucinewgame":
            pass
        elif command == "position":
            if len(parts) >= 3 and parts[1] == "fen":
                fen = " ".join(parts[2:])
        elif command == "go":
            nodes = int(parts[parts.index("nodes") + 1]) if "nodes" in parts else 1
            digest = hashlib.sha256(fen.encode("utf-8")).digest()
            move = pool[int.from_bytes(digest[:4], "big") % len(pool)]
            print(f"info depth 1 nodes {nodes} score cp 0", flush=True)
            print(f"bestmove {move}", flush=True)
        elif command == "quit":
            break
    """
)

FAKE_RULES_SCRIPT = textwrap.dedent(
    """
    import json, sys
    pool = ["a0a1", "b0b1", "c0c1", "d0d1", "e0e1", "f0f1", "g0g1", "h0h1"]
    history = []
    fen = "9/9/9/9/9/9/9/9/9/9 w - - 0 1"
    for line in sys.stdin:
        request = json.loads(line)
        method = request["method"]
        side = "red" if len(history) % 2 == 0 else "black"
        if method == "quit":
            data = {"quitting": True}
        elif method == "newGame":
            history = []
            fen = "9/9/9/9/9/9/9/9/9/9 w - - 0 1"
            data = {"fen": fen, "legalMoves": pool,
                    "result": {"kind": "ongoing", "reason": ""}}
        elif method == "loadFen":
            fen = request["fen"]
            history = []
            data = {"fen": fen, "legalMoves": pool,
                    "result": {"kind": "ongoing", "reason": ""}}
        elif method == "snapshot":
            data = {"fen": fen, "legalMoves": pool, "sideToMove": side,
                    "result": {"kind": "ongoing", "reason": ""}}
        elif method == "playMove":
            history.append(request["move"])
            fen = "9/9/9/9/9/9/9/9/9/9 w - - 0 1 moves=" + ",".join(history)
            data = {"fen": fen, "legalMoves": pool, "sideToMove": side,
                    "result": {"kind": "ongoing", "reason": ""}}
        else:
            data = {"fen": fen, "legalMoves": pool, "sideToMove": side,
                    "result": {"kind": "ongoing", "reason": ""}}
        print(json.dumps({"id": request["id"], "ok": True, "data": data}), flush=True)
        if method == "quit":
            break
    """
)


def write_script(directory: Path, name: str, source: str) -> Path:
    path = directory / name
    path.write_text(source, encoding="utf-8")
    return path


class BestMoveParsingTests(unittest.TestCase):
    def test_bestmove_with_ponder(self):
        match = BESTMOVE_PATTERN.match("bestmove b2b4 ponder b7b5")
        self.assertIsNotNone(match)
        self.assertEqual(match.group(1), "b2b4")

    def test_bestmove_plain(self):
        match = BESTMOVE_PATTERN.match("bestmove e2e4")
        self.assertIsNotNone(match)
        self.assertEqual(match.group(1), "e2e4")

    def test_fairy_coordinate_flip_maps_ranks_down(self):
        # Fairy-Stockfish ranks 1..10 from red's back rank; UCCI ranks 0..9.
        with tempfile.TemporaryDirectory() as directory:
            script = write_script(Path(directory), "fake_engine.py", FAKE_ENGINE_SCRIPT)
            with UciEngine([sys.executable, "-u", str(script)], name="fake",
                           coordinate_flip=True, timeout=10) as engine:
                self.assertEqual(engine._to_ucci("b2b4"), "b1b3")
                self.assertEqual(engine._to_ucci("e10e9"), "e9e8")
                self.assertEqual(engine._to_ucci("a1a2"), "a0a1")
                self.assertEqual(engine._to_ucci("h10g8"), "h9g7")


class WilsonTests(unittest.TestCase):
    def test_empty_sample_returns_zero(self):
        self.assertEqual(wilson_lower_bound(0, 0, 0), 0.0)

    def test_60_percent_of_800_is_below_gate(self):
        # Gate 1 requires the 95% lower bound to exceed 60%.
        self.assertLess(wilson_lower_bound(480, 0, 320), 0.60)

    def test_70_percent_of_800_clears_gate(self):
        self.assertGreater(wilson_lower_bound(560, 0, 240), 0.60)

    def test_draws_count_half(self):
        self.assertGreater(wilson_lower_bound(400, 800, 0), 0.60)


class EngineAdapterTests(unittest.TestCase):
    def test_missing_engine_raises(self):
        with self.assertRaises(FileNotFoundError):
            UciEngine(Path("does-not-exist.exe"))

    def test_fake_engine_search_is_deterministic_and_parseable(self):
        with tempfile.TemporaryDirectory() as directory:
            script = write_script(Path(directory), "fake_engine.py", FAKE_ENGINE_SCRIPT)
            with UciEngine([sys.executable, "-u", str(script)], name="fake", timeout=10) as engine:
                first = engine.search(INITIAL_FEN, 100)
                second = engine.search(INITIAL_FEN, 100)
                self.assertEqual(first.move, second.move)
                self.assertRegex(first.move, r"^[a-i][0-9][a-i][0-9]$")
                self.assertEqual(first.nodes, 100)


class FakeMatchTests(unittest.TestCase):
    def setUp(self):
        self._directory = tempfile.TemporaryDirectory()
        self.directory = Path(self._directory.name)
        self.engine_script = write_script(self.directory, "fake_engine.py", FAKE_ENGINE_SCRIPT)
        self.rules_script = write_script(self.directory, "fake_rules.py", FAKE_RULES_SCRIPT)

    def tearDown(self):
        self._directory.cleanup()

    def make_engines(self, name: str = "fake") -> dict[str, UciEngine]:
        return {
            "red": UciEngine([sys.executable, "-u", str(self.engine_script)], name=name, timeout=10),
            "black": UciEngine([sys.executable, "-u", str(self.engine_script)], name=name, timeout=10),
        }

    def test_openings_deterministic_for_fixed_seed(self):
        with NativeRulesClient([sys.executable, "-u", str(self.rules_script)], timeout=5) as rules:
            first = generate_openings(rules, seed=7, count=4, plies=3)
            second = generate_openings(rules, seed=7, count=4, plies=3)
            other = generate_openings(rules, seed=8, count=4, plies=3)
        self.assertEqual([o.fen for o in first], [o.fen for o in second])
        self.assertNotEqual([o.fen for o in first], [o.fen for o in other])

    def test_play_game_terminates_within_ply_limit(self):
        opening = Opening(fen=INITIAL_FEN, moves=())
        with NativeRulesClient([sys.executable, "-u", str(self.rules_script)], timeout=5) as rules:
            engines = self.make_engines()
            try:
                record = play_game(rules, engines, opening, nodes=100, max_plies=20, game_id=0)
            finally:
                for engine in engines.values():
                    engine.close()
        self.assertEqual(record.result, "draw")
        self.assertEqual(record.reason, "max_plies")
        self.assertEqual(len(record.moves), 20)
        self.assertEqual(record.engine_red, "fake")

    def test_record_json_is_stable(self):
        record = GameRecord(
            game_id=3,
            opening=Opening(fen=INITIAL_FEN, moves=("b2b4",)),
            nodes=100,
            moves=["b2b4", "b7b5"],
            result="draw",
            reason="max_plies",
            engine_red="fake",
            engine_black="fake",
        )
        payload = json.loads(json.dumps(record.to_json(), sort_keys=True))
        self.assertEqual(payload["game_id"], 3)
        self.assertEqual(payload["result"], "draw")
        self.assertEqual(payload["opening_moves"], ["b2b4"])

    def test_archive_writers_produce_deterministic_files(self):
        record = GameRecord(
            game_id=0,
            opening=Opening(fen=INITIAL_FEN, moves=()),
            nodes=100,
            moves=["b2b4"],
            result="red_win",
            reason="checkmate",
            engine_red="fake",
            engine_black="fake",
        )
        pgn = self.directory / "g.pgn"
        ucci = self.directory / "g.ucci.log"
        write_pgn(record, pgn)
        write_ucci_log(record, ucci)
        pgn_text = pgn.read_text(encoding="utf-8")
        self.assertIn('[Result "1-0"]', pgn_text)
        self.assertIn("b2b4 1-0", pgn_text)
        self.assertIn("# result: red_win (checkmate)", ucci.read_text(encoding="utf-8"))

    def test_summarize_records_from_candidate_perspective(self):
        records = [
            GameRecord(game_id=0, opening=Opening(fen=INITIAL_FEN, moves=()), nodes=1,
                       result="red_win", reason="m", engine_red="a", engine_black="b"),
            GameRecord(game_id=1, opening=Opening(fen=INITIAL_FEN, moves=()), nodes=1,
                       result="black_win", reason="m", engine_red="a", engine_black="b"),
            GameRecord(game_id=2, opening=Opening(fen=INITIAL_FEN, moves=()), nodes=1,
                       result="draw", reason="m", engine_red="a", engine_black="b"),
        ]
        summary = summarize_records(records, "a")
        self.assertEqual(summary["wins"], 1)
        self.assertEqual(summary["draws"], 1)
        self.assertEqual(summary["losses"], 1)
        self.assertAlmostEqual(summary["score_rate"], 0.5)
        # Balanced result at score 0.5 sits below the H1 hypothesis's bound.
        self.assertLess(summary["sprt_llr"], math.log(0.95 / 0.05))

    def test_sprt_llr_sign_and_bounds(self):
        # Clear dominance under H1 (score > 0.6) pushes LLR positive past the
        # H1 acceptance bound ln((1-beta)/alpha) for alpha=beta=0.05.
        dominant = sprt_llr(560, 0, 240)
        self.assertGreater(dominant, 0.0)
        self.assertGreater(dominant, math.log(0.95 / 0.05))
        # Clear deficit pushes LLR negative past the H0 acceptance bound.
        self.assertLess(sprt_llr(240, 0, 560), math.log(0.05 / 0.95))
        # All wins under h0=0.5 eventually pushes LLR past the H1 bound.
        self.assertGreater(sprt_llr(100, 0, 0), math.log(0.95 / 0.05))
        with self.assertRaises(ValueError):
            sprt_llr(1, 0, 0, h0=0.7, h1=0.6)
        with self.assertRaises(ValueError):
            sprt_llr(-1, 0, 0)


class NativeBaselinePlayerTests(unittest.TestCase):
    def setUp(self):
        self._directory = tempfile.TemporaryDirectory()
        self.directory = Path(self._directory.name)

    def tearDown(self):
        self._directory.cleanup()

    def make_fake_baseline(self):
        script = write_script(
            self.directory,
            "fake_baseline.py",
            textwrap.dedent(
                """
                import json, sys
                for line in sys.stdin:
                    request = json.loads(line)
                    method = request["method"]
                    if method == "quit":
                        data = {"quitting": True}
                    elif method == "loadFen":
                        data = {"fen": request.get("fen", ""), "legalMoves": [],
                                "result": {"kind": "ongoing", "reason": ""}}
                    elif method == "analyze":
                        data = {"depth": request.get("depth", 4), "nodes": 7, "nps": 0,
                                "scoreCp": 12, "mate": None, "backend": "baseline",
                                "pv": ["b2b4"]}
                    else:
                        data = {"fen": "9/9/9/9/9/9/9/9/9/9 w - - 0 1"}
                    print(json.dumps({"id": request["id"], "ok": True, "data": data}),
                          flush=True)
                    if method == "quit":
                        break
                """
            ),
        )
        return script

    def test_baseline_search_returns_engine_move(self):
        script = self.make_fake_baseline()
        with NativeEnginePlayer([sys.executable, "-u", str(script)], name="baseline",
                                difficulty="baseline", depth=4, timeout=10) as player:
            result = player.search(INITIAL_FEN, 5000)
            self.assertEqual(result.move, "b2b4")
            self.assertEqual(result.depth, 4)
            self.assertEqual(result.score_cp, 12)


@unittest.skipUnless(HAVE_REAL_ENGINES, "requires native rules engine and pikafish binaries")
class RealEngineDeterminismTests(unittest.TestCase):
    def test_same_engine_fixed_seed_two_games_byte_identical(self):
        """Plan exit criterion: same engine, fixed seed, 2 games => byte-identical results."""
        import json as jsonlib

        def run_once(directory: Path) -> list[str]:
            engines = {
                "red": UciEngine(PIKAFISH, name="pikafish", eval_file=CANDIDATE_NNUE,
                                 threads=1, hash_mb=16, timeout=60),
                "black": UciEngine(PIKAFISH, name="pikafish", eval_file=CANDIDATE_NNUE,
                                   threads=1, hash_mb=16, timeout=60),
            }
            try:
                with NativeRulesClient(RULES_ENGINE, timeout=20) as rules:
                    openings = generate_openings(rules, seed=42, count=2, plies=4)
                    records = [
                        play_game(
                            rules,
                            engines,
                            opening,
                            nodes=2000,
                            max_plies=120,
                            game_id=index,
                        )
                        for index, opening in enumerate(openings)
                    ]
            finally:
                for engine in engines.values():
                    engine.close()
            (directory / "games.jsonl").write_text(
                "".join(jsonlib.dumps(r.to_json(), sort_keys=True) + "\n" for r in records),
                encoding="utf-8",
            )
            return (directory / "games.jsonl").read_text(encoding="utf-8").splitlines()

        with tempfile.TemporaryDirectory() as first_dir, tempfile.TemporaryDirectory() as second_dir:
            first = run_once(Path(first_dir))
            second = run_once(Path(second_dir))
        self.assertEqual(first, second)
        for line in first:
            record = jsonlib.loads(line)
            self.assertIn(record["result"], ("red_win", "black_win", "draw"))


if __name__ == "__main__":
    unittest.main()
