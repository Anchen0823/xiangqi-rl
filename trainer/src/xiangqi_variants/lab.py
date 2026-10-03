from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import random
import subprocess
import time
from pathlib import Path

import numpy as np
import torch
from torch import nn

ROOT = Path(__file__).resolve().parents[3]
INPUT_SIZE = 90 * 68 + 128 + 16
ACTION_SIZE = 8190
FEATURE_VERSION = 'lab-features-v1'


class Referee:
    """One persistent Node process. Python never reimplements legal moves."""
    def __init__(self, engine=None):
        self.process = subprocess.Popen(
            ['node', str(engine or ROOT / 'build/variants/cli.mjs'), 'rpc'], cwd=ROOT,
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True, encoding='utf-8',
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0),
        )
        self.counter = 0

    def call(self, method, **params):
        self.counter += 1
        self.process.stdin.write(json.dumps({'id': self.counter, 'method': method, 'params': params}) + '\n')
        self.process.stdin.flush()
        line = self.process.stdout.readline()
        if not line:
            raise RuntimeError(f'Referee exited ({self.process.poll()})')
        response = json.loads(line)
        if not response.get('ok'):
            raise RuntimeError(response.get('error', 'referee failure'))
        if response.get('id') != self.counter:
            raise RuntimeError('Referee response id mismatch')
        return response['data']

    def close(self):
        if self.process.stdin:
            self.process.stdin.close()
        try:
            self.process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            self.process.terminate()
            self.process.wait(timeout=10)
        self.process.stdout.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()


class PolicyValue(nn.Module):
    def __init__(self):
        super().__init__()
        self.trunk = nn.Sequential(nn.Linear(INPUT_SIZE, 256), nn.ReLU(), nn.Linear(256, 128), nn.ReLU())
        self.policy = nn.Linear(128, ACTION_SIZE)
        self.value = nn.Linear(128, 1)

    def forward(self, observation):
        hidden = self.trunk(observation)
        return self.policy(hidden), torch.tanh(self.value(hidden)).squeeze(-1)


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def atomic_json(path, data):
    path = Path(path)
    temp = path.with_suffix(path.suffix + '.tmp')
    temp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    temp.replace(path)


def generate(ref, mode, out, games=8, nodes=32, seed=1000, scenario=None):
    out.mkdir(parents=True, exist_ok=True)
    info = ref.call('info', mode=mode, **({'scenario': scenario} if scenario else {}))
    manifest_path = out / 'manifest.json'
    manifest = {'schemaVersion': 1, 'mode': mode, 'rulesHash': info['rulesHash'],
                'codeHash': info['codeHash'], 'featureVersion': FEATURE_VERSION,
                'nodes': nodes, 'seed': seed, 'trainGames': games, 'validationGames': 2,
                'scenario': scenario, 'games': []}
    if manifest_path.exists():
        prior = json.loads(manifest_path.read_text(encoding='utf-8'))
        for field in ['schemaVersion', 'mode', 'rulesHash', 'codeHash', 'featureVersion', 'nodes', 'seed', 'trainGames', 'scenario']:
            if prior[field] != manifest[field]:
                raise ValueError(f'Dataset resume mismatch: {field}')
        manifest = prior
    presets = ['queen-left-3', 'queen-right-3', 'queen-left-2', 'queen-right-2', 'ending-2', 'ending-3']
    for split, count, start in [('train', games, seed), ('validation', 2, seed + 10000)]:
        for index in range(count):
            name = f'{split}-{index:03d}.json.gz'
            if any(x['file'] == name for x in manifest['games']):
                item = next(x for x in manifest['games'] if x['file'] == name)
                if sha(out / name) != item['sha256']:
                    raise ValueError('Dataset shard hash mismatch')
                continue
            game_seed = start + index
            started = time.monotonic()
            data = ref.call('selfplay', mode=mode, preset=presets[index % len(presets)], seed=game_seed,
                            agentSeed=game_seed + 1000000, nodes=nodes, rollout=4, maxPlies=1000,
                            **({'scenario': scenario} if scenario else {}))
            if data['status'] != 'complete':
                atomic_json(out / f'truncated-{split}-{index}.json', data)
                raise RuntimeError('Self-play was truncated: no terminal labels written; resume after investigation')
            # Referee snapshots are a separate research archive, never model input.
            atomic_json(out / f'{split}-{index:03d}.xqlab', data.pop('game'))
            with gzip.open(out / name, 'wt', encoding='utf-8') as stream:
                json.dump(data, stream, ensure_ascii=False)
            manifest['games'].append({'file': name, 'split': split, 'seed': game_seed,
                                      'plies': data['plies'], 'result': data['result'], 'sha256': sha(out / name)})
            atomic_json(manifest_path, manifest)
            print(f'{mode} {split} {index+1}/{count}: {data["plies"]} plies {data["result"]} {time.monotonic()-started:.1f}s', flush=True)
    return manifest


