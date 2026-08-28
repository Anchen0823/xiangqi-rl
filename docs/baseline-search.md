# Native depth-limited baseline search

Status: 2026-08-29, implementation-level. This implements plan priority #3 from
`docs/amateur-strength-plan.md`: a reproducible, non-tunable club baseline that
is stronger than the one-move greedy fallback but weaker than the CC0 teacher,
ready to be calibrated and used as Gate 1's opponent.

## What changed

- New module: `native/include/xiangqi/baseline.hpp` + `native/src/baseline.cpp`
  - Deterministic depth-limited negamax with alpha-beta.
  - Fixed material values mirroring `Position::pieceValue` plus hard-coded
    piece-square tables (king, advisor, elephant, horse, rook, cannon, pawn).
  - Fixed move ordering (captures by victim value, then PST delta) so results
    are fully reproducible; no runtime tuning knobs.
  - Both checkmate and stalemate (困毙) score as a loss for the side to move,
    and faster mates are preferred (mate score minus ply).
- `Position::pieceAt` public accessor added for the evaluator.
- `xiangqi-engine.exe` `analyze` now accepts `difficulty = "baseline"` with an
  optional numeric `depth` (default 3; 4+ is too slow without a TT):
  `{"id":..., "method":"analyze", "difficulty":"baseline", "depth":3}`.
- `trainer/src/xiangqi_nnue/match.py` gains `NativeEnginePlayer`, a JSON-protocol
  player exposing the same interface as `UciEngine` (`name`, `new_game`,
  `search`, `close`), and the CLI now accepts `--baseline <engine path>`
  (plus `--baseline-depth`) so candidate-vs-baseline matches run with the same
  referee, openings, archives and statistics as UCI matches.
- Native tests: `baselineSearch` is deterministic, returns a legal move on the
  initial position, and prefers a free cannon capture at depth 3.
- Trainer tests: `NativeEnginePlayer` returns the engine's move via the fake
  JSON-protocol engine.

## Usage

```powershell
.\.venv\Scripts\python.exe -m xiangqi_nnue.match `
  --engine .\native\bin\pikafish.exe --eval-file .\checkpoints\candidate-101.nnue `
  --baseline .\build\native\xiangqi-engine.exe --baseline-depth 3 `
  --rules-engine .\build\native\xiangqi-engine.exe `
  --games 800 --opening-plies 8 --nodes 5000 --seed 20260828 `
  --candidate pikafish --out-dir .\reports\gate1-candidate
```

## Measured timing (RTX 4060 laptop, single thread)

| Position | depth 2 | depth 3 | depth 4 |
|---|---|---|---|
| initial FEN | 0.7 s | 2.5 s | > 30 s |

Depth 3 is the practical default; Gate 1 uses it. The next step per the plan is
calibrating this baseline against the teacher at 50/200/1000 nodes to confirm it
sits between the greedy fallback and the teacher before running the full 800-game
Gate 1.

## Validation boundary

- All native rule tests pass (including baseline determinism and capture tests).
- 63 trainer tests pass.
- Local candidate-vs-baseline smoke: pikafish with `candidate-101.nnue` beat the
  depth-3 baseline 2-0 with legal-move and archive verification.
- Not yet done: teacher calibration, Gate 1/2 runs, a transposition table to
  make deeper baseline search practical, and tactical suite integration.
