import json
import random
import tempfile
import unittest
from pathlib import Path

from xiangqi_nnue.selfplay import SelfplaySourceWriter, play_game
from xiangqi_nnue.teacher import TeacherEvaluation, fairy_move_to_ucci
from xiangqi_nnue.label import file_sha256, read_source


class FakeRules:
    def __init__(self):
        self.ply = 0

    def state(self):
        return {
            "fen": f"9/9/9/9/9/9/9/9/9/9 {'w' if self.ply % 2 == 0 else 'b'} - - 0 1",
            "legalMoves": ["a0a1", "b0b1"],
            "result": {"kind": "red_win" if self.ply >= 2 else "ongoing", "reason": "mate" if self.ply >= 2 else ""},
        }

    def new_game(self):
        self.ply = 0
        return self.state()

    def play_move(self, move):
        self.ply += 1
        return self.state()


class FakeTeacher:
    def evaluate_fen(self, fen, nodes):
        # evaluate_fen now returns UCCI moves directly.
        return TeacherEvaluation(10, "a0a1", nodes)


class SelfplayTests(unittest.TestCase):
    def test_fairy_one_based_ranks_convert_to_ucci(self):
        self.assertEqual(fairy_move_to_ucci("c4c5"), "c3c4")
        self.assertEqual(fairy_move_to_ucci("a10a9"), "a9a8")
        with self.assertRaisesRegex(ValueError, "invalid"):
            fairy_move_to_ucci("a0a1")

    def test_game_assigns_side_to_move_outcomes(self):
        game = play_game(
            FakeRules(), FakeTeacher(), random.Random(1),
            nodes=10, max_plies=10, random_plies=0,
        )
        self.assertEqual(game.result, "red_win")
        self.assertEqual([item["outcome"] for item in game.positions], [1.0, -1.0])
        self.assertEqual([item["teacherBestmove"] for item in game.positions], ["a0a1", "a0a1"])
        self.assertEqual([item["teacherNodes"] for item in game.positions], [10, 10])

    def test_writer_resumes_and_rejects_config_change(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            game = play_game(
                FakeRules(), FakeTeacher(), random.Random(1),
                nodes=10, max_plies=10, random_plies=0,
            )
            SelfplaySourceWriter(root, {"seed": 1}).add(game)
            resumed = SelfplaySourceWriter(root, {"seed": 1})
            self.assertEqual(resumed.manifest["totalRecords"], 2)
            self.assertEqual(len(resumed.manifest["games"]), 1)
            with self.assertRaisesRegex(ValueError, "configuration"):
                SelfplaySourceWriter(root, {"seed": 2})
            manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["license"], "ODbL-1.0")
            self.assertEqual(len(list(read_source(root))), 2)
            self.assertEqual(file_sha256(root), file_sha256(root / "manifest.json"))

    def test_source_reader_rejects_corrupt_game(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            game = play_game(
                FakeRules(), FakeTeacher(), random.Random(1),
                nodes=10, max_plies=10, random_plies=0,
            )
            SelfplaySourceWriter(root, {"seed": 1}).add(game)
            with (root / "game-000000.jsonl").open("a", encoding="utf-8") as stream:
                stream.write("tamper")
            with self.assertRaisesRegex(ValueError, "checksum mismatch"):
                list(read_source(root))


if __name__ == "__main__":
    unittest.main()
