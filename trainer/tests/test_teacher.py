import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

from xiangqi_nnue.teacher import FairyStockfishTeacher, MATE_SCORE


class TeacherTests(unittest.TestCase):
    def make_teacher(self, directory: str):
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
                    print("info depth 2 score mate -3 nodes 19 pv a0a1", flush=True)
                    print("bestmove a0a1", flush=True)
                elif line.startswith("go nodes"):
                    print("info depth 1 score cp 42 nodes 9 pv a0a1", flush=True)
                    print("bestmove a0a1", flush=True)
                elif line == "quit":
                    break
            """
        )
        script = Path(directory) / "fake_teacher.py"
        script.write_text(source, encoding="utf-8")
        return FairyStockfishTeacher([sys.executable, "-u", script], timeout=2)

    def test_centipawn_evaluation(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.make_teacher(directory) as teacher:
                result = teacher.evaluate_fen("9/9/9/9/9/9/9/9/9/9 w - - 0 1", 10)
            self.assertEqual(result.score_cp, 42)
            self.assertEqual(result.bestmove, "a0a1")
            self.assertEqual(result.nodes, 9)
            self.assertIsNone(result.mate_ply)

    def test_mate_evaluation_is_bounded(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.make_teacher(directory) as teacher:
                result = teacher.evaluate_fen("9/9/9/9/9/9/9/9/9/9 b - - 0 1", 20)
            self.assertEqual(result.score_cp, -(MATE_SCORE - 3))
            self.assertEqual(result.mate_ply, -3)

    def test_invalid_requests_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.make_teacher(directory) as teacher:
                with self.assertRaisesRegex(ValueError, "single line"):
                    teacher.evaluate_fen("bad\nquit", 10)
                with self.assertRaisesRegex(ValueError, "positive"):
                    teacher.evaluate_fen("valid w", 0)


if __name__ == "__main__":
    unittest.main()
