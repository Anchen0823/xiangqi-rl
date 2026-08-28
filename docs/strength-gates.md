# Strength gates and artifact verification

Status: 2026-08-29, infrastructure-level. This adds the reproducibility and
gate-running tooling from `docs/amateur-strength-plan.md` phases 0 and 2:
`scripts/verify-artifacts.ps1` and `scripts/run-gates.ps1`, plus the
Fairy-Stockfish teacher adapter needed for Gate 2.

## verify-artifacts.ps1

Verifies the pinned reproducibility anchors:

- teacher binary SHA-256 against `third_party/fairy-stockfish-teacher.json`
  (and that the network license is CC0-1.0);
- Pikafish checkout HEAD equals `third_party/pikafish.rev` and the training
  patch is applied;
- optional `-VerifyData`: every dataset shard SHA-256 against its manifest;
- optional `-VerifyCheckpoints`: records checkpoint SHA-256 hashes.

Writes `reports/verify-artifacts.json`; exits non-zero on any mismatch.
Gate runs refuse to start if this fails.

## Teacher adapter (Gate 2)

Fairy-Stockfish speaks UCI but numbers Xiangqi ranks 1..10 from red's back rank
while the native referee uses UCCI ranks 0..9. `UciEngine` now supports
`variant="xiangqi"` (sets `UCI_Variant`) and `coordinate_flip=True`, which
maps each returned `bestmove` rank down by one (`h10g8` -> `h9g7`). The CLI
accepts `--teacher <path>` for this adapter, so candidate-vs-teacher matches
run through the same referee/openings/archives as every other match.

## run-gates.ps1

One command for the strength-protocol gates:

1. Runs `verify-artifacts.ps1`; refuses to continue on failure.
2. Gate 1: candidate (`--CandidateEngine`/`--CandidateEvalFile`) vs the native
   depth-limited baseline (`--BaselineEngine`, `--BaselineDepth`), 800 games
   default, requires the two-sided 95% Wilson lower bound > 0.60.
3. Gate 2: candidate vs the CC0 teacher (`--TeacherEngine`) at equal nodes,
   400 games default, requires the lower bound >= 0.20.
4. Tactical suite: reported as pending until the versioned suite exists.

Each gate archives PGNs, UCCI logs, `games.jsonl`, `summary.json` under the
`--OutDir` gate folder, plus a combined `gate-audit.json` with engine SHA-256,
hardware, command line and per-gate statistics. Any enabled gate failing
throws, so release automation can rely on exit codes.

## Validation boundary

- 53 trainer tests pass; native rule tests pass.
- Local smoke: Gate 1 (pikafish + candidate-101 vs depth-3 baseline) passes the
  harness; Gate 2 (candidate vs teacher, 2000 nodes) completes with legal
  moves and the expected result direction (teacher wins) — the candidate-101
  checkpoint is the documented overfit demo, so gate *thresholds* are not
  expected to pass yet.
- Not yet done: the versioned tactical suite, baseline strength calibration
  against the teacher (50/200/1000 nodes), and full 800/400-game gate runs.
