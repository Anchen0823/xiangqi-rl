from __future__ import annotations
import gzip
import json
import tempfile
import unittest
from pathlib import Path
import numpy as np
import torch
from xiangqi_variants.lab import ACTION_SIZE, INPUT_SIZE, PolicyValue, batch, losses, rows_from_dataset, sha


class VariantTrainingTests(unittest.TestCase):
    def test_policy_mask_and_gradients(self):
        rows = [{'x': [[0, 1]], 'legal': [2, 7], 'pi': [[2, .75], [7, .25]], 'z': 1}]
        tensors = batch(rows, [0], 'cpu')
        model = PolicyValue()
        loss, _, _ = losses(model, tensors)
        loss.backward()
        self.assertTrue(torch.isfinite(loss))
        self.assertTrue(all(p.grad is None or torch.isfinite(p.grad).all() for p in model.parameters()))
        self.assertEqual(model(tensors[0])[0].shape, (1, ACTION_SIZE))
        self.assertEqual(tensors[0].shape, (1, INPUT_SIZE))

    def test_illegal_policy_targets_rejected(self):
        rows = [{'x': [], 'legal': [2], 'pi': [[7, 1.0]], 'z': 0}]
        with self.assertRaisesRegex(ValueError, 'illegal'):
            batch(rows, [0], 'cpu')

    def test_truncation_cannot_supply_draw_labels(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            path = directory / 'game.json.gz'
            with gzip.open(path, 'wt', encoding='utf-8') as stream:
                json.dump({'status': 'truncated', 'result': {'kind': 'ongoing'}, 'rows': []}, stream)
            (directory / 'manifest.json').write_text(json.dumps({'games': [{'file': path.name, 'split': 'train', 'seed': 1, 'sha256': sha(path)}]}), encoding='utf-8')
            with self.assertRaisesRegex(ValueError, 'Truncated'):
                rows_from_dataset(directory, 'train')

    def test_terminal_value_is_relative_to_acting_player(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary); path = directory / 'game.json.gz'
            with gzip.open(path, 'wt', encoding='utf-8') as stream:
                json.dump({'status': 'complete', 'result': {'kind': 'win', 'winner': 1}, 'rows': [{'seat': 0}, {'seat': 1}]}, stream)
            (directory / 'manifest.json').write_text(json.dumps({'games': [{'file': path.name, 'split': 'train', 'seed': 1, 'sha256': sha(path)}]}), encoding='utf-8')
            self.assertEqual([r['z'] for r in rows_from_dataset(directory, 'train')], [-1, 1])


if __name__ == '__main__':
    unittest.main()
