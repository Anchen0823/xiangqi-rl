"""Compare legal actions to the existing native authority, not its different repetition policy."""
from __future__ import annotations
import argparse
import json
import random
from pathlib import Path
from xiangqi_variants.lab import Referee, atomic_json
from xiangqi_nnue.rules import NativeRulesClient


def fen(o):
    board = {p['square']: p['kind'].upper() if p['color'] == 'red' else p['kind'] for p in o['pieces']}
    rows = []
    for y in range(9, -1, -1):
        row, empty = '', 0
        for x in range(9):
            item = board.get(y*9+x)
            if item is None:
                empty += 1
            else:
                if empty:
                    row += str(empty); empty = 0
                row += item
        if empty:
            row += str(empty)
        rows.append(row)
    return '/'.join(rows) + (' w' if o['seats'][o['turn']] == 'red' else ' b') + ' - - 0 1'


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--positions', type=int, default=2000)
    parser.add_argument('--out', type=Path, default=Path('reports/variants/native-differential.json'))
    args = parser.parse_args()
    rng = random.Random(18273)
    checked = 0
    with Referee() as ref, NativeRulesClient('build/native/xiangqi-engine.exe') as native:
        while checked < args.positions:
            observation = ref.call('new', mode='custom', preset='standard')
            for _ in range(120):
                if observation['result']['kind'] != 'ongoing':
                    break
                current = fen(observation)
                authority = native.load_fen(current)
                ours = ref.call('legal')
                if sorted(ours) != sorted(authority['legalMoves']):
                    raise AssertionError(json.dumps({'fen': current, 'nativeOnly': sorted(set(authority['legalMoves'])-set(ours)), 'labOnly': sorted(set(ours)-set(authority['legalMoves']))}))
                checked += 1
                if checked >= args.positions:
                    break
                if not observation['legalActions']:
                    break
                observation = ref.call('step', action=rng.choice(observation['legalActions']))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    atomic_json(args.out, {'passed': True, 'positions': checked, 'seed': 18273,
                         'scope': 'ordinary Xiangqi legal actions, reset repetition counters per position',
                         'boundary': 'Existing native CCA repetition completeness is not certified by this check.'})
    print(f'Passed: {checked} legal-move positions match native referee')


if __name__ == '__main__':
    main()
