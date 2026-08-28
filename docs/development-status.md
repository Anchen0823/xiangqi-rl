# Development status and release gates

This repository is intentionally honest about verification boundaries. A checked box means the corresponding artifact has passed the named local or CI test; it does not imply tournament certification.

## Implemented baseline

- Native C++20 move generation and JSONL request/response process.
- Horse-leg, elephant-eye, cannon-screen, palace, river-pawn, flying-general and self-check constraints.
- Checkmate, stalemate, undo, FEN, 120-ply natural-limit counter and third-occurrence repetition hook.
- Repetition responsibility priority for sole/mutual perpetual check and chase, including the early red-deviation policy.
- CCA 2020 article 26.1 king/pawn direct-chase exemption and newly discovered chase classification.
- Electron/React board with AI/local modes, five UI levels, save/load, FEN and analysis panels.
- PyTorch envelope matching pinned Pikafish HalfKAv2_hm (16,536) and FullThreats (45,547)
  feature transformers, pairwise 1024-to-512 perspective transforms, 16 material stacks,
  PSQT residuals, 1024-to-32-to-32-to-1 dense topology and CUDA smoke diagnostics.

## Required before a stable release

- Validate long-kill, roots, joint chase, exchange invitations and every remaining 2020 exception against official diagrams.
- Differential-test 100,000 random fragments and complete 500 crash-free self-play games.
- Replace the fallback one-ply material move with the pinned Pikafish search and locally trained network.
- Implement exact feature extraction, quantized `.nnue` serialization and Pikafish output parity;
  matching the trainable topology alone is not an export-compatibility claim.
- Pass CUDA fallback parity, gradient, memory-pressure, resume and quantization-error suites.
- Pass the SPRT, tactical and human-club strength gates documented in `strength-protocol.md`.

No stable version tag may be created while any required gate is missing.
