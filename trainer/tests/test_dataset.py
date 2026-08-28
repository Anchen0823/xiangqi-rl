import json
import tempfile
import unittest
from pathlib import Path

from xiangqi_nnue.dataset import (
    DatasetProvenance,
    DatasetShardWriter,
    TrainingRecord,
    read_records,
)
from xiangqi_nnue.features import PerspectiveFeatures, PositionFeatures


def provenance(**changes):
    values = {
        "source_url": "https://example.test/odbl-games",
        "attribution": "Example ODbL collection",
        "teacher_name": "Example CC0 teacher",
        "teacher_url": "https://example.test/cc0-teacher",
    }
    values.update(changes)
    return DatasetProvenance(**values)


def record(ply):
    features = PositionFeatures(
        layer_bucket=ply % 16,
        perspectives=(
            PerspectiveFeatures("red", 1, 2, False, (1, 2), (3,)),
            PerspectiveFeatures("black", 2, 1, True, (4,), (5, 6)),
        ),
    )
    return TrainingRecord(
        fen="9/9/9/9/9/9/9/9/9/9 w - - 0 1",
        score_cp=ply * 10,
        outcome=0.0,
        ply=ply,
        features=features,
    )


class DatasetTests(unittest.TestCase):
    def test_atomic_shards_resume_and_round_trip(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            with DatasetShardWriter(directory, "sample", provenance(), 2) as writer:
                writer.write(record(0))
                writer.write(record(1))
                writer.write(record(2))
            with DatasetShardWriter(directory, "sample", provenance(), 2) as writer:
                writer.write(record(3))

            manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["totalRecords"], 4)
            self.assertEqual([item["records"] for item in manifest["shards"]], [2, 1, 1])
            self.assertEqual([item.ply for item in read_records(directory)], [0, 1, 2, 3])
            self.assertFalse(list(directory.glob("*.partial")))

    def test_checksum_corruption_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            with DatasetShardWriter(directory, "sample", provenance(), 1) as writer:
                writer.write(record(0))
            shard = next(directory.glob("*.jsonl.gz"))
            with shard.open("ab") as stream:
                stream.write(b"tamper")
            with self.assertRaisesRegex(ValueError, "checksum mismatch"):
                list(read_records(directory))

    def test_restricted_licenses_are_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaisesRegex(ValueError, "CC0"):
                DatasetShardWriter(
                    Path(temporary),
                    "sample",
                    provenance(teacher_license="GPL-3.0-only"),
                )

    def test_invalid_record_is_rejected_before_write(self):
        invalid = TrainingRecord(
            fen="bad\nfen",
            score_cp=0,
            outcome=0.0,
            ply=0,
            features=record(0).features,
        )
        with tempfile.TemporaryDirectory() as temporary:
            with DatasetShardWriter(Path(temporary), "sample", provenance()) as writer:
                with self.assertRaisesRegex(ValueError, "single line"):
                    writer.write(invalid)
            self.assertFalse(list(Path(temporary).glob("*.jsonl.gz")))


if __name__ == "__main__":
    unittest.main()