def rows_from_dataset(directory, split):
    manifest = json.loads((directory / 'manifest.json').read_text(encoding='utf-8'))
    rows = []
    seeds = {}
    for item in manifest['games']:
        if item['seed'] in seeds and seeds[item['seed']] != item['split']:
            raise ValueError('Game seed leaked across splits')
        seeds[item['seed']] = item['split']
        if item['split'] != split:
            continue
        if sha(directory / item['file']) != item['sha256']:
            raise ValueError('Dataset shard hash mismatch')
        with gzip.open(directory / item['file'], 'rt', encoding='utf-8') as stream:
            game = json.load(stream)
        if game['status'] != 'complete' or game['result']['kind'] == 'ongoing':
            raise ValueError('Truncated game cannot supply terminal labels')
        for row in game['rows']:
            row['z'] = (0.0 if game['result']['kind'] == 'draw' else
                        1.0 if game['result']['winner'] == row['seat'] else -1.0)
            rows.append(row)
    if not rows:
        raise ValueError(f'Empty {split} split')
    return rows


def batch(rows, indices, device):
    x = np.zeros((len(indices), INPUT_SIZE), dtype=np.float32)
    policy = np.zeros((len(indices), ACTION_SIZE), dtype=np.float32)
    mask = np.zeros_like(policy, dtype=bool)
    z = np.empty(len(indices), dtype=np.float32)
    for i, index in enumerate(indices):
        row = rows[int(index)]
        for k, v in row['x']:
            x[i, k] = v
        mask[i, row['legal']] = True
        for k, v in row['pi']:
            policy[i, k] = v
        if not np.isfinite(policy[i]).all() or abs(float(policy[i].sum()) - 1) > 1e-4:
            raise ValueError('Invalid policy target')
        if np.any(policy[i, ~mask[i]]):
            raise ValueError('Policy target includes illegal actions')
        z[i] = row['z']
    return tuple(torch.from_numpy(a).to(device) for a in (x, policy, mask, z))


def losses(model, data):
    x, target, mask, z = data
    logits, value = model(x)
    log_policy = torch.log_softmax(logits.masked_fill(~mask, -1e9), dim=1)
    policy_loss = -(target * log_policy).sum(1).mean()
    value_loss = (value - z).square().mean()
    return policy_loss + value_loss, policy_loss, value_loss


