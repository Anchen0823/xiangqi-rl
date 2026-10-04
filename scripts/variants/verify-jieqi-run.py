"""Replay complete pilot games, inspect every policy target, and audit evaluation budgets."""
import argparse
import gzip
import json
from collections import Counter
from pathlib import Path

import numpy as np
import torch

from xiangqi_variants.lab import Referee, PolicyValue, atomic_json, sha, batch, rows_from_dataset, losses
from xiangqi_variants.jieqi import seed_for, write_pilot_report


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('run', type=Path)
    parser.add_argument('--data-only', action='store_true')
    args = parser.parse_args(); root = args.run.resolve()
    dataset = root / 'dataset'
    manifest = json.loads((dataset / 'manifest.json').read_text(encoding='utf-8'))
    config = json.loads((root / 'run.json').read_text(encoding='utf-8'))
    assert sha(root / 'engine.mjs') == config['engineHash'] == manifest['codeHash']
    evidence = {'dataGames': 0, 'dataRows': 0, 'dataResults': {}, 'evaluationGames': 0,
                'evaluationMoves': 0, 'candidateInferences': 0, 'opponentInferences': 0,
                'reproducedDecisions': 0, 'rulesHash': manifest['rulesHash']}
    seeds = set(); results = Counter()
    with Referee(root / 'engine.mjs') as ref:
        for item in manifest['games']:
            file = dataset / item['file']
            assert sha(file) == item['sha256']
            assert item['seed'] not in seeds
            seeds.add(item['seed'])
            with gzip.open(file, 'rt', encoding='utf-8') as stream:
                data = json.load(stream)
            assert data['status'] == 'complete' and data['result']['kind'] != 'ongoing'
            assert data['seed'] == item['seed'] and data['rulesHash'] == manifest['rulesHash']
            assert len(data['rows']) == data['plies'] == item['plies']
            assert data['nodes'] == data['plies'] * manifest['nodes']
            replay = json.loads((dataset / item['file'].replace('.json.gz', '.xqlab')).read_text(encoding='utf-8'))
            observation = ref.call('load', data=replay)
            assert observation['result'] == data['result']
            for row in data['rows']:
                row['z'] = 0 if data['result']['kind'] == 'draw' else (1 if row['seat'] == data['result']['winner'] else -1)
            for start in range(0, len(data['rows']), 64):
                tensors = batch(data['rows'], range(start, min(start + 64, len(data['rows']))), 'cpu')
                assert all(torch.isfinite(tensor).all() for tensor in tensors)
            evidence['dataGames'] += 1; evidence['dataRows'] += data['plies']
            results[data['result']['reason']] += 1
        evidence['dataResults'] = dict(results)
        if not args.data_only:
            for name in ['baseline', 'previous']:
                out = root / 'evaluation' / name
                summary = json.loads((out / 'summary.json').read_text(encoding='utf-8'))
                records = []
                for file in sorted(out.glob('game-*.json')):
                    record = json.loads(file.read_text(encoding='utf-8')); records.append(record)
                    expected_seed = seed_for(name, record['group']) + config.get('seedOffset', 0)
                    assert expected_seed not in seeds
                    assert summary['config']['seed'] + record['group'] == expected_seed
                    assert all(s['nodes'] == config['nodes'] for s in record['searches'])
                    assert len(record['actions']) == len(record['searches']) == len(record['searchSeeds'])
                    for index, search in enumerate(record['searches']):
                        candidate_turn = (record['scenario']['turn'] + index) % 2 == record['candidateSeat']
                        if candidate_turn:
                            assert search['inferences'] > 0
                            evidence['candidateInferences'] += search['inferences']
                        else:
                            assert (search['inferences'] > 0) == (name == 'previous')
                            evidence['opponentInferences'] += search['inferences']
                    if record['status'] == 'complete':
                        observation = ref.call('load', data={'schemaVersion': 1, 'format': 'xqlab',
                            'rulesHash': record['rulesHash'], 'scenario': record['scenario'],
                            'actions': record['actions'], 'practice': False})
                        assert observation['result'] == record['result'] and observation['keys'][-1] == record['finalKey']
                    evidence['evaluationGames'] += 1; evidence['evaluationMoves'] += len(record['actions'])
                    if record['group'] == 0 and record['actions']:
                        ref.call('new', scenario=record['scenario'])
                        model = root / 'model/candidate.onnx' if record['scenario']['turn'] == record['candidateSeat'] else (
                            root / 'previous/candidate.onnx' if name == 'previous' else None)
                        found = ref.call('analyze', nodes=config['nodes'], rollout=4, seed=record['searchSeeds'][0],
                                         **({'model': str(model)} if model else {}))
                        assert found['action'] == record['actions'][0]
                        evidence['reproducedDecisions'] += 1
                rebuilt = ref.call('report', out=str(out), config=summary['config'], records=records, groupSize=2)
                assert rebuilt == summary
            heldout = rows_from_dataset(dataset, 'validation')
            scores = {}
            for name, folder in [('previous', 'previous'), ('candidate', 'model')]:
                state = torch.load(root / folder / 'candidate.pt', map_location='cpu', weights_only=False)
                model = PolicyValue(); model.load_state_dict(state['model']); model.eval()
                totals = np.zeros(3)
                with torch.no_grad():
                    for start in range(0, len(heldout), 64):
                        indices = range(start, min(start + 64, len(heldout)))
                        totals += np.array([float(x) for x in losses(model, batch(heldout, indices, 'cpu'))]) * len(indices)
                scores[name] = {'loss': totals[0]/len(heldout), 'policyLoss': totals[1]/len(heldout), 'valueMSE': totals[2]/len(heldout)}
            evidence['heldoutComparison'] = scores
            parity = json.loads((root / 'model/parity.json').read_text(encoding='utf-8'))
            assert parity['passed'] and max(parity['policyMaxAbs'], parity['valueMaxAbs']) <= 1e-4
            evidence['parity'] = parity
    evidence['passed'] = True
    atomic_json(root / ('data-audit.json' if args.data_only else 'audit.json'), evidence)
    if not args.data_only:
        write_pilot_report(root, json.loads((root / 'summary.json').read_text(encoding='utf-8')))
    print(json.dumps(evidence, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    torch.set_num_threads(2)
    main()
