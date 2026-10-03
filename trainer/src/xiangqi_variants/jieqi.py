"""Bounded Jieqi pilot; observations only, terminal labels, independent paired evaluation."""
from __future__ import annotations

import argparse
import gzip
import json
import shutil
import time
import os
from html import escape
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

import numpy as np
import torch

from .lab import (ROOT, FEATURE_VERSION, Referee, atomic_json, sha, train, export_model,
                  rows_from_dataset, batch, losses)


@contextmanager
def run_lock(root):
    """OS lock survives stale files but is released on process exit."""
    root.mkdir(parents=True, exist_ok=True)
    with (root / 'run.lock').open('a+b') as stream:
        stream.seek(0, 2)
        if stream.tell() == 0:
            stream.write(b'0'); stream.flush()
        stream.seek(0)
        try:
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as error:
            raise RuntimeError('This output directory already has a running pilot') from error
        try:
            yield
        finally:
            stream.seek(0)
            if os.name == 'nt':
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream, fcntl.LOCK_UN)


def seed_for(split, index):
    starts = {'train': 3000000, 'validation': 3100000, 'baseline': 5000000, 'previous': 6000000}
    if not 0 <= index < 10000:
        raise ValueError('Seed index out of range')
    return starts[split] + index


def write_pilot_report(root, summary):
    def pct(value):
        return '暂无' if value is None else f'{value * 100:.1f}%'
    rows = []
    audit_note = ''
    audit_file = root / 'audit.json'
    if audit_file.exists():
        audit = json.loads(audit_file.read_text(encoding='utf-8'))
        old = audit['heldoutComparison']['previous']['loss']
        new = audit['heldoutComparison']['candidate']['loss']
        audit_note = (f'<h2>数据与模型审计</h2><p>回放 {audit["dataGames"]} 个数据局、'
                      f'{audit["dataRows"]} 条样本及 {audit["evaluationGames"]} 个评测局；'
                      f'检查 {audit["evaluationMoves"]} 步搜索预算，复现 {audit["reproducedDecisions"]} 次决策。</p>'
                      f'<p>完整验证集总损失：旧模型 {old:.4f}，新候选 {new:.4f}（越低越好）。'
                      '对局点估计与验证损失应分别看待，不能仅据短训宣布棋力提升。</p>'
                      '<p><a href="audit.json">完整审计 JSON</a></p>')
    for name, title in [('baseline', '基础搜索'), ('previous', '上一轮揭棋候选')]:
        result = summary['evaluation'][name]
        interval = ' / '.join(map(pct, result['score95'])) if result['score95'] else '未完成全部配对'
        rows.append(f'<tr><td><a href="evaluation/{name}/report.html">{title}</a></td>'
                    f'<td>{result["games"]}/{result["scheduledGames"]}</td>'
                    f'<td>{result["wins"]} / {result["draws"]} / {result["losses"]}</td>'
                    f'<td>{pct(result["winRate"])}</td><td>{pct(result["scoreRate"])}</td><td>{interval}</td></tr>')
    page = f'''<!doctype html><html lang="zh-CN"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>揭棋试训报告</title>
<style>body{{font:16px system-ui;max-width:1000px;margin:32px auto;padding:20px;background:#faf8f0;color:#203d36}}table{{border-collapse:collapse;width:100%}}td,th{{padding:12px;border-bottom:1px solid #ccd4ca;text-align:left}}aside{{background:#fff0cf;padding:16px}}pre{{white-space:pre-wrap;overflow-wrap:anywhere}}.table{{overflow-x:auto}}a{{color:#21654c}}</style>
<h1>揭棋独立权重试训</h1><p>{escape(root.name)} · 实际执行 {summary['elapsedSeconds']/60:.1f} 分钟 · 预算 {summary['budgetMinutes']:g} 分钟</p>
<p>完整训练局 {summary['trainGames']}；独立验证局 {summary['validationGames']}；排除截断局 {summary['excludedGames']}；优化更新 {summary['steps']} 次。</p>
<aside>{escape(summary['warning'])} 下表以候选视角统计，95% 区间以完整配对组为单位。</aside>
<div class="table"><table><tr><th>对手与详细报告</th><th>完成局</th><th>胜 / 和 / 负</th><th>纯胜率</th><th>得分率</th><th>95% 得分区间</th></tr>{''.join(rows)}</table></div>
<p><a href="model/candidate.json">模型清单</a> · <a href="model/candidate.onnx">ONNX 权重</a> · <a href="model/heldout.json">完整验证集指标</a> · <a href="model/parity.json">ONNX 一致性</a> · <a href="summary.json">JSON 总结</a></p>
<p>在揭棋模式加载同目录的 candidate.json 与 candidate.onnx。普通象棋继续使用自己的 NNUE 权重。</p>
{audit_note}
<details><summary>完整实验结果</summary><pre>{escape(json.dumps(summary, ensure_ascii=False, indent=2))}</pre></details></html>'''
    (root / 'report.html').write_text(page, encoding='utf-8')


