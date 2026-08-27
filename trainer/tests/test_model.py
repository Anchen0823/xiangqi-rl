import unittest

import torch

from xiangqi_nnue.model import NnueConfig, XiangqiNnue, squared_clipped_relu


class NnueTests(unittest.TestCase):
    def test_shape_and_backward(self):
        model = XiangqiNnue(NnueConfig(feature_count=128, accumulator_size=16))
        indices = torch.tensor([1, 2, 3, 4, 5, 6])
        offsets = torch.tensor([0, 2, 4, 6])
        output = model(indices, offsets, indices.flip(0), offsets)
        self.assertEqual(tuple(output.shape), (3,))
        output.sum().backward()
        self.assertIsNotNone(model.features.weight.grad)

    def test_squared_clipped_activation(self):
        actual = squared_clipped_relu(torch.tensor([-1.0, 0.5, 2.0]))
        torch.testing.assert_close(actual, torch.tensor([0.0, 0.25, 1.0]))


if __name__ == "__main__":
    unittest.main()
