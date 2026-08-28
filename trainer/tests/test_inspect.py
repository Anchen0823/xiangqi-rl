import tempfile
import unittest
from pathlib import Path

from xiangqi_nnue.dataset import DatasetProvenance, DatasetShardWriter, TrainingRecord
from xiangqi_nnue.features import PerspectiveFeatures, PositionFeatures
from xiangqi_nnue.inspect import inspect_dataset

FEATURES = PositionFeatures(
    1,
    (
        PerspectiveFeatures("red", 0, 0, False, (1,), (2,)),
        PerspectiveFeatures("black", 0, 0, False, (3,), (4,)),
    ),
)


def make_dataset(root: Path, records: list[TrainingRecord]) -> None:
    provenance = DatasetProvenance(
        "https://example.test/source", "0" * 64, "Example", "Teacher",
        "https://example.test/teacher", "1" * 64,
    )
    with DatasetShardWriter(root, "inspect", provenance, 50) as writer:
        for record in records:
            writer.write(record)


def record(fen: str, score: int, outcome, ply: int, nodes: int = 5000, bestmove: str = "a0a1"):
    return TrainingRecord(fen, score, outcome, ply, FEATURES, nodes, bestmove)


class InspectDatasetTests(unittest.TestCase):
    def test_distributions_and_duplicates(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "data"
            make_dataset(root, [
                record("fen-a", 100, None, 0),
                record("fen-b", -200, 1.0, 1),
                record("fen-c", 300, -1.0, 2),
                record("fen-a", 100, None, 3),  # duplicate FEN
            ])
            report = inspect_dataset(root)
        self.assertEqual(report["inspected_records"], 4)
        self.assertEqual(report["duplicate_fen_records"], 1)
        self.assertAlmostEqual(report["duplicate_fen_ratio"], 0.25)
        self.assertEqual(report["score_cp"]["min"], -200)
        self.assertEqual(report["score_cp"]["max"], 300)
        self.assertEqual(report["score_cp"]["count"], 4)
        self.assertEqual(report["outcomes"], {"none": 2, "red": 1, "black": 1, "draw": 0})
        self.assertEqual(report["unique_fens"], 3)
        self.assertEqual(report["teacher_nodes"]["min"], 5000)

    def test_max_records_limits_scan(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "data"
            make_dataset(root, [record(f"fen-{i}", i * 10, None, i) for i in range(6)])
            report = inspect_dataset(root, max_records=2)
        self.assertEqual(report["inspected_records"], 2)

    def test_missing_manifest_raises(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(FileNotFoundError):
                inspect_dataset(Path(directory) / "nope")

    def test_legality_sample_requires_rules_engine(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "data"
            make_dataset(root, [record("fen-a", 100, None, 0)])
            with self.assertRaisesRegex(ValueError, "rules-engine"):
                inspect_dataset(root, legality_sample=5)


if __name__ == "__main__":
    unittest.main()
