# Third-party notices

## Pikafish

The optional search backend is fetched from `official-pikafish/Pikafish` at the commit recorded in `third_party/pikafish.rev`. Pikafish is GPLv3. Its source is not vendored in this repository, and official restricted NNUE network files are not fetched or used.

## Electron, React, PyTorch and NVIDIA CUDA

Runtime and development dependencies retain their respective upstream licenses. Package lock files and environment reports record exact versions. NVIDIA CUDA is an optional training-only dependency; desktop CPU inference must not require it.

## Data and teacher networks

Only explicitly recorded ODbL-compatible data and CC0 teacher networks are accepted. See `docs/data-policy.md`.
