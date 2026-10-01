import tempfile
import unittest
from unittest.mock import patch

import torch
from pathlib import Path

from xiangqi_nnue.dataset import DatasetProvenance, DatasetShardWriter, TrainingRecord
from xiangqi_nnue.features import PerspectiveFeatures, PositionFeatures
from xiangqi_nnue.train import StreamingBatchSource, training_target
from xiangqi_nnue import train


FEATURES = PositionFeatures(
    1,
    (
        PerspectiveFeatures("red", 0, 0, False, (1,), (2,)),
        PerspectiveFeatures("black", 0, 0, False, (3,), (4,)),
    ),
)


def record(ply):
    return TrainingRecord(
        "9/9/9/9/9/9/9/9/9/9 w - - 0 1", ply * 100, None, ply,
        FEATURES, 100, "a0a1",
    )


class TrainDataTests(unittest.TestCase):
    def make_dataset(self, root):
        provenance = DatasetProvenance(
            "https://example.test/source", "0" * 64, "Example", "Teacher",
            "https://example.test/teacher", "1" * 64,
        )
        with DatasetShardWriter(root, "train", provenance, 2) as writer:
            for ply in range(6):
                writer.write(record(ply))

    def test_stream_state_resumes_exact_next_batch(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.make_dataset(root)
            with StreamingBatchSource(root, batch_size=2, shuffle_buffer=4, seed=7) as first:
                first.next_batch()
                state = first.state_dict()
                expected = [item.ply for item in first.next_batch()]
            with StreamingBatchSource(root, batch_size=2, shuffle_buffer=4, seed=999) as resumed:
                resumed.load_state_dict(state)
                self.assertEqual([item.ply for item in resumed.next_batch()], expected)

    def test_stream_crosses_epoch_without_empty_batches(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.make_dataset(root)
            with StreamingBatchSource(root, batch_size=4, shuffle_buffer=4) as stream:
                self.assertEqual(len(stream.next_batch()), 4)
                self.assertEqual(len(stream.next_batch()), 4)

    def test_teacher_target_is_bounded_and_blends_outcome(self):
        neutral = record(0)
        self.assertEqual(training_target(neutral), 0.0)
        decisive = TrainingRecord(neutral.fen, 32_000, -1.0, 0, FEATURES, 100, "a0a1")
        self.assertLess(training_target(decisive), 1.0)
        self.assertGreater(training_target(decisive), 0.6)

    def test_early_stop_checkpoint_and_best_are_resumable(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.make_dataset(root / "data")
            config = root / "tiny.toml"
            config.write_text('''[model]
psq_feature_count = 16
threat_feature_count = 16
accumulator_size = 4
hidden1 = 4
hidden2 = 2
layer_stacks = 16
[training]
batch_size = 2
micro_batch_size = 2
warmup_steps = 0
val_interval_epochs = 0.5
early_stop_patience_epochs = 0.5
''')
            latest, best = root / "latest.pt", root / "best.pt"
            argv = ["train", "--config", str(config), "--dataset", str(root / "data"),
                    "--val-dataset", str(root / "data"), "--steps", "20",
                    "--checkpoint", str(latest), "--best-checkpoint", str(best),
                    "--metrics", str(root / "logs" / "metrics.jsonl")]
            with patch("sys.argv", argv), patch.object(torch.cuda, "is_available", return_value=False), \
                 patch.object(train, "wait_for_safe_temperature"), \
                 patch.object(train, "evaluate_records", side_effect=[{"huber": 0.1}, {"huber": 0.2}]), \
                 patch("builtins.print"):
                train.main()
            saved = torch.load(latest, weights_only=False)
            self.assertEqual(saved["step"], 1)
            self.assertEqual(saved["best_val_huber"], 0.1)
            selected = torch.load(best, weights_only=False)
            self.assertEqual(selected["step"], -1)
            self.assertIn("data", selected)
            self.assertIn("dataset_manifest_sha256", selected)

            # Continuing must retain the historical best and real step number.
            with patch("sys.argv", argv + ["--resume"]), \
                 patch.object(torch.cuda, "is_available", return_value=False), \
                 patch.object(train, "wait_for_safe_temperature"), \
                 patch.object(train, "evaluate_records", return_value={"huber": 0.2}), \
                 patch("builtins.print"):
                train.main()
            resumed = torch.load(latest, weights_only=False)
            self.assertEqual(resumed["step"], 2)
            self.assertEqual(resumed["best_val_huber"], 0.1)
            self.assertEqual(torch.load(best, weights_only=False)["step"], -1)


if __name__ == "__main__":
    unittest.main()
