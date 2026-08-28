# Dataset quality inspection

Status: 2026-08-29, implementation-level. This implements plan priority #6
from `docs/amateur-strength-plan.md`: a data-quality statistics script used by
the phase-3 quality gate before scaling up labeled data.

## What changed

- New module: `trainer/src/xiangqi_nnue/inspect.py`
  - `inspect_dataset` streams records from a labeled dataset and reports:
    - record count vs the manifest total;
    - `score_cp` distribution (min/max/mean/stddev and p5/p25/p50/p75/p95);
    - outcome distribution (none / red / black / draw);
    - duplicate-FEN records and ratio, unique FEN count;
    - teacher-node distribution;
    - optional bestmove legality spot-check against the native rules referee
      (`--legality-sample N --rules-engine ...`), listing every illegal sample.
  - CLI: `xiangqi-inspect` console script.
- New script: `scripts/inspect-dataset.ps1` — PowerShell wrapper that resolves
  the venv and repo paths and forwards to the module.
- New test suite: `trainer/tests/test_inspect.py` (4 tests).

## First real-dataset finding (fixed)

Running the inspector on `datasets/selfplay-v1-calibration-2w-labeled`
(2,975 records) with a 20-move legality sample surfaced a real bug:

- score distribution looks reasonable (median 2 cp, p5/p95 around +/-1000 cp);
- 22 duplicate-FEN records (ratio 0.7%);
- 4 of 20 sampled bestmoves were **not UCCI-legal** — e.g. `h10f9` — because
  the live-teacher labeling path persisted Fairy-Stockfish's native coordinate
  system (ranks 1..10) instead of UCCI ranks 0..9 in `TrainingRecord.bestmove`.

Fix: `FairyStockfishTeacher.evaluate_fen` now converts every returned bestmove
via the canonical `fairy_move_to_ucci` (moved from `selfplay.py` into
`teacher.py`), so direct labeling and self-play both persist UCCI moves.
Training consumes features + scores, not moves, so this never corrupted
training — but the quality gate now holds on fresh labels.

## Usage

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/inspect-dataset.ps1 `
  -Dataset datasets\selfplay-v1-calibration-2w-labeled -LegalitySample 100
```

## Validation boundary

- 66 trainer tests pass (62 before + 4 new).
- Real-dataset run above completed; the legality spot-check correctly flagged
  the coordinate mismatch.
- Not yet done: wiring the rank flip into the labeler, and running the full
  quality gate on 3M+ positions before S1 training.
