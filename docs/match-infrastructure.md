# Match infrastructure (UCI engine matches with a rules referee)

Status: 2026-08-28, infrastructure-level. This implements the second priority
item from `docs/amateur-strength-plan.md`: a reproducible match harness that
will later run Gate 1 (candidate vs baseline) and Gate 2 (candidate vs strong
CC0 teacher) under `docs/strength-protocol.md`.

## Scope

- New module: `trainer/src/xiangqi_nnue/match.py`
  - `UciEngine`: long-lived UCI engine adapter with `position fen`, `go nodes`,
    `bestmove`/`info` parsing, explicit timeouts and crash detection, and
    `ucinewgame` between games for deterministic transposition-table state.
  - `generate_openings`: deterministic legal openings from a fixed seed, played
    and validated by the native rules referee; each opening archives both the
    FEN and the UCCI move sequence.
  - `play_game`: referee-driven game loop. The `NativeRulesClient` referee
    validates every move and adjudicates checkmate/stalemate, natural limit and
    repetition; engine timeouts, crashes, missing moves and illegal moves
    forfeit the mover.
  - Wilson 95% two-sided lower bound on score rate (`wilson_lower_bound`),
    `summarize_records`, PGN and raw UCCI log writers, and a `run_match`
    orchestrator with color reversal.
  - CLI: `python -m xiangqi_nnue.match` (console script `xiangqi-match`).
- `NativeRulesClient.load_fen` added so the referee can start from opening FENs.
- New test suite: `trainer/tests/test_match.py` (14 tests).

## Determinism

Search determinism comes from `Threads 1`, a fixed hash size, fixed `go nodes`
limits and `ucinewgame` before every game. The plan's exit criterion — same
engine, fixed seed, two games, byte-identical results — is pinned by
`test_same_engine_fixed_seed_two_games_byte_identical`, which runs the match
twice with fresh Pikafish processes and requires identical `games.jsonl` lines.
The test auto-skips on CI when the pinned Pikafish binary or a candidate `.nnue`
is absent; fake-engine tests cover parsing and the game loop everywhere.

## Usage

```powershell
.\.venv\Scripts\python.exe -m xiangqi_nnue.match `
  --engine .\native\bin\pikafish.exe --engine .\native\bin\pikafish.exe `
  --eval-file .\checkpoints\candidate-101.nnue `
  --rules-engine .\build\native\xiangqi-engine.exe `
  --games 2 --opening-plies 4 --nodes 2000 --max-plies 120 `
  --seed 42 --out-dir .\reports\smoke-match
```

Archives per game: `game-NNNN.pgn` (UCCI-move PGN), `game-NNNN.ucci.log` (raw
UCI traffic), plus `games.jsonl` and `summary.json` (Wilson lower bound).

## Match correctness update (2026-09-30)

- Consecutive games now use the same opening with reversed engine colors.
  Previously colors alternated but each game used a different opening. Use an
  even game count for a fully paired match; an odd count leaves one unpaired game.
- A terminal referee result after the final allowed ply takes precedence over
  the move-cap draw. Custom opening generation also loads the requested initial
  FEN before generating any moves.
- Candidate summaries require exactly one identifiable candidate per game and
  reject unfinished results. The CLI assigns `-1` / `-2` suffixes when player
  names coincide (including same-binary matches), and defaults the candidate to
  the first player. Explicit `--candidate` values must match the resolved names.
- Engine cleanup is managed by `ExitStack`, including a failure while starting
  the second player. Invalid match budgets and candidate names fail before launch.
- The existing `sprt_llr` calculation now uses log-space arithmetic to avoid
  underflow in large samples. Its formula remains a fractional-score
  approximation, identified by `sprt_method` in the summary; it is not a
  normalized trinomial or paired-game SPRT and cannot alone certify promotion.

Regression checks: `python -m unittest discover -s trainer/tests -p 'test_match*.py' -v`.
Historical match reports have not been rewritten; new evaluations should rerun
with the corrected opening schedule and terminal-result handling.

Local verification on 2026-09-30: all 87 trainer tests passed, including 27 match
tests and the real Pikafish determinism check. A separate two-game native
baseline CLI smoke (depth 1, seed 42, opening 4 plies, cap 8 plies) produced
matching opening FENs and reversed player identities in
`reports/match-correctness-20260930/games.jsonl` (gitignored). This short capped
run verifies infrastructure only, not playing strength. The full suite exposed
an unclosed source-file warning in `split.py`; after adding a context manager,
both split tests passed again with ResourceWarning reporting enabled and no
resource warnings.

## Validation boundary

- 51 trainer tests pass (including 14 new match tests); local real-engine
  determinism run passes.
- Not yet done: calibrated club baseline engine, Gate 1 / Gate 2 / tactical
  suite runs, concurrent games, resume, and SPRT — those remain in the plan.
