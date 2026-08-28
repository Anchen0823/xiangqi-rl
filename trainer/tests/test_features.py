import json
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

import torch

from xiangqi_nnue.features import (
    FeatureProtocolError,
    PerspectiveFeatures,
    PikafishFeatureClient,
    PositionFeatures,
    collate_model_inputs,
    parse_training_features,
)


def payload(psq=None, threats=None):
    psq = [1, 2] if psq is None else psq
    threats = [3] if threats is None else threats
    return {
        "layerBucket": 4,
        "perspectives": [
            {
                "color": "red",
                "featureBucket": 7,
                "attackBucket": 3,
                "mirror": False,
                "psq": psq,
                "threats": threats,
            },
            {
                "color": "black",
                "featureBucket": 6,
                "attackBucket": 2,
                "mirror": True,
                "psq": [5],
                "threats": [7, 8],
            },
        ],
    }


class FeatureTests(unittest.TestCase):
    def test_parse_and_validate_response(self):
        result = parse_training_features(json.dumps(payload()))
        self.assertEqual(result.layer_bucket, 4)
        self.assertEqual(result.side_to_move.color, "red")
        self.assertEqual(result.side_to_move.psq, (1, 2))
        self.assertEqual(result.opponent.threats, (7, 8))

    def test_out_of_range_index_is_rejected(self):
        with self.assertRaisesRegex(FeatureProtocolError, "out-of-range"):
            parse_training_features(json.dumps(payload(psq=[16_536])))

    def test_duplicate_perspective_color_is_rejected(self):
        invalid = payload()
        invalid["perspectives"][1]["color"] = "red"
        with self.assertRaisesRegex(FeatureProtocolError, "different"):
            parse_training_features(json.dumps(invalid))

    def test_collate_variable_sparse_bags(self):
        first = parse_training_features(json.dumps(payload()))
        second = PositionFeatures(
            layer_bucket=2,
            perspectives=(
                PerspectiveFeatures("black", 0, 0, False, (9,), (10, 11)),
                PerspectiveFeatures("red", 0, 0, False, (12, 13), ()),
            ),
        )
        inputs = collate_model_inputs([first, second])
        self.assertEqual(len(inputs), 9)
        torch.testing.assert_close(inputs[0], torch.tensor([1, 2, 9]))
        torch.testing.assert_close(inputs[1], torch.tensor([0, 2, 3]))
        torch.testing.assert_close(inputs[7], torch.tensor([0, 2, 2]))
        torch.testing.assert_close(inputs[8], torch.tensor([4, 2]))

    def test_client_ignores_banner_and_reads_jsonl(self):
        source = textwrap.dedent(
            f"""
            import json
            import sys
            current = "red"
            data = {payload()!r}
            print("Pikafish fake banner", flush=True)
            for line in sys.stdin:
                line = line.strip()
                if line.startswith("position fen"):
                    current = "black" if " b " in line else "red"
                elif line == "training_features":
                    data["perspectives"][0]["color"] = current
                    data["perspectives"][1]["color"] = "red" if current == "black" else "black"
                    print(json.dumps(data, separators=(",", ":")), flush=True)
                elif line == "quit":
                    break
            """
        )
        with tempfile.TemporaryDirectory() as directory:
            script = Path(directory) / "fake_engine.py"
            script.write_text(source, encoding="utf-8")
            with PikafishFeatureClient([sys.executable, "-u", script], timeout=2) as client:
                self.assertEqual(client.start_position().side_to_move.color, "red")
                black = client.fen("9/9/9/9/9/9/9/9/9/9 b - - 0 1")
                self.assertEqual(black.side_to_move.color, "black")

    def test_fen_command_injection_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "newline"):
            # Validation occurs before a process request; construct no client here.
            PikafishFeatureClient.fen(None, "startpos\nquit")  # type: ignore[arg-type]


if __name__ == "__main__":
    unittest.main()
