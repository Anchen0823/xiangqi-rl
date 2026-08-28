import io
import tempfile
import unittest
from pathlib import Path

import numpy as np
import torch

from xiangqi_nnue.export_nnue import (
    NETWORK_MAGIC,
    NETWORK_VERSION,
    QuantizedNetwork,
    QuantizedLayerStack,
    feature_transformer_hash,
    network_architecture_hash,
    network_hash,
    quantize_state_dict,
    write_leb128_signed,
    write_nnue,
)
from xiangqi_nnue.features import PikafishFeatureClient
from xiangqi_nnue.model import XiangqiNnue
from xiangqi_nnue.parity import (
    PikafishEvalClient,
    float_forward_internal,
    simulate_quantized_forward,
)

try:
    import zstandard  # noqa: F401

    HAVE_ZSTD = True
except ImportError:
    HAVE_ZSTD = False

ENGINE = Path(__file__).resolve().parents[2] / "native" / "bin" / "pikafish.exe"
INITIAL_FEN = "rnbakabnr/9/1c5c1/p1p1p1p1p/9/9/P1P1P1P1P/1C5C1/9/RNBAKABNR w - - 0 1"


class Leb128Tests(unittest.TestCase):
    def test_known_signed_values_match_pikafish_encoder(self):
        stream = io.BytesIO()
        write_leb128_signed(stream, [-4, 124])
        expected = NETWORK_MAGIC + (3).to_bytes(4, "little") + bytes([0x7C, 0xFC, 0x00])
        self.assertEqual(stream.getvalue(), expected)

    def test_negative_boundary_round_trip_shape(self):
        stream = io.BytesIO()
        write_leb128_signed(stream, [0, 1, -1, 64, -64, -65, 127, -127, -128, 128, 4096, -4096])
        payload = stream.getvalue()
        self.assertEqual(payload[: len(NETWORK_MAGIC)], NETWORK_MAGIC)
        count = int.from_bytes(payload[len(NETWORK_MAGIC):len(NETWORK_MAGIC) + 4], "little")
        self.assertEqual(count, len(payload) - len(NETWORK_MAGIC) - 4)


class HashTests(unittest.TestCase):
    def test_hashes_match_pinned_pikafish_constants(self):
        # These values were cross-checked against a standalone C++ program
        # compiled from native/vendor/Pikafish headers at revision b97ef0f.
        self.assertEqual(feature_transformer_hash(), 0x23F47EB0)
        self.assertEqual(network_architecture_hash(), 0x63337116)
        self.assertEqual(network_hash(), 0x40C70FA6)
        self.assertEqual(NETWORK_VERSION, 0x6A448AFA)


class QuantizationTests(unittest.TestCase):
    def test_layer_biases_use_pikafish_int32_layout(self):
        # Layer OutputType is i32; only the feature-transformer bias is i16.
        layer = QuantizedLayerStack(
            fc0_bias=np.zeros(32, dtype=np.int32),
            fc0_weight=np.zeros((32, 1024), dtype=np.int8),
            fc1_bias=np.zeros(32, dtype=np.int32),
            fc1_weight=np.zeros((32, 64), dtype=np.int8),
            fc2_bias=np.zeros(1, dtype=np.int32),
            fc2_weight=np.zeros((1, 128), dtype=np.int8),
        )
        self.assertEqual(layer.fc0_bias.dtype, np.int32)
        self.assertEqual(layer.fc2_bias.dtype, np.int32)
        layer.validate()

    def test_full_state_dict_quantizes_to_expected_shapes(self):
        model = XiangqiNnue().eval()
        quantized = quantize_state_dict(model.state_dict())
        self.assertEqual(quantized.accumulator_bias.shape, (1024,))
        self.assertEqual(quantized.psq_features.shape, (16_536, 1024))
        self.assertEqual(quantized.threat_features.shape, (45_547, 1024))
        self.assertEqual(quantized.psq_psqt.shape, (16_536, 16))
        self.assertEqual(quantized.threat_psqt.shape, (45_547, 16))
        self.assertEqual(len(quantized.stacks), 16)
        quantized.validate()


@unittest.skipUnless(HAVE_ZSTD and ENGINE.is_file(), "Pikafish export integration is unavailable")
class ExportReadbackTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        torch.manual_seed(123)
        cls.model = XiangqiNnue().eval()
        with torch.no_grad():
            cls.model.accumulator_bias.normal_(0, 0.01)
            for embedding in (
                cls.model.psq_features,
                cls.model.threat_features,
                cls.model.psq_psqt,
                cls.model.threat_psqt,
            ):
                embedding.weight.normal_(0, 0.004)
            for stack in cls.model.stacks:
                stack.hidden1.weight.normal_(0, 0.05)
                stack.hidden1.bias.normal_(0, 0.05)
                stack.hidden2.weight.normal_(0, 0.10)
                stack.hidden2.bias.normal_(0, 0.05)
                stack.output.weight.normal_(0, 0.10)
                stack.output.bias.normal_(0, 0.10)

    def test_written_network_loads_and_eval_matches_quantized_simulator(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            network = root / "candidate.nnue"
            report = write_nnue(network, self.model.state_dict(), description="export test")
            self.assertTrue(network.is_file())
            self.assertEqual(report["networkVersion"], hex(NETWORK_VERSION))
            self.assertEqual(report["networkHash"], hex(network_hash()))

            quantized = quantize_state_dict(self.model.state_dict())
            with PikafishFeatureClient(ENGINE) as features_client:
                features = features_client.fen(INITIAL_FEN)
            with PikafishEvalClient(ENGINE, network) as engine:
                engine_internal = engine.eval_fen(INITIAL_FEN)

            quantized_internal = simulate_quantized_forward(quantized, features)
            float_internal = float_forward_internal(self.model, features)
            self.assertEqual(engine_internal, quantized_internal)
            # Quantization error is intentionally allowed, but must stay
            # far below one centipawn-equivalent internal unit at this scale.
            self.assertLess(abs(float_internal - engine_internal), 25.0)


if __name__ == "__main__":
    unittest.main()
