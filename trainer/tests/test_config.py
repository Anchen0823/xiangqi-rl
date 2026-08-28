import math
import tempfile
import unittest
from pathlib import Path

import torch

from xiangqi_nnue.config import TrainingConfig, cosine_warmup_lr
from xiangqi_nnue.model import NnueConfig, XiangqiNnue
from xiangqi_nnue.train import MetricAccumulator, evaluate_records, manifest_total_records
from xiangqi_nnue.dataset import DatasetProvenance, DatasetShardWriter, TrainingRecord
from xiangqi_nnue.features import PerspectiveFeatures, PositionFeatures

VALID_TOML = """
[model]
psq_feature_count = 16536
threat_feature_count = 45547
accumulator_size = 1024
hidden1 = 32
hidden2 = 32
layer_stacks = 16

[training]
seed = 823
batch_size = 8192
micro_batch_size = 1024
learning_rate = 0.001
weight_decay = 0.00001
warmup_steps = 500
checkpoint_seconds = 1800
memory_soft_limit_gib = 6.5
system_memory_limit_gib = 12.0
temperature_pause_c = 83
temperature_resume_c = 78
max_epochs = 10
val_interval_epochs = 0.5
early_stop_patience_epochs = 2.0
"""

FEATURES = PositionFeatures(
    1,
    (
        PerspectiveFeatures("red", 0, 0, False, (1,), (2,)),
        PerspectiveFeatures("black", 0, 0, False, (3,), (4,)),
    ),
)


class ConfigTests(unittest.TestCase):
    def test_valid_toml_loads_all_fields(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "train.toml"
            path.write_text(VALID_TOML, encoding="utf-8")
            config = TrainingConfig.from_toml(path)
        self.assertEqual(config.seed, 823)
        self.assertEqual(config.batch_size, 8192)
        self.assertEqual(config.micro_batch_size, 1024)
        self.assertEqual(config.accumulate, 8)
        self.assertEqual(config.learning_rate, 0.001)
        self.assertEqual(config.weight_decay, 0.00001)
        self.assertEqual(config.warmup_steps, 500)
        self.assertEqual(config.max_epochs, 10)
        self.assertEqual(config.val_interval_epochs, 0.5)
        self.assertEqual(config.early_stop_patience_epochs, 2.0)
        self.assertEqual(config.model.layer_stacks, 16)
        self.assertEqual(config.model.psq_feature_count, 16536)

    def test_missing_table_raises(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "bad.toml"
            path.write_text("[data]\nkey = 1\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "training"):
                TrainingConfig.from_toml(path)

    def test_accumulate_requires_divisible_batch(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "bad.toml"
            path.write_text(VALID_TOML.replace("batch_size = 8192", "batch_size = 8193"),
                            encoding="utf-8")
            config = TrainingConfig.from_toml(path)
        with self.assertRaisesRegex(ValueError, "multiple"):
            _ = config.accumulate

    def test_temperature_gate_ordering_is_checked(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "bad.toml"
            path.write_text(VALID_TOML.replace(
                "temperature_resume_c = 78", "temperature_resume_c = 90"), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "below"):
                TrainingConfig.from_toml(path)


class CosineWarmupTests(unittest.TestCase):
    def test_warmup_ramps_linearly(self):
        self.assertAlmostEqual(cosine_warmup_lr(0, 100, 1000, 0.001), 0.00001, places=8)
        self.assertAlmostEqual(cosine_warmup_lr(99, 100, 1000, 0.001), 0.001, places=8)

    def test_cosine_peak_after_warmup_then_decay(self):
        peak = cosine_warmup_lr(100, 100, 1000, 0.001)
        self.assertAlmostEqual(peak, 0.001, places=8)
        tail = cosine_warmup_lr(999, 100, 1000, 0.001)
        self.assertAlmostEqual(tail, 0.0, places=8)
        middle = cosine_warmup_lr(550, 100, 1000, 0.001)
        self.assertGreater(middle, 0.0)
        self.assertLess(middle, peak)

    def test_empty_schedule_returns_base(self):
        self.assertEqual(cosine_warmup_lr(0, 100, 0, 0.001), 0.001)


class MetricAccumulatorTests(unittest.TestCase):
    def test_perfect_prediction_has_zero_error_and_unit_correlation(self):
        accumulator = MetricAccumulator()
        target = torch.tensor([0.2, -0.4, 0.9], dtype=torch.float32)
        accumulator.update(target, target)
        summary = accumulator.summary()
        self.assertAlmostEqual(summary["huber"], 0.0, places=6)
        self.assertAlmostEqual(summary["mae"], 0.0, places=6)
        self.assertAlmostEqual(summary["pearson"], 1.0, places=6)
        self.assertEqual(summary["records"], 3)

    def test_anti_correlated_predictions(self):
        accumulator = MetricAccumulator()
        target = torch.tensor([-1.0, 0.0, 1.0], dtype=torch.float32)
        accumulator.update(-target, target)
        self.assertAlmostEqual(accumulator.summary()["pearson"], -1.0, places=6)

    def test_empty_accumulator_is_nan(self):
        summary = MetricAccumulator().summary()
        self.assertTrue(math.isnan(summary["huber"]))


class EvaluateRecordsTests(unittest.TestCase):
    def make_dataset(self, root: Path, count: int = 8):
        provenance = DatasetProvenance(
            "https://example.test/source", "0" * 64, "Example", "Teacher",
            "https://example.test/teacher", "1" * 64,
        )
        with DatasetShardWriter(root, "val", provenance, 2) as writer:
            for ply in range(count):
                record = TrainingRecord(
                    "9/9/9/9/9/9/9/9/9/9 w - - 0 1", ply * 100, None, ply,
                    FEATURES, 100, "a0a1",
                )
                writer.write(record)

    def test_evaluate_records_returns_bounded_metrics(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "val"
            self.make_dataset(root)
            self.assertEqual(manifest_total_records(root), 8)
            model = XiangqiNnue(NnueConfig(psq_feature_count=4, threat_feature_count=5,
                                           accumulator_size=4, hidden1=2, hidden2=2,
                                           layer_stacks=2)).eval()
            from xiangqi_nnue.dataset import read_records
            summary = evaluate_records(model, read_records(root), torch.device("cpu"),
                                       micro_batch=3)
        self.assertEqual(summary["records"], 8)
        self.assertTrue(math.isfinite(summary["huber"]))
        self.assertTrue(math.isfinite(summary["mae"]))
        self.assertTrue(-1.0 <= summary["pearson"] <= 1.0)


if __name__ == "__main__":
    unittest.main()