def evaluate(ref, root, info, model, meta, previous, pairs, nodes, deadline, seed_offset=0):
    results = {}
    for name, opponent in [('baseline', None), ('previous', previous)]:
        out = root / 'evaluation' / name
        out.mkdir(parents=True, exist_ok=True)
        config = {'schemaVersion': 1, 'id': f'jieqi-{root.name}-{name}', 'pairs': pairs,
                  'nodes': nodes, 'rollout': 4, 'seed': seed_for(name, 0) + seed_offset, 'maxPlies': 1000,
                  'purpose': 'candidate', 'codeHash': info['codeHash'],
                  'modelHashes': [meta['sha256'], sha(opponent) if opponent else None]}
        records = []
        for group in range(pairs):
            for leg in range(2):
                file = out / f'game-{group}-{leg}.json'
                if file.exists():
                    records.append(json.loads(file.read_text(encoding='utf-8')))
        # Validate all persisted records before resuming any work.
        ref.call('report', out=str(out), records=records, config=config, groupSize=2)
        results[name] = (out, config, records, opponent)
    # Alternate opponents so a time limit does not exclude one comparison entirely.
    for group in range(pairs):
        for name, (out, config, records, opponent) in results.items():
            for leg in range(2):
                if any(r['group'] == group and r['leg'] == leg for r in records):
                    continue
                if time.time() >= deadline:
                    continue
                params = {'opponent': str(opponent)} if opponent else {}
                record = ref.call('match', mode='jieqi', seed=seed_for(name, group) + seed_offset, config=config,
                                  group=group, leg=leg, model=str(model), **params)
                atomic_json(out / f'game-{group}-{leg}.json', record)
                records.append(record)
                summary = ref.call('report', out=str(out), records=records, config=config, groupSize=2)
                atomic_json(root / 'status.json', {'phase': 'evaluation', 'comparison': name,
                            'group': group + 1, 'leg': leg + 1, 'summary': summary})
                print(f'Evaluation {name} {group+1}/{pairs} leg {leg+1}: {record["status"]} {record["result"]}', flush=True)
    return {name: ref.call('report', out=str(out), records=records, config=config, groupSize=2)
            for name, (out, config, records, _) in results.items()}


