"""Audit saved games, exact budgets, seeded search, interruption and optimizer resume."""
import argparse
import hashlib
import json
import subprocess
from pathlib import Path

from xiangqi_variants.lab import ROOT, Referee, train


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--reports', type=Path, default=Path('reports/variants/queen-final-20261002'))
    parser.add_argument('--training', type=Path, default=Path('runs/variants/acceptance-20261002'))
    parser.add_argument('--out', type=Path, default=Path('reports/variants/artifact-audit'))
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    evidence = {'replayedGames': 0, 'budgetedMoves': 0, 'searchReproductions': 0, 'trainingModes': {}}
    with Referee() as ref:
        for folder in sorted(p for p in args.reports.iterdir() if p.is_dir()):
            config = json.loads((folder / 'config.json').read_text(encoding='utf-8'))
            if digest(folder / 'engine.mjs') != config['codeHash']:
                raise AssertionError('Archived executable hash mismatch')
            files = sorted(folder.glob('game-*.json'))
            assert len(files) == config['pairs'] * 2, (folder, len(files))
            for file in files:
                r = json.loads(file.read_text(encoding='utf-8'))
                assert r['status'] == 'complete', file
                assert all(s['nodes'] == config['nodes'] for s in r['searches']), file
                assert len(r['actions']) == len(r['searches']) == len(r['searchSeeds']), file
                o = ref.call('load', data=dict(schemaVersion=1, format='xqlab', rulesHash=r['rulesHash'], scenario=r['scenario'], actions=r['actions'], practice=False))
                assert o['result'] == r['result'] and o['keys'][-1] == r['finalKey'], file
                evidence['replayedGames'] += 1
                evidence['budgetedMoves'] += len(r['actions'])
                if r['group'] == 0 and r['leg'] == 0:
                    ref.call('new', scenario=r['scenario'])
                    s = ref.call('analyze', nodes=config['nodes'], rollout=config['rollout'], seed=r['searchSeeds'][0])
                    assert s['action'] == r['actions'][0], file
                    evidence['searchReproductions'] += 1
            print(f'replayed {folder.name}', flush=True)
        # A process stop after a durably stored numbered game must reuse that game.
        out = args.out / 'interruption'
        cmd = ['node', 'build/variants/cli.mjs', 'batch', '--mode', 'custom', '--pairs', '2', '--nodes', '128', '--max-plies', '4', '--out', str(out)]
        process = subprocess.Popen(cmd, cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding='utf-8', creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        first = process.stdout.readline()
        assert first, process.stderr.read()
        saved = out / 'game-0000-0.json'
        before = digest(saved)
        process.terminate(); process.wait(timeout=10)
        subprocess.run(cmd, cwd=ROOT, check=True, capture_output=True)
        assert before == digest(saved)
        evidence['interruptedBatchRestoredWithoutReplacingSavedGame'] = True
        source = args.out / 'scenario.json'
        scenario = ref.call('info', mode='custom')['scenario']
        source.write_text(json.dumps(scenario), encoding='utf-8')
        custom_cmd = ['node', 'build/variants/cli.mjs', 'batch', '--mode', 'custom', '--scenario', str(source), '--pairs', '1', '--nodes', '8', '--max-plies', '2', '--out', str(args.out / 'scenario-binding')]
        subprocess.run(custom_cmd, cwd=ROOT, check=True, capture_output=True)
        next(p for p in scenario['pieces'] if p['kind'] == 'q')['square'] = 9
        source.write_text(json.dumps(scenario), encoding='utf-8')
        rejected = subprocess.run(custom_cmd, cwd=ROOT, capture_output=True)
        assert rejected.returncode != 0
        evidence['changedInitialScenarioRefusedOnResume'] = True
    for mode in ['custom', 'jieqi', 'banqi']:
        folder = args.training / mode
        acceptance = json.loads((folder / 'acceptance.json').read_text(encoding='utf-8'))
        manifest = json.loads((folder / 'dataset/manifest.json').read_text(encoding='utf-8'))
        parity = json.loads((folder / 'model/parity.json').read_text(encoding='utf-8'))
        training = json.loads((folder / 'model/training.json').read_text(encoding='utf-8'))
        assert acceptance['passed'] and training['startStep'] == 50 and training['step'] >= 100
        assert len(manifest['games']) >= 10 and all(x['result']['kind'] != 'ongoing' for x in manifest['games'])
        assert parity['passed'] and max(parity['policyMaxAbs'], parity['valueMaxAbs']) <= 1e-4
        evidence['trainingModes'][mode] = {'games':len(manifest['games']), 'updates':training['step'], 'evaluationGames':acceptance['evaluation']['games'], 'onnxSha256':digest(folder/'model/candidate.onnx'), 'parity':parity}
    # Compare the actual 50+50 smoke checkpoint against uninterrupted 100 updates.
    import torch
    continuous, _ = train(args.training / 'custom/dataset', args.out / 'continuous-model', steps=100, device='cpu')
    resumed = torch.load(args.training / 'custom/model/candidate.pt', map_location='cpu', weights_only=False)
    difference = max(float((v-resumed['model'][k]).abs().max()) for k,v in continuous.state_dict().items())
    assert difference == 0, difference
    evidence['optimizerResumeMaxParameterDifference'] = difference
    (args.out / 'verification.json').write_text(json.dumps(evidence, indent=2), encoding='utf-8')
    print(json.dumps(evidence, indent=2))


if __name__ == '__main__':
    main()