def train(dataset, out, steps=100, resume=False, device='auto', initial=None):
    if resume and initial:
        raise ValueError('Choose exact resume or warm start, not both')
    out.mkdir(parents=True, exist_ok=True)
    manifest = json.loads((dataset / 'manifest.json').read_text(encoding='utf-8'))
    manifest_hash = sha(dataset / 'manifest.json')
    device = ('cuda' if torch.cuda.is_available() else 'cpu') if device == 'auto' else device
    torch.set_num_threads(2)
    random.seed(173); np.random.seed(173); torch.manual_seed(173)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(173)
    model = PolicyValue().to(device)
    optimizer = torch.optim.AdamW(model.parameters(), lr=3e-4, weight_decay=1e-4)
    train_rows = rows_from_dataset(dataset, 'train')
    val_rows = rows_from_dataset(dataset, 'validation')
    checkpoint = out / 'candidate.pt'
    step = cursor = 0
    order = np.random.permutation(len(train_rows))
    logs = []
    initialization = None
    if initial:
        state = torch.load(initial, map_location=device, weights_only=False)
        if state.get('rulesHash') != manifest['rulesHash']:
            raise ValueError('Initial checkpoint rules mismatch')
        initial_features = state.get('featureVersion')
        if initial_features is None:
            # Legacy short-training checkpoints kept their feature contract in the sibling manifest.
            metadata_path = Path(initial).with_suffix('.json')
            if not metadata_path.exists():
                raise ValueError('Initial checkpoint has no feature compatibility manifest')
            metadata = json.loads(metadata_path.read_text(encoding='utf-8'))
            if (metadata.get('rulesHash') != manifest['rulesHash'] or
                    metadata.get('inputSize') != INPUT_SIZE or metadata.get('actionSize') != ACTION_SIZE):
                raise ValueError('Initial checkpoint manifest mismatch')
            initial_features = metadata.get('featureVersion')
        if initial_features != FEATURE_VERSION:
            raise ValueError('Initial checkpoint features mismatch')
        model.load_state_dict(state['model'], strict=True)
        initialization = {'path': str(Path(initial).resolve()), 'sha256': sha(initial), 'step': state['step']}
    if resume:
        state = torch.load(checkpoint, map_location=device, weights_only=False)
        if state['datasetHash'] != manifest_hash or state['rulesHash'] != manifest['rulesHash']:
            raise ValueError('Checkpoint/dataset/rules mismatch')
        model.load_state_dict(state['model']); optimizer.load_state_dict(state['optimizer'])
        step, cursor, order, logs = state['step'], state['cursor'], state['order'], state['logs']
        initialization = state.get('initialization')
        random.setstate(state['random']); np.random.set_state(state['numpy']); torch.set_rng_state(state['torch'].cpu())
        if device.startswith('cuda') and state.get('cuda'):
            torch.cuda.set_rng_state_all([x.cpu() for x in state['cuda']])
    start_step = step
    while step < steps:
        if cursor >= len(order):
            order = np.random.permutation(len(train_rows)); cursor = 0
        indices = order[cursor:cursor + 64]; cursor += len(indices)
        model.train(); optimizer.zero_grad(set_to_none=True)
        loss, lp, lv = losses(model, batch(train_rows, indices, device))
        if not torch.isfinite(loss):
            raise RuntimeError('Non-finite training loss')
        loss.backward(); nn.utils.clip_grad_norm_(model.parameters(), 1.0); optimizer.step(); step += 1
        if step % 25 == 0 or step == steps:
            model.eval()
            with torch.no_grad():
                validation = float(losses(model, batch(val_rows, np.arange(min(64, len(val_rows))), device))[0])
            row = {'step': step, 'loss': float(loss.detach()), 'policy': float(lp.detach()),
                   'value': float(lv.detach()), 'validationLoss': validation}
            logs.append(row); print(json.dumps(row), flush=True)
            state = {'schemaVersion': 1, 'model': model.state_dict(), 'optimizer': optimizer.state_dict(),
                     'step': step, 'cursor': cursor, 'order': order, 'logs': logs,
                     'random': random.getstate(), 'numpy': np.random.get_state(), 'torch': torch.get_rng_state(),
                     'cuda': torch.cuda.get_rng_state_all() if device.startswith('cuda') else None,
                     'datasetHash': manifest_hash, 'rulesHash': manifest['rulesHash'],
                     'featureVersion': FEATURE_VERSION, 'initialization': initialization}
            torch.save(state, checkpoint.with_suffix('.tmp')); checkpoint.with_suffix('.tmp').replace(checkpoint)
    atomic_json(out / 'training.json', {'schemaVersion': 1, 'mode': manifest['mode'], 'rulesHash': manifest['rulesHash'],
                                      'datasetHash': manifest_hash, 'startStep': start_step, 'step': step,
                                      'trainRows': len(train_rows), 'validationRows': len(val_rows), 'device': device,
                                      'logs': logs, 'initialization': initialization,
                                      'warning': '短训验证流水线，不代表棋力提升。'})
    return model.cpu().eval(), manifest


def export_model(model, manifest, dataset, out):
    import onnx
    import onnxruntime as ort
    rows = rows_from_dataset(dataset, 'validation')
    sample = batch(rows, np.arange(min(8, len(rows))), 'cpu')[0]
    path = out / 'candidate.onnx'
    torch.onnx.export(model, sample, str(path), input_names=['observation'], output_names=['policy', 'value'],
                      dynamic_axes={'observation': {0: 'batch'}, 'policy': {0: 'batch'}, 'value': {0: 'batch'}},
                      opset_version=17, dynamo=False)
    onnx.checker.check_model(str(path))
    session = ort.InferenceSession(str(path), providers=['CPUExecutionProvider'])
    with torch.no_grad():
        expected = [x.numpy() for x in model(sample)]
    actual = session.run(None, {'observation': sample.numpy()})
    errors = [float(np.max(np.abs(a-b))) for a,b in zip(actual, expected)]
    if max(errors) > 1e-4:
        raise RuntimeError(f'ONNX parity failed: {errors}')
    meta = {'schemaVersion': 1, 'rulesHash': manifest['rulesHash'], 'featureVersion': FEATURE_VERSION,
            'inputSize': INPUT_SIZE, 'actionSize': ACTION_SIZE, 'sha256': sha(path),
            'training': json.loads((out / 'training.json').read_text(encoding='utf-8'))}
    atomic_json(out / 'candidate.json', meta)
    atomic_json(out / 'parity.json', {'samples': len(sample), 'policyMaxAbs': errors[0], 'valueMaxAbs': errors[1], 'passed': True})
    return path, meta


