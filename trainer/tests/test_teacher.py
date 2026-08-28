import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

from xiangqi_nnue.teacher import FairyStockfishTeacher, MATE_SCORE, fairy_move_to_ucci


class TeacherTests(unittest.TestCase):
    def make_teacher(self, directory: str):
        # Fake teacher speaks Fairy-Stockfish coordinates: files a-i, ranks 1..10
        # from red's back rank (e.g. "b2b4" = UCCI "b1b3").
        source = textwrap.dedent(
            """
            import sys
            for raw in sys.stdin:
                line = raw.strip()
                if line == "uci":
                    print("id name fake", flush=True)
                    print("uciok", flush=True)
                elif line == "isready":
                    print("readyok", flush=True)
                elif line == "go nodes 20":
                    print("info depth 2 score mate -3 nodes 19 pv b2b4", flush=True)
                    print("bestmove b2b4", flush=True)
                elif line.startswith("go nodes"):
                    print("info depth 1 score cp 42 nodes 9 pv h10g8", flush=True)
                    print("bestmove h10g8", flush=True)
                elif line == "quit":
                    break
            """
        )
        script = Path(directory) / "fake_teacher.py"
        script.write_text(source, encoding="utf-8")
        return FairyStockfishTeacher([sys.executable, "-u", script], timeout=2)

    def test_centipawn_evaluation_converts_coordinates(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.make_teacher(directory) as teacher:
                result = teacher.evaluate_fen("9/9/9/9/9/9/9/9/9/9 w - - 0 1", 10)
            self.assertEqual(result.score_cp, 42)
            self.assertEqual(result.bestmove, "h9g7")  # Fairy h10g8 -> UCCI h9g7
            self.assertEqual(result.nodes, 9)
            self.assertIsNone(result.mate_ply)

    def test_mate_evaluation_is_bounded_and_converts(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.make_teacher(directory) as teacher:
                result = teacher.evaluate_fen("9/9/9/9/9/9/9/9/9/9 b - - 0 1", 20)
            self.assertEqual(result.score_cp, -(MATE_SCORE - 3))
            self.assertEqual(result.mate_ply, -3)
            self.assertEqual(result.bestmove, "b1b3")  # Fairy b2b4 -> UCCI b1b3

    def test_invalid_requests_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.make_teacher(directory) as teacher:
                with self.assertRaisesRegex(ValueError, "single line"):
                    teacher.evaluate_fen("bad\nquit", 10)
                with self.assertRaisesRegex(ValueError, "positive"):
                    teacher.evaluate_fen("valid w", 0)

    def test_fairy_move_converter_round_trip(self):
        self.assertEqual(fairy_move_to_ucci("a1a2"), "a0a1")
        self.assertEqual(fairy_move_to_ucci("e10e9"), "e9e8")
        self.assertEqual(fairy_move_to_ucci("h10g8"), "h9g7")
        with self.assertRaises(ValueError):
            fairy_move_to_ucci("z0z1")


if __name__ == "__main__":
    unittest.main()
