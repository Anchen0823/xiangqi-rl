"""Frozen final night candidate versus baseline and the pre-night model; resumable."""
import argparse
import json
import shutil
import time
from pathlib import Path

from xiangqi_variants.jieqi import evaluate, run_lock
from xiangqi_variants.lab import Referee, atomic_json, sha, FEATURE_VERSION


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--campaign', type=Path, default=Path('runs/jieqi/night-8h'))
    parser.add_argument('--out', type=Path, default=Path('runs/jieqi/night-review-20261004'))
    parser.add_argument('--pairs', type=int, default=32)
    parser.add_argument('--nodes', type=int, default=128)
    parser.add_argument('--minutes', type=float, default=60)
    parser.add_argument('--seed-offset', type=int, default=3000000000)
    args = parser.parse_args()
    if min(args.pairs, args.nodes, args.minutes) <= 0 or args.pairs > 10000:
        parser.error('Invalid budget')
    if not 0 <= args.seed_offset <= 4294957295 - 6000000:
        parser.error('Seed range must fit uint32')
    campaign = json.loads((args.campaign / 'night.json').read_text(encoding='utf-8'))
    model = Path(campaign['latestModel']).resolve()
    previous = (args.campaign / 'round-000/previous').resolve()
    engine = model.parent / 'engine.mjs'
    settings = dict(model=str(model), previous=str(previous), modelHash=sha(model/'candidate.onnx'),
                    previousHash=sha(previous/'candidate.onnx'), engineHash=sha(engine),
                    pairs=args.pairs, nodes=args.nodes, seedOffset=args.seed_offset)
    # Reserve a completely new seed domain, even for campaigns with many rounds.
    for folder in args.campaign.glob('round-*/dataset'):
        manifest = json.loads((folder/'manifest.json').read_text(encoding='utf-8'))
        occupied = {g['seed'] for g in manifest['games']}
        for base in (5000000, 6000000):
            if occupied.intersection(range(args.seed_offset+base, args.seed_offset+base+args.pairs)):
                raise ValueError('Evaluation seeds overlap training data')
    for item in campaign['rounds']:
        for result in item['evaluation'].values():
            start = result['config']['seed']
            stop = start + result['config']['pairs']
            for base in (5000000, 6000000):
                new_start = args.seed_offset + base
                if max(start, new_start) < min(stop, new_start + args.pairs):
                    raise ValueError('Evaluation seeds overlap historical evaluation')
    with run_lock(args.out):
        config = args.out/'review.json'
        if config.exists():
            if json.loads(config.read_text(encoding='utf-8')) != settings:
                raise ValueError('Resume configuration mismatch')
        else:
            atomic_json(config, settings)
            shutil.copy2(engine, args.out/'engine.mjs')
        if sha(args.out/'engine.mjs') != settings['engineHash']:
            raise ValueError('Frozen referee changed')
        with Referee(args.out/'engine.mjs') as ref:
            info = ref.call('info', mode='jieqi')
            for folder in (model, previous):
                meta = json.loads((folder/'candidate.json').read_text(encoding='utf-8'))
                if meta['rulesHash'] != info['rulesHash'] or meta['featureVersion'] != FEATURE_VERSION or meta['sha256'] != sha(folder/'candidate.onnx'):
                    raise ValueError('Incompatible or changed model')
            meta = json.loads((model/'candidate.json').read_text(encoding='utf-8'))
            results = evaluate(ref, args.out, info, model/'candidate.onnx', meta,
                               previous/'candidate.onnx', args.pairs, args.nodes,
                               time.time()+args.minutes*60, args.seed_offset)
            atomic_json(args.out/'summary.json', results)
            print(json.dumps(results, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
