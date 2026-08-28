# Training configuration and validation metrics

Status: 2026-08-28, implementation-level. This closes plan gap #5 from
`docs/amateur-strength-plan.md`: `train.toml` is now actually read by
`train.py`, training evaluates on a held-out validation split, records
train/val metrics, and stops early on validation plateau.

## What changed

- New module: `trainer/src/xiangqi_nnue/config.py`
  - `TrainingConfig.from_toml` loads `trainer/config/train.toml` as the single
    source of truth: model dimensions, seed, batch sizes, learning rate, weight
    decay, warmup steps, checkpoint cadence, temperature gates, memory limits,
    max epochs, validation interval and early-stop patience.
  - `cosine_warmup_lr`: linear warmup then cosine decay to zero.
- `train.py` now:
  - loads the config (`--config`, defaults to `trainer/config/train.toml`);
  - uses config seed / LR / weight decay / micro-batch / accumulate / shuffle
    buffer / temperature gates / memory soft limit / checkpoint cadence;
  - applies the warmup+cosine LR schedule each step;
  - evaluates Huber, MAE and Pearson correlation on `--val-dataset` every
    `val_interval_epochs`, writing train/val metrics to `--metrics`
    (`metrics.jsonl`) and printing learning curves;
  - keeps the best validation checkpoint at `--best-checkpoint` (never the
    test split) and stops early after `early_stop_patience_epochs` without
    improvement.
- `train.toml` gained `warmup_steps`, `max_epochs`, `val_interval_epochs` and
  `early_stop_patience_epochs`.
- New test suite: `trainer/tests/test_config.py` (11 tests) covering config
  validation, the LR schedule, the metric accumulator, and record evaluation.

## Validation boundary

- 62 trainer tests pass (51 before this change + 11 new).
- Verified locally end-to-end with synthetic train/val splits: metrics.jsonl
  shows decreasing val Huber with per-step LR, best checkpoint is written, and
  epoch-based early stopping is wired.
- The 90/5/5 game-boundary splitter that produces `--val-dataset` remains a
  data-production (Phase 3) task; until then validation runs on whatever
  directory the operator provides.
