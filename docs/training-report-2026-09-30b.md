# Expanded continuation: 2026-09-30 (second pass)

Continued from the 2026-09-30 candidate on a training set rebuilt from the full
`selfplay-v1` corpus. Validation-selected best improved on every holdout,
including the untouched 2026-09-30 holdouts that the previous run used. No
champion was promoted and the earlier artifacts are unchanged.

## Why the data was rebuilt

The previous run trained on `datasets/trial-split/train` (52,262 records from
400 games). `datasets/selfplay-v1` held 1,500 games and 212,403 positions that
had never been labeled, so the 2026-09-30 report's "expand labeled data beyond
the trial partition" step was the remaining blocker.

`selfplay-v1` self-play cached the teacher's 5,000-node score, bestmove and
node count on all but the opening position of each game, so labeling consumed
no new teacher search. `xiangqi_nnue.label` finished all 212,403 records in
215.6 seconds into `datasets/v1-labeled` (5 shards), against the pinned CC0
Fairy-Stockfish teacher whose SHA-256 still matches the manifest.

`selfplay-v1` and `selfplay-trial` were generated with the same seed and their
first 400 game files are byte-identical, so the trial partition is a strict
subset rather than independent data.

## Leakage control

Positions are keyed by the first two FEN fields (board and side to move), so
move counters cannot disguise a repeat. `scripts/prepare-expanded-split.py`
removes, from all 1,500 games:

- every position in the previous `trial-split/train` set, which the warm-start
  checkpoint was already fitted on;
- every position in `trial-continue-20260930` val and test, which stay
  untouched as a like-for-like regression holdout.

Surviving games are then split by whole game at 94/3/3 with seed 20260930, and
positions are deduplicated within and across partitions.

| Partition | Records | Games |
|---|---:|---:|
| train | 139,496 | 1,034 |
| val | 4,115 | 33 |
| holdout (fresh final) | 4,016 | 33 |

Old-holdout leakage into any partition: 0. Overlap with the old training
partition: 0. The train partition is 2.67x the previous 52,262 records.

## Configuration

`trainer/config/trial-expanded.toml`, batch 8,192, microbatch 256, learning rate
0.0004, 10 warmup steps, cosine decay, seed 20260930, validate every half
epoch, early-stop patience two epochs, pause at 83 C. 17 optimizer steps per
epoch. Weights were initialized from `checkpoints/continue-20260930/best.pt`
with `--init-checkpoint`, which resets the optimizer and dataset cursor because
the dataset is new; `--resume` would have been rejected on the manifest hash.

## Results

Training stopped early at step 170 of a 170-step schedule (epoch 9.5), two
epochs after the validation optimum at step 134. Validation Huber fell from
0.079724 at the warm start to 0.049264.

Evaluation on the holdouts, all of them unseen during training:

| Holdout | Model | Huber | MAE | Pearson |
|---|---|---:|---:|---:|
| 2026-09-30 val (2,783) | previous | 0.134024 | 0.393348 | 0.543966 |
| 2026-09-30 val (2,783) | expanded | 0.073929 | 0.286431 | 0.784503 |
| 2026-09-30 test (2,983) | previous | 0.120181 | 0.382436 | 0.602538 |
| 2026-09-30 test (2,983) | expanded | 0.076119 | 0.294715 | 0.772921 |
| fresh holdout (4,016) | previous | 0.106964 | 0.336301 | 0.639199 |
| fresh holdout (4,016) | expanded | 0.070819 | 0.272967 | 0.779822 |

Pearson correlation rose on all three, and the improvement holds on the
holdouts the previous run already used, so it is not an artifact of the new
partition. Parameters were checked for finite values.

The exported network loaded in pinned Pikafish. On 12 evenly spaced fresh
holdout positions, quantized Python evaluation exactly matched engine readback.
Maximum float-versus-engine internal error was 39.3133 on this sample. This
sample does not establish full-domain quantization parity.

## What this does and does not show

Evaluation error fell sharply, but this is still a single-distribution teacher
on self-play positions, and no play was measured in this run. It is not
evidence of passing the baseline, teacher, tactical or human strength gates,
and no promotion decision is implied.

## Artifacts (local, gitignored)

- `checkpoints/expanded-20260930/best.pt`, SHA-256
  `30004886f23f28790471249194da70abec4cbe95f775e796cd89b04abc79e9b1`.
- `checkpoints/expanded-20260930/latest.pt`.
- `checkpoints/expanded-20260930/candidate.nnue` (34,337,870 bytes), SHA-256
  `60f554c24244f8e63645303b2d1f7b9bea3899b33f353a71018687e5a2145624`.
- `reports/training-20260930b/`: data preflight, training log, metrics,
  evaluation JSON, evaluation script.

## Reproduction

From repository root, with the teacher binary and `datasets/selfplay-v1`
present:

```powershell
.\.venv\Scripts\python.exe -u -m xiangqi_nnue.label `
  --source datasets\selfplay-v1 --source-url "local:selfplay-v1-20260829" `
  --attribution "Xiangqi RL self-play v1" `
  --dataset datasets\v1-labeled --dataset-id selfplay-v1-cc0 `
  --feature-engine .\native\bin\pikafish.exe `
  --teacher-engine .\native\bin\fairy-stockfish-teacher.exe `
  --teacher-manifest .\third_party\fairy-stockfish-teacher.json `
  --nodes 5000 --threads 1 --hash-mb 128

.\.venv\Scripts\python.exe -u scripts\prepare-expanded-split.py

$env:OMP_NUM_THREADS = '4'
$env:MKL_NUM_THREADS = '4'
.\.venv\Scripts\python.exe -u -m xiangqi_nnue.train `
  --config trainer\config\trial-expanded.toml `
  --dataset datasets\v1-split-20260930\train `
  --val-dataset datasets\v1-split-20260930\val `
  --init-checkpoint checkpoints\continue-20260930\best.pt `
  --checkpoint checkpoints\expanded-20260930\latest.pt `
  --best-checkpoint checkpoints\expanded-20260930\best.pt `
  --metrics reports\training-20260930b\metrics.jsonl

.\.venv\Scripts\python.exe -u reports\training-20260930b\evaluate.py
```

Labeling and splitting are resumable and deterministic. Use separate output
paths for a new experiment to preserve these results.

## Next

Generate a fresh self-play corpus and hold out its games before any further
promotion attempt, run a play match against the 2026-09-30 candidate, then work
through the full strength protocol. Teacher-score cache coverage should also be
verified for any new corpus, since it is what makes labeling cheap.
