# Training run: candidate-101

This report records a reproducible local training run. It is an experiment
record, not a claim that the candidate has passed the human strength gate.

## Inputs

- Source: `datasets/selfplay-v1-calibration-2w`
- Source positions: 2,975
- Teacher: Fairy-Stockfish Xiangqi CC0 network, verified by the repository
  manifest
- Features: extracted with `native/bin/pikafish.exe`
- Labeled dataset: `datasets/selfplay-v1-calibration-2w-labeled`
- Labeled dataset manifest SHA-256: `315521b0e727f8b3439bfecfa98b50cf75686cec8d92ebfcb45d7405b68acac5`
- Device: NVIDIA GeForce RTX 4060 Laptop GPU
- Runtime: PyTorch `2.12.1+cu132`, CUDA available

## Training

The candidate was trained with:

```powershell
$env:PYTHONPATH = 'trainer/src'
\.venv\Scripts\python.exe -m xiangqi_nnue.train `
  --dataset datasets\selfplay-v1-calibration-2w-labeled `
  --steps 1001 --micro-batch 64 --accumulate 1 `
  --shuffle-buffer 1024 --checkpoint checkpoints\candidate-101.pt
```

The first 101 steps were run from scratch, followed by a resume to step 1000.
Observed Huber loss decreased from `0.1166227` at step 0 to `0.0003908` at
step 1000. The final checkpoint is 782,181,555 bytes, has SHA-256
`6232b114c4666de556d2951b90489f0b79cc0957bcbb72cb94bc855f84361b24`, and its
floating-point parameters are finite.

## Validation boundary

- Trainer unit tests: 31 passed.
- CUDA smoke: passed for float16 and bfloat16 forward/backward/optimizer steps.
- TypeScript typecheck: passed.
- Native rules test: passed.
- Human-club gate: not run; no verified club-player games are available.
- 800-game baseline and 400-game teacher SPRT: not run.
- Native Pikafish integration: not passed for this PyTorch checkpoint; the
  checkpoint is not an exported `.nnue` file and is not the active search
  network.

Therefore this run demonstrates a valid, converged training artifact but does
not yet justify claiming that the trained model defeats an amateur player.