def acceptance(ref, mode, out, info, model_path, meta, nodes=64, scenario=None):
    report_dir = out / 'evaluation'; report_dir.mkdir(parents=True, exist_ok=True)
    config = {'schemaVersion': 1, 'id': f'{mode}-short-training', 'pairs': 4, 'nodes': nodes,
              'rollout': 4, 'seed': 900000, 'maxPlies': 1000, 'purpose': 'candidate',
              'codeHash': info['codeHash'], 'modelHashes': [meta['sha256'], None]}
    records = []
    group_size = 4 if mode == 'banqi' else 2
    for group in range(4):
        for leg in range(group_size):
            file = report_dir / f'game-{group}-{leg}.json'
            if file.exists():
                record = json.loads(file.read_text(encoding='utf-8'))
            else:
                record = ref.call('match', mode=mode, seed=config['seed'] + group, config=config,
                                  group=group, leg=leg, model=str(model_path.resolve()),
                                  **({'scenario': scenario} if scenario else {}))
                atomic_json(file, record)
            records.append(record)
            summary = ref.call('report', out=str(report_dir.resolve()), records=records, config=config, groupSize=group_size)
            print(f'{mode} validation {group+1}/4 leg {leg+1}: {record["status"]} {record["result"]}', flush=True)
    if summary['completionRate'] != 1:
        raise RuntimeError('Acceptance matches did not all finish normally')
    return summary


def main():
    parser = argparse.ArgumentParser(description='象棋变体实验室：数据 → 训练 → 恢复 → 导出 → 候选对弈')
    parser.add_argument('command', choices=['smoke', 'generate', 'train', 'export'])
    parser.add_argument('--mode', choices=['custom', 'jieqi', 'banqi', 'all'], default='all')
    parser.add_argument('--out', type=Path, default=Path('runs/variants/short-training'))
    parser.add_argument('--nodes', type=int, default=32)
    parser.add_argument('--steps', type=int, default=100)
    parser.add_argument('--games', type=int, default=8)
    parser.add_argument('--resume', action='store_true')
    parser.add_argument('--device', default='auto')
    parser.add_argument('--scenario', type=Path, help='网页导出的自定义局面 JSON 或 .xqlab；按其规则独立训练')
    args = parser.parse_args()
    if args.nodes < 1 or args.games < 1 or args.steps < 1:
        parser.error('budgets must be positive')
    args.out = args.out.resolve()
    scenario = None
    if args.scenario:
        source = json.loads(args.scenario.read_text(encoding='utf-8'))
        scenario = source['scenario'] if source.get('format') == 'xqlab' else source
        if args.mode not in ['all', scenario['rules']['mode']]:
            parser.error('scenario mode differs from --mode')
        modes = [scenario['rules']['mode']]
    else:
        modes = ['custom', 'jieqi', 'banqi'] if args.mode == 'all' else [args.mode]
    for mode in modes:
        out = args.out / mode; dataset = out / 'dataset'; weights = out / 'model'
        with Referee() as ref:
            info = ref.call('info', mode=mode, **({'scenario': scenario} if scenario else {}))
            if args.command in ['smoke', 'generate']:
                generate(ref, mode, dataset, args.games, args.nodes, scenario=scenario)
            if args.command in ['smoke', 'train']:
                if args.command == 'smoke':
                    train(dataset, weights, max(1, args.steps // 2), False, args.device)
                    model, manifest = train(dataset, weights, args.steps, True, args.device)
                else:
                    model, manifest = train(dataset, weights, args.steps, args.resume, args.device)
            elif args.command == 'export':
                state = torch.load(weights / 'candidate.pt', map_location='cpu', weights_only=False)
                model = PolicyValue(); model.load_state_dict(state['model']); model.eval()
                manifest = json.loads((dataset / 'manifest.json').read_text(encoding='utf-8'))
            if args.command in ['smoke', 'train', 'export']:
                model_path, meta = export_model(model, manifest, dataset, weights)
            if args.command == 'smoke':
                summary = acceptance(ref, mode, out, info, model_path, meta, scenario=scenario)
                atomic_json(out / 'acceptance.json', {'passed': True, 'rulesHash': info['rulesHash'],
                                                    'trainGames': args.games, 'steps': args.steps,
                                                    'resumed': True, 'onnxSha256': meta['sha256'], 'evaluation': summary})
                print(f'{mode}: short-training acceptance passed (not a strength claim)', flush=True)


if __name__ == '__main__':
    main()
