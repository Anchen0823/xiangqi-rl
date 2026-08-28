# Local CUDA validation

Validated on 2026-08-28. This report records environment evidence; it is not a
claim that the fused sparse-feature extension or a full training run has passed.

| Check | Result |
| --- | --- |
| GPU | NVIDIA GeForce RTX 4060 Laptop GPU, compute capability 8.9 |
| Driver | 610.88 |
| Toolkit | CUDA 13.3, nvcc 13.3.73 |
| Host compiler | Visual Studio 2022 x64 tools 17.10.5 |
| Native kernel | `trainer/cuda/device_smoke.cu`: PASS |
| Device memory | 8,585,216,000 bytes (PyTorch reports 8.0 GiB) |
| Python | 3.12.10 |
| PyTorch | 2.12.1+cu132, CUDA available |
| FP16 | forward, backward and optimizer step: PASS |
| BF16 | supported; forward, backward and optimizer step: PASS |
| NNUE smoke peak | 144.62 MiB allocated |
| Test temperature | 62-65 C |

The installed Toolkit is newer than the cu132 runtime bundled by PyTorch.
Standalone nvcc compilation and PyTorch kernels both pass. Custom extension
build and numerical parity remain mandatory before enabling fused training.
