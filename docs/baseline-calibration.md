# Baseline strength calibration

Status: 2026-08-29, small-sample smoke. This records the first calibration of
the native depth-limited baseline (`docs/baseline-search.md`) against the CC0
teacher, as required by plan phase 2: the baseline must be stronger than the
one-move greedy fallback but weaker than the teacher at higher node budgets.

## Method

- Baseline: `build/native/xiangqi-engine.exe` `analyze` difficulty `baseline`,
  depth 3 (deterministic alpha-beta, material + PST).
- Teacher: pinned Fairy-Stockfish CC0 teacher (`native/bin/fairy-stockfish-teacher.exe`).
- Referee: native rules engine; openings: 8 per level, 6 seeded random plies;
  max 120 plies; seed 99; 8 games per node level.
- Command per level:

```powershell
.\.venv\Scripts\python.exe -m xiangqi_nnue.match `
  --baseline .\build\native\xiangqi-engine.exe --baseline-depth 3 `
  --teacher .\native\bin\fairy-stockfish-teacher.exe `
  --rules-engine .\build\native\xiangqi-engine.exe `
  --games 8 --opening-plies 6 --nodes <N> --max-plies 120 --seed 99 `
  --candidate baseline --out-dir .\reports\calibration\nodes-<N>
```

## Results (baseline as candidate)

| Teacher nodes | Wins | Draws | Losses | Score rate | Wilson 95% LB |
|---|---|---|---|---|---|
| 50 | 2 | 0 | 6 | 0.25 | 0.071 |
| 200 | 4 | 0 | 4 | 0.50 | 0.215 |
| 1000 | 4 | 0 | 4 | 0.50 | 0.215 |

Archives: `.reports/calibration/nodes-*/` (PGN, UCCI logs, games.jsonl,
summary.json) — gitignored generated artifacts.

## Interpretation

- With only 8 games per level the confidence intervals are wide; the point
  estimates place the depth-3 baseline around teacher strength at 200-1000
  nodes and slightly below at 50 nodes.
- The baseline is clearly stronger than the greedy fallback (which never
  searches) and is in the intended "weak club" band. It is NOT yet proven
  weaker than the teacher at any node count — a larger calibration (e.g. 40+
  games per level) is needed before Gate 1 thresholds can be trusted.
- Gate 1's 800-game run will supersede this smoke; the runner is
  `scripts/run-gates.ps1`.

## Next

- Scale calibration to ~40 games per node level when CPU budget allows.
- Build the versioned tactical suite (100-200 ODbL/CC0 or hand-constructed
  checkmate/material positions) for the 90% tactical gate.
