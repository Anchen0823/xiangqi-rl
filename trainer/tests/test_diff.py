import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

from xiangqi_nnue.diff import PerftReference, diff_positions, native_perft, random_positions
from xiangqi_nnue.rules import NativeRulesClient

RULES_ENGINE = Path(__file__).resolve().parents[2] / "build" / "native" / "xiangqi-engine.exe"
HAVE_RULES = RULES_ENGINE.is_file()

FAKE_REFERENCE = textwrap.dedent(
    """
    import sys
    for line in sys.stdin:
        parts = line.split()
        if not parts:
            continue
        command = parts[0]
        if command == "uci":
            print("id name fake-reference", flush=True)
            print("uciok", flush=True)
        elif command == "isready":
            print("readyok", flush=True)
        elif command == "position":
            pass
        elif command == "go" and len(parts) >= 3 and parts[1] == "perft":
            # Deterministic count derived from the FEN (held in "position").
            import hashlib
            digest = hashlib.sha256(b"fen").digest()
            count = 2 + int.from_bytes(digest[:2], "big") % 60
            print(f"Nodes searched: {count}", flush=True)
        elif command == "quit":
            break
    """
)

INITIAL_FEN = "rnbakabnr/9/1c5c1/p1p1p1p1p/9/9/P1P1P1P1P/1C5C1/9/RNBAKABNR w - - 0 1"


class RandomPositionTests(unittest.TestCase):
    def test_deterministic_and_legal(self):
        with tempfile.TemporaryDirectory() as directory:
            script = Path(directory) / "fake_rules.py"
            script.write_text(textwrap.dedent(
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
                        data = {"fen": fen, "legalMoves": pool,
                                "result": {"kind": "ongoing", "reason": ""}}
                    elif method == "loadFen":
                        fen = request["fen"]; history = []
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
                    elif method == "undo":
                        if history: history.pop()
                        data = {"fen": fen, "legalMoves": pool, "sideToMove": side,
                                "result": {"kind": "ongoing", "reason": ""}}
                    else:
                        data = {"fen": fen, "legalMoves": pool, "sideToMove": side,
                                "result": {"kind": "ongoing", "reason": ""}}
                    print(json.dumps({"id": request["id"], "ok": True, "data": data}),
                          flush=True)
                    if method == "quit":
                        break
                """
            ), encoding="utf-8")
            with NativeRulesClient([sys.executable, "-u", str(script)], timeout=5) as rules:
                first = random_positions(rules, count=4, min_plies=2, max_plies=5, seed=9)
                second = random_positions(rules, count=4, min_plies=2, max_plies=5, seed=9)
                other = random_positions(rules, count=4, min_plies=2, max_plies=5, seed=10)
        self.assertEqual(first, second)
        self.assertNotEqual(first, other)
        for fen in first:
            self.assertIn("moves=", fen)

    def test_invalid_arguments_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            script = Path(directory) / "fake_rules.py"
            script.write_text(textwrap.dedent(
                """
                import json, sys
                for line in sys.stdin:
                    request = json.loads(line)
                    if request["method"] == "quit":
                        break
                    print(json.dumps({"id": request["id"], "ok": True, "data": {
                        "fen": "9/9/9/9/9/9/9/9/9/9 w - - 0 1",
                        "legalMoves": ["a0a1"], "result": {"kind": "ongoing", "reason": ""}
                    }}), flush=True)
                """
            ), encoding="utf-8")
            with NativeRulesClient([sys.executable, "-u", str(script)], timeout=5) as rules:
                with self.assertRaises(ValueError):
                    random_positions(rules, count=0, min_plies=0, max_plies=0, seed=1)
                with self.assertRaises(ValueError):
                    random_positions(rules, count=1, min_plies=5, max_plies=2, seed=1)


class PerftReferenceTests(unittest.TestCase):
    def test_fake_reference_perft_parses(self):
        with tempfile.TemporaryDirectory() as directory:
            script = Path(directory) / "fake_ref.py"
            script.write_text(FAKE_REFERENCE, encoding="utf-8")
            with PerftReference([sys.executable, "-u", str(script)], timeout=5) as reference:
                count = reference.perft(INITIAL_FEN, 1)
        self.assertGreaterEqual(count, 2)
        self.assertLess(count, 62)


class DiffTests(unittest.TestCase):
    def test_diff_reports_mismatches(self):
        with tempfile.TemporaryDirectory() as directory:
            ref_script = Path(directory) / "fake_ref.py"
            ref_script.write_text(FAKE_REFERENCE, encoding="utf-8")
            rules_script = Path(directory) / "fake_rules.py"
            rules_script.write_text(textwrap.dedent(
                """
                import json, sys
                pool = ["a0a1", "b0b1", "c0c1", "d0d1", "e0e1", "f0f1", "g0g1", "h0h1"]
                fen = "9/9/9/9/9/9/9/9/9/9 w - - 0 1"
                for line in sys.stdin:
                    request = json.loads(line)
                    method = request["method"]
                    if method == "quit":
                        data = {"quitting": True}
                    elif method == "newGame":
                        data = {"fen": fen, "legalMoves": pool,
                                "result": {"kind": "ongoing", "reason": ""}}
                    elif method == "loadFen":
                        fen = request["fen"]
                        data = {"fen": fen, "legalMoves": pool,
                                "result": {"kind": "ongoing", "reason": ""}}
                    elif method == "snapshot":
                        data = {"fen": fen, "legalMoves": pool,
                                "result": {"kind": "ongoing", "reason": ""}}
                    elif method == "playMove":
                        data = {"fen": fen, "legalMoves": pool,
                                "result": {"kind": "ongoing", "reason": ""}}
                    elif method == "undo":
                        data = {"fen": fen, "legalMoves": pool,
                                "result": {"kind": "ongoing", "reason": ""}}
                    else:
                        data = {"fen": fen, "legalMoves": pool,
                                "result": {"kind": "ongoing", "reason": ""}}
                    print(json.dumps({"id": request["id"], "ok": True, "data": data}),
                          flush=True)
                    if method == "quit":
                        break
                """
            ), encoding="utf-8")
            with NativeRulesClient([sys.executable, "-u", str(rules_script)], timeout=5) as rules:
                with PerftReference([sys.executable, "-u", str(ref_script)], timeout=5) as reference:
                    report = diff_positions(
                        rules=rules, reference=reference,
                        positions=[INITIAL_FEN] * 3, depth=1,
                    )
        self.assertEqual(report["checked"], 3)
        self.assertEqual(report["matched"], 0)  # fake counts never equal 8
        self.assertEqual(len(report["mismatches"]), 3)


@unittest.skipUnless(HAVE_RULES, "requires native rules engine binary")
class NativePerftTests(unittest.TestCase):
    def test_native_perft_initial_position(self):
        # The native engine reports 44 legal moves on the initial position.
        with NativeRulesClient(RULES_ENGINE) as rules:
            count = native_perft(rules, INITIAL_FEN, 1)
        self.assertEqual(count, 44)


if __name__ == "__main__":
    unittest.main()
