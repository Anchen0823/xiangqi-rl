# NNUE export and Pikafish readback

Status: 2026-08-28, implementation-level validation. This document records the
closed loop for the highest-priority blocker from `docs/amateur-strength-plan.md`:
a PyTorch checkpoint can now be quantized, serialized as a Pikafish `.nnue`
file, loaded by the pinned search binary, and read back through the UCI `eval`
trace.

## Scope

- New module: `trainer/src/xiangqi_nnue/export_nnue.py`
  - Exact Pikafish network header and component hashes for pinned revision
    `b97ef0f`.
  - Signed LEB128 writer byte-compatible with `nnue_common.h`.
  - Feature transformer and 16 layer stacks serialized in Pikafish read order.
  - Zstandard-compressed output with atomic replace and SHA-256 metadata.
- New module: `trainer/src/xiangqi_nnue/parity.py`
  - Integer-exact Python model of Pikafish's quantized evaluation.
  - Minimal UCI client for the `eval` trace.
  - Float/quantized/engine comparison helper.
- New integration test: `trainer/tests/test_export_nnue.py`.

## Format decisions derived from the pinned source

| Component | Pikafish type | Quantization |
|---|---|---|
| Feature-transformer accumulator bias | int16 | `round(256 * accumulator_bias)` |
| PSQ feature weights | int8 | `round(256 * psq_features)` |
| Threat feature weights | int8 | `round(256 * threat_features)` |
| PSQ/threat PSQT residuals | int32 | `round(9600 * *_psqt)` |
| fc0 (`hidden1`) bias / weight | int32 / int8 | `16384 *` / `128 *` |
| fc1 (`hidden2`) bias / weight | int32 / int8 | `8192 *` / `64 *` |
| fc2 (`output`) bias / weight | int32 / int8 | `16384 *` / `128 *` |

Important detail: dense-layer biases are `OutputType = int32`, not the int16
used by the feature transformer. The test suite pins this layout explicitly.

Verified constants:

- `FeatureTransformer::get_hash_value() = 0x23f47eb0`
- `NetworkArchitecture::get_hash_value() = 0x63337116`
- `Network::hash = 0x40c70fa6`
- `Version = 0x6a448afa`

The hashes were cross-checked against a standalone C++ program compiled from
`native/vendor/Pikafish` headers at revision `b97ef0f`.

## Results

### Random-weight closed loop

A deterministic full-size random model was exported and evaluated on the
initial Xiangqi FEN:

- float PyTorch internal: `-53.79`
- integer Python simulator: `-52`
- Pikafish `eval` internal: `-52`
- float-to-engine error: `1.79` internal units

The exported `.nnue` was accepted by `native/bin/pikafish.exe` and the
quantized Python simulator matched the engine exactly.

### Candidate-101 checkpoint

`checkpoints/candidate-101.pt` exported successfully as
`checkpoints/candidate-101.nnue` (33,689,495 bytes). Across 10 deterministic
random legal positions from the native rules engine:

- quantized simulator matched Pikafish `eval` exactly on all 10 positions;
- maximum absolute float-to-engine error was `5.63` internal units.

This does not say anything about playing strength: candidate-101 remains the
documented overfit calibration run. It only demonstrates that the export path
works for real training checkpoints.

## Validation boundary

- `python -m unittest discover -s trainer/tests` now runs 37 tests, all pass.
- CI trainer job installs `zstandard`; the Pikafish readback test auto-skips
  when the pinned engine binary is absent.
- Not yet done: large randomized FEN parity suite, quantization-error suite,
  quantized search stability games, and strength gates. Those remain in the
  plan before any champion claim.
