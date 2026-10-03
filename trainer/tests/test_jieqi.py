from __future__ import annotations

import gzip
import json
import tempfile
import unittest
from pathlib import Path

import torch

from xiangqi_variants.jieqi import seed_for, run_lock, evaluate
from xiangqi_variants.lab import PolicyValue, FEATURE_VERSION, sha, train


class JieqiPilotTests(unittest.TestCase):
    def test_output_lock_rejects_concurrent_writer_and_releases(self):
        with tempfile.TemporaryDirectory() as tmp:
            with run_lock(Path(tmp)):
                with self.assertRaisesRegex(RuntimeError, 'already has a running'):
                    with run_lock(Path(tmp)):
                        pass
            with run_lock(Path(tmp)):
                pass

    def test_expired_budget_keeps_both_comparisons_missing(self):
        class ReportsOnly:
            def call(self, method, **params):
                if method != 'report':
                    raise AssertionError('Expired budget started a game')
                return {'completionRate': 0, 'scheduledGames': params['config']['pairs'] * 2,
                        'records': len(params['records'])}
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); previous = root / 'previous.onnx'; previous.write_bytes(b'old')
            result = evaluate(ReportsOnly(), root, {'codeHash': 'code'}, root / 'candidate.onnx',
                              {'sha256': 'new'}, previous, 4, 64, deadline=0)
            self.assertEqual(set(result), {'baseline', 'previous'})
            self.assertTrue(all(x['records'] == 0 and x['scheduledGames'] == 8 for x in result.values()))

    def dataset(self, root):
        dataset = root / 'dataset'; dataset.mkdir()
        games = []
        for split, seed in [('train', 1), ('validation', 2)]:
            file = dataset / f'{split}.json.gz'
            with gzip.open(file, 'wt', encoding='utf-8') as stream:
                json.dump({'status': 'complete', 'result': {'kind': 'win', 'winner': 0},
                           'rows': [{'x': [[0, 1]], 'legal': [2, 7], 'pi': [[2, .75], [7, .25]], 'seat': 0},
                                    {'x': [[1, 1]], 'legal': [3, 9], 'pi': [[3, .5], [9, .5]], 'seat': 1}]}, stream)
            games.append({'split': split, 'seed': seed, 'file': file.name, 'sha256': sha(file)})
        (dataset / 'manifest.json').write_text(json.dumps({'mode': 'jieqi', 'rulesHash': 'jieqi-test', 'games': games}))
        return dataset

    def test_seed_domains_disjoint(self):
        domains = [set(seed_for(split, i) for i in range(10000))
                   for split in ['train', 'validation', 'baseline', 'previous']]
        self.assertEqual(len(set.union(*domains)), 40000)
        with self.assertRaises(ValueError):
            seed_for('train', 10000)

    def test_warm_start_resume_is_exact_and_keeps_origin(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); dataset = self.dataset(root)
            initial = root / 'old.pt'
            torch.save({'rulesHash': 'jieqi-test', 'featureVersion': FEATURE_VERSION,
                        'step': 100, 'model': PolicyValue().state_dict()}, initial)
            full, _ = train(dataset, root / 'full', 6, device='cpu', initial=initial)
            train(dataset, root / 'resumed', 3, device='cpu', initial=initial)
            restored, _ = train(dataset, root / 'resumed', 6, resume=True, device='cpu')
            for name, tensor in full.state_dict().items():
                self.assertTrue(torch.equal(tensor, restored.state_dict()[name]), name)
            meta = json.loads((root / 'resumed/training.json').read_text(encoding='utf-8'))
            self.assertEqual(meta['startStep'], 3)
            self.assertEqual(meta['initialization']['sha256'], sha(initial))
            self.assertEqual(meta['initialization']['step'], 100)

    def test_wrong_rules_or_features_cannot_initialize(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); dataset = self.dataset(root); initial = root / 'wrong.pt'
            torch.save({'rulesHash': 'standard-nnue'}, initial)
            with self.assertRaisesRegex(ValueError, 'rules mismatch'):
                train(dataset, root / 'model', 1, device='cpu', initial=initial)
            torch.save({'rulesHash': 'jieqi-test', 'featureVersion': 'future'}, initial)
            with self.assertRaisesRegex(ValueError, 'features mismatch'):
                train(dataset, root / 'model', 1, device='cpu', initial=initial)
            torch.save({'rulesHash': 'jieqi-test'}, initial)
            with self.assertRaisesRegex(ValueError, 'no feature compatibility'):
                train(dataset, root / 'model', 1, device='cpu', initial=initial)
            with self.assertRaisesRegex(ValueError, 'not both'):
                train(dataset, root / 'model', 1, resume=True, initial=initial)


if __name__ == '__main__':
    unittest.main()
