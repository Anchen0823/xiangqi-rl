# Self-play trial and labeling quality gate

Status: 2026-08-29, trial complete. This records the first end-to-end run of
the plan phase-3 data-production pipeline: deterministic self-play source
generation, CC0 teacher labeling, and the quality gate.

## Trial

- Source: `datasets/selfplay-trial` (gitignored) — 400 games, 58,826 positions.
- Command: `xiangqi_nnue.selfplay` with 12 workers, `--nodes 5000`,
  `--max-plies 240`, `--random-plies 8`, seed `20260829`.
- Termination mix: checkmates, `mutual_repetition` and `max_plies` draws —
  every game ended under the referee's rules with **zero illegal moves** (the
  UCCI-coordinate fix from PR #24 is confirmed end-to-end).
- Outcome distribution: red 242 / black 52 / draw 106 games (red's first-move
  advantage, high repetition-draw rate).

## Labeling

- Output: `datasets/trial-labeled` (gitignored) — 58,826 records, 3 shards of
  20k, resumable manifest with SHA-256 per shard.
- Command: `xiangqi_nnue.label` with `--nodes 5000 --threads 8 --hash-mb 128`.

## Quality gate (`scripts/inspect-dataset.ps1`)

| Metric | Value |
|---|---|
| Records inspected | 58,826 (matches manifest) |
| Bestmove legality sample | 100/100 legal |
| Duplicate-FEN ratio | 1.36% (798 records) |
| Unique FENs | 58,028 |
| Score cp median / p5 / p95 | 1 / -1040 / +1078 |
| Outcome split (red/draw/black) | 18,318 / 22,348 / 18,160 |
| Teacher nodes (median) | 5,002 |

The legality sample is the key regression check: before the Fairy→UCCI fix
(PR #22/#24) the same check found 4/20 illegal moves; it is now 100/100.

## Next

- Scale: generate several million positions (12 workers, ~24h) then label at
  5k nodes / 8 threads to reach the 3-8M target; split 90/5/5 by game
  boundaries with cross-split FEN dedup before S1 training.
- The 58k trial set is large enough to smoke-test S1 training end-to-end
  (config-driven, val metrics, early stop) before committing GPU hours.
