import unittest

import torch

from xiangqi_nnue.model import (
    NnueConfig,
    XiangqiNnue,
    clipped_relu,
    squared_clipped_relu,
)


def sparse(feature_count: int, batch: int = 3, active: int = 2):
    indices = torch.arange(batch * active) % feature_count
    offsets = torch.arange(0, (batch + 1) * active, active)
    return indices, offsets


class NnueTests(unittest.TestCase):
    def setUp(self):
        self.config = NnueConfig(
            psq_feature_count=128,
            threat_feature_count=96,
            accumulator_size=16,
            hidden1=8,
            hidden2=8,
            layer_stacks=4,
        )

    def test_shape_and_backward(self):
        model = XiangqiNnue(self.config)
        psq = sparse(self.config.psq_feature_count)
        threat = sparse(self.config.threat_feature_count)
        buckets = torch.tensor([0, 1, 1])
        output = model(*psq, *threat, *psq, *threat, buckets)
        self.assertEqual(tuple(output.shape), (3,))
        output.sum().backward()
        self.assertIsNotNone(model.psq_features.weight.grad)
        self.assertIsNotNone(model.threat_features.weight.grad)
        self.assertIsNotNone(model.stacks[0].hidden1.weight.grad)
        self.assertIsNotNone(model.stacks[1].hidden1.weight.grad)

    def test_pikafish_dimensions_and_layer_layout(self):
        config = NnueConfig()
        self.assertEqual(config.psq_feature_count, 16_536)
        self.assertEqual(config.threat_feature_count, 45_547)
        model = XiangqiNnue(self.config)
        self.assertEqual(model.stacks[0].hidden1.in_features, 16)
        self.assertEqual(model.stacks[0].output.in_features, 32)
        self.assertEqual(len(model.stacks), 4)

    def test_pairwise_accumulator_transform(self):
        accumulator = torch.tensor([[0.5, -1.0, 0.2, 2.0]])
        actual = XiangqiNnue._transform_perspective(accumulator)
        torch.testing.assert_close(actual, torch.tensor([[0.1, 0.0]]))

    def test_activation_values(self):
        values = torch.tensor([-1.0, 0.5, 2.0])
        torch.testing.assert_close(clipped_relu(values), torch.tensor([0.0, 0.5, 1.0]))
        torch.testing.assert_close(squared_clipped_relu(values), torch.tensor([0.0, 0.25, 1.0]))

    def test_invalid_bucket_is_rejected(self):
        model = XiangqiNnue(self.config)
        psq = sparse(self.config.psq_feature_count)
        threat = sparse(self.config.threat_feature_count)
        with self.assertRaisesRegex(ValueError, "outside"):
            model(*psq, *threat, *psq, *threat, torch.tensor([0, 1, 4]))

    def test_autocast_bucket_merge_uses_dense_output_dtype(self):
        model = XiangqiNnue(self.config)
        psq = sparse(self.config.psq_feature_count)
        threat = sparse(self.config.threat_feature_count)
        with torch.autocast("cpu", dtype=torch.bfloat16):
            output = model(*psq, *threat, *psq, *threat, torch.tensor([0, 1, 1]))
        self.assertEqual(tuple(output.shape), (3,))
        output.sum().backward()


if __name__ == "__main__":
    unittest.main()