def run(args):
    seed_offset = getattr(args, 'seed_offset', 0)
    root = args.out.resolve(); root.mkdir(parents=True, exist_ok=True)
    engine = root / 'engine.mjs'
    previous = root / 'previous'
    config_path = root / 'run.json'
    if not config_path.exists():
        previous.mkdir(exist_ok=True)
        for suffix in ['pt', 'onnx', 'json']:
            shutil.copy2(args.initial / f'candidate.{suffix}', previous / f'candidate.{suffix}')
        shutil.copy2(ROOT / 'build/variants/cli.mjs', engine)
        source = root / 'source'; source.mkdir(exist_ok=True)
        for name in ['jieqi.py', 'lab.py']:
            shutil.copy2(Path(__file__).parent / name, source / name)
        config = {'schemaVersion': 1, 'mode': 'jieqi', 'minutes': args.minutes, 'nodes': args.nodes,
                  'steps': args.steps, 'pairs': args.pairs, 'device': args.device,
                  'initialHash': sha(previous / 'candidate.pt'), 'initialOnnxHash': sha(previous / 'candidate.onnx'),
                  'engineHash': sha(engine), 'startedAt': time.time(), 'dataFrozen': False,
                  'featureVersion': FEATURE_VERSION, 'seedOffset': seed_offset}
        config['trainingCodeHashes'] = {name: sha(source / name) for name in ['jieqi.py', 'lab.py']}
        atomic_json(config_path, config)
    else:
        config = json.loads(config_path.read_text(encoding='utf-8'))
        if config.get('seedOffset', 0) != seed_offset:
            raise ValueError('Pilot resume mismatch: seedOffset')
        for key in ['minutes', 'nodes', 'steps', 'pairs', 'device']:
            if config[key] != getattr(args, key):
                raise ValueError(f'Pilot resume mismatch: {key}')
        if sha(engine) != config['engineHash'] or sha(previous / 'candidate.pt') != config['initialHash'] or sha(previous / 'candidate.onnx') != config['initialOnnxHash']:
            raise ValueError('Pilot artifact hash mismatch')
        for name, digest in config.get('trainingCodeHashes', {}).items():
            if sha(Path(__file__).parent / name) != digest:
                raise ValueError('Training source changed; use a new run directory')
        completed = root / 'summary.json'
        if completed.exists():
            saved_summary = json.loads(completed.read_text(encoding='utf-8'))
            if saved_summary['phase'] == 'complete':
                if sha(root / 'model/candidate.onnx') != saved_summary['onnxSha256']:
                    raise ValueError('Completed candidate hash mismatch')
                print('Pilot already complete; retained original training and evaluation records.', flush=True)
                return
    # Resume grants another explicit invocation's budget, retaining all seeds and frozen data.
    started = time.time(); deadline = min(started + args.minutes * 60, getattr(args, 'deadline_override', float('inf')))
    data_deadline = started + max(0, deadline-started) * .60
    dataset = root / 'dataset'; dataset.mkdir(exist_ok=True)
    weights = root / 'model'
    with Referee(engine) as ref:
        info = ref.call('info', mode='jieqi')
        previous_meta = json.loads((previous / 'candidate.json').read_text(encoding='utf-8'))
        if previous_meta['rulesHash'] != info['rulesHash'] or previous_meta['featureVersion'] != FEATURE_VERSION:
            raise ValueError('Previous model incompatible with Jieqi rules/features')
        manifest_path = dataset / 'manifest.json'
        manifest = json.loads(manifest_path.read_text(encoding='utf-8')) if manifest_path.exists() else {
            'schemaVersion': 1, 'mode': 'jieqi', 'rulesHash': info['rulesHash'], 'codeHash': info['codeHash'],
            'featureVersion': FEATURE_VERSION, 'nodes': args.nodes, 'rollout': 4,
            'modelHash': config['initialOnnxHash'], 'games': [], 'attempts': []}
        if manifest['rulesHash'] != info['rulesHash'] or manifest['codeHash'] != info['codeHash']:
            raise ValueError('Dataset referee mismatch')
        for item in manifest['games']:
            if sha(dataset / item['file']) != item['sha256']:
                raise ValueError('Dataset shard hash mismatch')
        if not config['dataFrozen']:
            # Validation seeds are reserved before the time-bounded training stream.
            for split, count in [('validation', 4), ('train', 512)]:
                for index in range(count):
                    if any(x['split'] == split and x['index'] == index for x in manifest['attempts']):
                        continue
                    if split == 'train' and time.time() >= data_deadline:
                        break
                    stamp = time.monotonic()
                    game_seed = seed_for(split, index) + seed_offset
                    data = ref.call('selfplay', mode='jieqi', seed=game_seed, agentSeed=game_seed + 1000000,
                                    nodes=args.nodes, rollout=4, maxPlies=1000,
                                    model=str(previous / 'candidate.onnx'))
                    name = f'{split}-{index:03d}'
                    atomic_json(dataset / f'{name}.xqlab', data.pop('game'))
                    manifest['attempts'].append({'split': split, 'index': index, 'seed': game_seed,
                                                'status': data['status'], 'plies': data['plies']})
                    if data['status'] == 'complete':
                        file = dataset / f'{name}.json.gz'
                        with gzip.open(file, 'wt', encoding='utf-8') as stream:
                            json.dump(data, stream)
                        manifest['games'].append({'split': split, 'file': file.name, 'seed': game_seed,
                                                  'plies': data['plies'], 'result': data['result'], 'sha256': sha(file)})
                    else:
                        atomic_json(dataset / f'{name}-excluded.json', {'status': data['status'], 'result': data['result']})
                    atomic_json(manifest_path, manifest)
                    counts = {s: sum(g['split'] == s for g in manifest['games']) for s in ['train', 'validation']}
                    atomic_json(root / 'status.json', {'phase': 'selfplay', 'completeGames': counts,
                                'lastGameSeconds': time.monotonic()-stamp, 'elapsedSeconds': time.time()-started})
                    print(f'{split} {index}: {data["status"]}, {data["plies"]} plies, {time.monotonic()-stamp:.1f}s', flush=True)
            if sum(g['split'] == 'train' for g in manifest['games']) < 8 or sum(g['split'] == 'validation' for g in manifest['games']) < 2:
                raise RuntimeError('Too few complete games; retained data, no candidate trained')
            config['dataFrozen'] = True
            atomic_json(config_path, config)
        atomic_json(root / 'status.json', {'phase': 'training', 'steps': args.steps})
        checkpoint = weights / 'candidate.pt'
        if not checkpoint.exists():
            train(dataset, weights, max(1, args.steps // 2), device=args.device, initial=previous / 'candidate.pt')
        model, manifest = train(dataset, weights, args.steps, resume=True, device=args.device)
        model_path, meta = export_model(model, manifest, dataset, weights)
        # Inspect every held-out row, not just the trainer's small progress batch.
        rows = rows_from_dataset(dataset, 'validation'); totals = np.zeros(3)
        with torch.no_grad():
            for offset in range(0, len(rows), 64):
                indices = np.arange(offset, min(offset+64, len(rows)))
                totals += np.array([float(x) for x in losses(model, batch(rows, indices, 'cpu'))]) * len(indices)
        atomic_json(weights / 'heldout.json', {'rows': len(rows), 'loss': totals[0]/len(rows),
                    'policyLoss': totals[1]/len(rows), 'valueMSE': totals[2]/len(rows)})
        evaluations = evaluate(ref, root, info, model_path, meta, previous / 'candidate.onnx',
                               args.pairs, args.nodes, deadline, seed_offset)
        summary = {'phase': 'complete' if all(x['completionRate'] == 1 for x in evaluations.values()) else 'partial-evaluation',
                   'elapsedSeconds': time.time()-started, 'budgetMinutes': args.minutes,
                   'trainGames': sum(g['split'] == 'train' for g in manifest['games']),
                   'validationGames': sum(g['split'] == 'validation' for g in manifest['games']),
                   'excludedGames': sum(x['status'] != 'complete' for x in manifest['attempts']),
                   'steps': args.steps, 'onnxSha256': meta['sha256'], 'evaluation': evaluations,
                   'warning': '揭棋短训实验，未证明棋力提升；候选未自动晋级。时间上限在整局边界检查。'}
        atomic_json(root / 'summary.json', summary); atomic_json(root / 'status.json', summary)
        write_pilot_report(root, summary)
        print(json.dumps(summary, ensure_ascii=False), flush=True)


def main():
    parser = argparse.ArgumentParser(description='揭棋独立权重：限时数据生成、续训、恢复、ONNX 与配对评测')
    parser.add_argument('--out', type=Path, default=Path('runs/jieqi') / datetime.now().strftime('pilot-%Y%m%d-%H%M%S'))
    parser.add_argument('--initial', type=Path, default=Path('runs/variants/acceptance-20261002/jieqi/model'))
    parser.add_argument('--minutes', type=float, default=30)
    parser.add_argument('--nodes', type=int, default=64)
    parser.add_argument('--steps', type=int, default=1000)
    parser.add_argument('--pairs', type=int, default=8)
    parser.add_argument('--device', choices=['cpu', 'cuda', 'auto'], default='cpu')
    parser.add_argument('--seed-offset', type=int, default=0)
    args = parser.parse_args()
    if min(args.minutes, args.nodes, args.steps, args.pairs) <= 0:
        parser.error('All budgets must be positive')
    if not 0 <= args.seed_offset <= 4000000000:
        parser.error('Seed offset out of range')
    with run_lock(args.out):
        try:
            run(args)
        except Exception as error:
            atomic_json(args.out / 'status.json', {'phase': 'failed', 'error': str(error)})
            raise


if __name__ == '__main__':
    main()
