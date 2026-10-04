"""Eight-hour Jieqi campaign, bounded rounds, fixed seed domains and durable resume."""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from types import SimpleNamespace

from .jieqi import run, run_lock
from .lab import atomic_json, sha


def round_seed(index):
    if not 0 <= index < 200:
        raise ValueError('Round seed domain exhausted')
    return (index + 1) * 10000000


def run_campaign(args, runner=run, clock=time.time):
    root = args.out.resolve(); root.mkdir(parents=True, exist_ok=True)
    file = root / 'night.json'
    settings = {key: getattr(args, key) for key in ['hours', 'round_minutes', 'nodes', 'steps', 'pairs', 'device']}
    seed_round_start = getattr(args, 'seed_round_start', 0)
    round_seed(seed_round_start)
    if seed_round_start:
        settings['seed_round_start'] = seed_round_start
    if file.exists():
        state = json.loads(file.read_text(encoding='utf-8'))
        if state['settings'] != settings:
            raise ValueError('Night resume configuration mismatch')
        if str(args.initial.resolve()) != state['initial']:
            raise ValueError('Night initial model configuration mismatch')
    else:
        initial = args.initial.resolve()
        for extension in ['pt', 'onnx', 'json']:
            if not (initial / f'candidate.{extension}').is_file():
                raise ValueError(f'Missing initial candidate.{extension}: {initial}')
        started = clock()
        state = {'schemaVersion': 1, 'settings': settings, 'startedAt': started,
                 'deadline': started + args.hours * 3600, 'phase': 'ready', 'rounds': [],
                 'initial': str(initial), 'initialHash': sha(initial / 'candidate.pt'),
                 'latestModel': str(initial), 'latestHash': sha(initial / 'candidate.pt')}
        atomic_json(file, state)
    if sha(Path(state['latestModel']) / 'candidate.pt') != state['latestHash']:
        raise ValueError('Night candidate changed since checkpoint')
    try:
        while clock() < state['deadline']:
            index = len(state['rounds'])
            out = root / f'round-{index:03d}'
            # Do not start a fresh round with too little time for terminal data and evaluation.
            reserve = min(600, args.round_minutes * 60 * .25)
            if not (out / 'run.json').exists() and state['deadline'] - clock() < reserve:
                break
            options = SimpleNamespace(out=out, initial=Path(state['latestModel']),
                minutes=args.round_minutes, nodes=args.nodes, steps=args.steps, pairs=args.pairs,
                device=args.device, seed_offset=round_seed(seed_round_start + index), deadline_override=state['deadline'])
            state.update(phase='running', currentRound=index, currentOutput=str(out))
            atomic_json(file, state)
            print(f'Jieqi round {index + 1}; remaining {(state["deadline"]-clock())/60:.1f} minutes', flush=True)
            with run_lock(out):
                runner(options)
            summary = json.loads((out / 'summary.json').read_text(encoding='utf-8'))
            if summary['phase'] != 'complete':
                # Continue this same numbered evaluation if total budget remains.
                if clock() >= state['deadline']:
                    break
                continue
            candidate = out / 'model'
            state['rounds'].append({'index': index, 'seedOffset': options.seed_offset,
                'directory': str(out), 'onnxSha256': summary['onnxSha256'],
                'trainGames': summary['trainGames'], 'evaluation': summary['evaluation']})
            state.update(latestModel=str(candidate), latestHash=sha(candidate / 'candidate.pt'))
            atomic_json(file, state)
        state['phase'] = 'budget-finished'
    except KeyboardInterrupt:
        state['phase'] = 'interrupted'
        raise
    except Exception as error:
        state.update(phase='failed', error=str(error))
        raise
    finally:
        state['updatedAt'] = clock()
        atomic_json(file, state)
    print(f'Campaign finished: {len(state["rounds"])} complete rounds; candidate {state["latestModel"]}', flush=True)
    return state


def main():
    parser = argparse.ArgumentParser(description='揭棋 8 小时训练；按轮自博弈、恢复、导出及独立评测')
    parser.add_argument('--out', type=Path, default=Path('runs/jieqi/night-8h'))
    parser.add_argument('--initial', type=Path, default=Path('runs/jieqi/pilot-20261003/model'))
    parser.add_argument('--hours', type=float, default=8)
    parser.add_argument('--round-minutes', type=float, default=60)
    parser.add_argument('--nodes', type=int, default=128)
    parser.add_argument('--steps', type=int, default=2000)
    parser.add_argument('--pairs', type=int, default=8)
    parser.add_argument('--device', choices=['cpu', 'cuda', 'auto'], default='cpu')
    parser.add_argument('--seed-round-start', type=int, default=0,
                        help='Global round offset; use a fresh range for a new campaign')
    args = parser.parse_args()
    if min(args.hours, args.round_minutes, args.nodes, args.steps, args.pairs) <= 0:
        parser.error('All budgets must be positive')
    with run_lock(args.out):
        run_campaign(args)


if __name__ == '__main__':
    main()
