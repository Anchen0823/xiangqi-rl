import json
import tempfile
import unittest
from pathlib import Path

from xiangqi_nnue.dataset import DatasetProvenance, DatasetShardWriter, read_records
from xiangqi_nnue.features import PerspectiveFeatures, PositionFeatures
from xiangqi_nnue.label import SourcePosition, file_sha256, label_records, read_source
from xiangqi_nnue.teacher import TeacherEvaluation


FEATURES = PositionFeatures(
    1,
    (
        PerspectiveFeatures("red", 0, 0, False, (1,), (2,)),
        PerspectiveFeatures("black", 0, 0, False, (3,), (4,)),
    ),
)


class FakeFeatures:
    def fen(self, fen):
        return FEATURES


class FakeTeacher:
    def __init__(self):
        self.calls = 0

    def evaluate_fen(self, fen, nodes):
        self.calls += 1
        return TeacherEvaluation(75, "a0a1", nodes + 1)


class LabelTests(unittest.TestCase):
    def test_source_hash_parse_label_and_resume(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "positions.jsonl"
            source.write_text(
                json.dumps({"fen": "9/9/9/9/9/9/9/9/9/9 w - - 0 1", "ply": 7})
                + "\n"
                + json.dumps(
                    {
                        "fen": "9/9/9/9/9/9/9/9/9/9 b - - 0 1",
                        "ply": 8,
                        "outcome": -1.0,
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            provenance = DatasetProvenance(
                "https://example.test/source",
                file_sha256(source),
                "Example",
                "Teacher",
                "https://example.test/teacher",
                "1" * 64,
            )
            output = root / "dataset"
            with DatasetShardWriter(output, "labels", provenance, 1) as writer:
                count = label_records(
                    read_source(source), writer, FakeFeatures(), FakeTeacher(), nodes=10, limit=1
                )
            self.assertEqual(count, 1)
            with DatasetShardWriter(output, "labels", provenance, 1) as writer:
                count = label_records(
                    read_source(source),
                    writer,
                    FakeFeatures(),
                    FakeTeacher(),
                    nodes=10,
                    skip=writer.manifest["totalRecords"],
                )
            self.assertEqual(count, 1)
            records = list(read_records(output))
            self.assertEqual([record.score_cp for record in records], [75, 75])
            self.assertEqual([record.teacher_nodes for record in records], [11, 11])
            self.assertEqual([record.bestmove for record in records], ["a0a1", "a0a1"])
            self.assertEqual([record.outcome for record in records], [None, -1.0])

    def test_invalid_source_reports_line(self):
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "bad.jsonl"
            source.write_text('{"ply": 1}\n', encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "line 1"):
                list(read_source(source))

    def test_cached_teacher_evaluation_skips_engine_search(self):
        source = iter([
            SourcePosition(
                "9/9/9/9/9/9/9/9/9/9 w - - 0 1",
                0,
                0.0,
                teacher_score_cp=123,
                teacher_nodes=2001,
                teacher_bestmove="c3c4",
            )
        ])
        teacher = FakeTeacher()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            provenance = DatasetProvenance(
                "generated:test", "0" * 64, "Example", "Teacher",
                "https://example.test/teacher", "1" * 64,
            )
            with DatasetShardWriter(root, "cached", provenance, 1) as writer:
                label_records(source, writer, FakeFeatures(), teacher, nodes=10)
            result = next(read_records(root))
        self.assertEqual(teacher.calls, 0)
        self.assertEqual(result.score_cp, 123)
        self.assertEqual(result.teacher_nodes, 2001)
        self.assertEqual(result.bestmove, "c3c4")


if __name__ == "__main__":
    unittest.main()
