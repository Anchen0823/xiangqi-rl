# Training data and model policy

- Accepted game data must have an explicit ODbL-1.0-compatible grant and retained attribution/provenance metadata.
- Teacher weights must be CC0-1.0. Restricted official Pikafish NNUE files are neither used nor transformed.
- The pinned Fairy-Stockfish teacher separates the GPL engine license from the CC0 Xiangqi network license; installation verifies the upstream release SHA-256 before use.
- Each shard manifest records source, license, retrieval date, record count and SHA-256.
- Datasets, generated labels and checkpoints remain outside Git. The local cache hard limit is 160 GiB.
- A release network includes its configuration, quantization report, training curves, strength report and SHA-256.

Import rejects missing license metadata or a license outside the allowlist. Deleting a source from the allowlist invalidates derived candidates until provenance is reviewed.
