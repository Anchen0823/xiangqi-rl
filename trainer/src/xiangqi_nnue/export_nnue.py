from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO, Iterable, Mapping

import numpy as np
import torch

from .model import NnueConfig

try:
    import zstandard as zstd
except ImportError as error:  # pragma: no cover - depends on the optional export dependency
    zstd = None
    _ZSTD_IMPORT_ERROR = error


NETWORK_VERSION = 0x6A448AFA
NETWORK_MAGIC = b"COMPRESSED_LEB128"
OUTPUT_SCALE = 16
WEIGHT_SCALE_BITS = 6
HIDDEN_ONE_VAL = 128
MAX_I8 = 127
MIN_I8 = -128
MAX_I16 = 32_767
MIN_I16 = -32_768
MAX_I32 = 2_147_483_647
MIN_I32 = -2_147_483_648

# Pikafish b97ef0f feature-set hash constants.
THREAT_FEATURE_HASH = 0x2E6B9D04
PSQ_FEATURE_HASH = 0x7F234CB8

# Quantization scales matching Pikafish b97ef0f integer arithmetic. They were
# derived from nnue_feature_transformer.h, nnue_architecture.h and the
# clipped-relu layer shift amounts, and are validated by the closed-loop
# export parity suite rather than by trainer folklore.
ACCUMULATOR_SCALE = 2 * HIDDEN_ONE_VAL  # 256
PSQT_SCALE = 600 * OUTPUT_SCALE  # 9600
FC0_BIAS_SCALE = HIDDEN_ONE_VAL * (1 << (WEIGHT_SCALE_BITS + 1))  # 16384
FC1_BIAS_SCALE = HIDDEN_ONE_VAL * (1 << WEIGHT_SCALE_BITS)  # 8192
FC2_BIAS_SCALE = FC0_BIAS_SCALE


def _u32(value: int) -> bytes:
    if not 0 <= value <= 0xFFFFFFFF:
        raise ValueError(f"u32 out of range: {value}")
    return int(value).to_bytes(4, "little")


def _combine_hash(hashes: Iterable[int]) -> int:
    result = 0
    for component in hashes:
        result = ((result << 1) | (result >> 31)) & 0xFFFFFFFF
        result ^= component & 0xFFFFFFFF
    return result


def feature_transformer_hash() -> int:
    return _combine_hash((THREAT_FEATURE_HASH, PSQ_FEATURE_HASH)) ^ (1024 * 2)


def affine_transform_hash(previous: int, output_dimensions: int) -> int:
    result = (0xCC03DAE4 + output_dimensions) & 0xFFFFFFFF
    result ^= (previous >> 1) & 0xFFFFFFFF
    result ^= (previous << 31) & 0xFFFFFFFF
    return result


def clipped_relu_hash(previous: int) -> int:
    return (0x538D24C7 + previous) & 0xFFFFFFFF


def network_architecture_hash() -> int:
    # ac_sqr_0 and ac_sqr_1 are deliberately absent, matching
    # NetworkArchitecture::get_hash_value() in nnue_architecture.h.
    result = 0xEC42E90D
    result ^= 1024 * 2
    result = affine_transform_hash(result, 32)
    result = clipped_relu_hash(result)
    result = affine_transform_hash(result, 32)
    result = clipped_relu_hash(result)
    result = affine_transform_hash(result, 1)
    return result


def network_hash() -> int:
    return feature_transformer_hash() ^ network_architecture_hash()


def write_leb128_signed(stream: BinaryIO, values: np.ndarray | Iterable[int]) -> int:
    """Write signed LEB128 exactly as Pikafish's write_leb_128 does."""
    encoded = bytearray()
    for raw_value in values:
        value = int(raw_value)
        if not MIN_I32 <= value <= MAX_I32:
            raise ValueError(f"signed LEB128 value out of range: {value}")
        while True:
            byte = value & 0x7F
            value >>= 7  # Python's right shift is arithmetic for negative values.
            stop = value == 0 if (byte & 0x40) == 0 else value == -1
            if stop:
                encoded.append(byte)
                break
            encoded.append(byte | 0x80)
    stream.write(NETWORK_MAGIC)
    stream.write(_u32(len(encoded)))
    stream.write(encoded)
    return len(encoded) + len(NETWORK_MAGIC) + 4


def _quantize_numpy(
    tensor: torch.Tensor, scale: float, dtype: type[np.signedinteger], minimum: int, maximum: int
) -> np.ndarray:
    values = tensor.detach().float().cpu().numpy()
    if not np.all(np.isfinite(values)):
        raise ValueError("refusing to export non-finite model parameters")
    return np.rint(values * scale).clip(minimum, maximum).astype(dtype)


def _as_int16(tensor: torch.Tensor, scale: float) -> np.ndarray:
    return _quantize_numpy(tensor, scale, np.int16, MIN_I16, MAX_I16)


def _as_int8(tensor: torch.Tensor, scale: float) -> np.ndarray:
    return _quantize_numpy(tensor, scale, np.int8, MIN_I8, MAX_I8)


def _as_int32(tensor: torch.Tensor, scale: float) -> np.ndarray:
    return _quantize_numpy(tensor, scale, np.int32, MIN_I32, MAX_I32)


@dataclass(frozen=True)
class QuantizedLayerStack:
    fc0_bias: np.ndarray  # int32[32]
    fc0_weight: np.ndarray  # int8[32, 1024]
    fc1_bias: np.ndarray  # int32[32]
    fc1_weight: np.ndarray  # int8[32, 64]
    fc2_bias: np.ndarray  # int32[1]
    fc2_weight: np.ndarray  # int8[1, 128]

    def validate(self) -> None:
        expected = (
            (self.fc0_bias, (32,), np.int32),
            (self.fc0_weight, (32, 1024), np.int8),
            (self.fc1_bias, (32,), np.int32),
            (self.fc1_weight, (32, 64), np.int8),
            (self.fc2_bias, (1,), np.int32),
            (self.fc2_weight, (1, 128), np.int8),
        )
        for index, (array, shape, dtype) in enumerate(expected):
            if array.shape != shape or array.dtype != dtype:
                raise ValueError(f"quantized layer parameter {index} has shape/dtype "
                                 f"{array.shape}/{array.dtype}, expected {shape}/{dtype}")


@dataclass(frozen=True)
class QuantizedNetwork:
    accumulator_bias: np.ndarray  # int16[1024]
    psq_features: np.ndarray  # int8[16536, 1024]
    threat_features: np.ndarray  # int8[45547, 1024]
    psq_psqt: np.ndarray  # int32[16536, 16]
    threat_psqt: np.ndarray  # int32[45547, 16]
    stacks: tuple[QuantizedLayerStack, ...]

    def validate(self) -> None:
        expected = (
            (self.accumulator_bias, (1024,), np.int16),
            (self.psq_features, (16_536, 1024), np.int8),
            (self.threat_features, (45_547, 1024), np.int8),
            (self.psq_psqt, (16_536, 16), np.int32),
            (self.threat_psqt, (45_547, 16), np.int32),
        )
        for index, (array, shape, dtype) in enumerate(expected):
            if array.shape != shape or array.dtype != dtype:
                raise ValueError(f"quantized network parameter {index} has shape/dtype "
                                 f"{array.shape}/{array.dtype}, expected {shape}/{dtype}")
        if len(self.stacks) != 16:
            raise ValueError(f"expected 16 layer stacks, got {len(self.stacks)}")
        for stack in self.stacks:
            stack.validate()


def quantize_state_dict(
    state_dict: Mapping[str, torch.Tensor], config: NnueConfig = NnueConfig()
) -> QuantizedNetwork:
    """Quantize the trainable PyTorch envelope into Pikafish integer weights."""

    def tensor(name: str) -> torch.Tensor:
        if name not in state_dict:
            raise KeyError(f"model state dict is missing {name}")
        return state_dict[name]

    stacks = []
    for index in range(config.layer_stacks):
        prefix = f"stacks.{index}."
        stacks.append(
            QuantizedLayerStack(
                fc0_bias=_as_int32(tensor(prefix + "hidden1.bias"), FC0_BIAS_SCALE),
                fc0_weight=_as_int8(tensor(prefix + "hidden1.weight"), FC0_BIAS_SCALE / 128),
                fc1_bias=_as_int32(tensor(prefix + "hidden2.bias"), FC1_BIAS_SCALE),
                fc1_weight=_as_int8(tensor(prefix + "hidden2.weight"), FC1_BIAS_SCALE / 128),
                fc2_bias=_as_int32(tensor(prefix + "output.bias"), FC2_BIAS_SCALE),
                fc2_weight=_as_int8(tensor(prefix + "output.weight"), FC2_BIAS_SCALE / 128),
            )
        )

    quantized = QuantizedNetwork(
        accumulator_bias=_as_int16(tensor("accumulator_bias"), ACCUMULATOR_SCALE),
        psq_features=_as_int8(tensor("psq_features.weight"), ACCUMULATOR_SCALE),
        threat_features=_as_int8(tensor("threat_features.weight"), ACCUMULATOR_SCALE),
        psq_psqt=_as_int32(tensor("psq_psqt.weight"), PSQT_SCALE),
        threat_psqt=_as_int32(tensor("threat_psqt.weight"), PSQT_SCALE),
        stacks=tuple(stacks),
    )
    quantized.validate()
    return quantized


def uncompressed_chunks(
    network: QuantizedNetwork, description: str = "Xiangqi RL NNUE"
) -> Iterable[bytes]:
    """Yield the exact uncompressed Pikafish network byte stream in order."""
    network.validate()
    if "\x00" in description:
        raise ValueError("network description cannot contain NUL")
    encoded_description = description.encode("utf-8")
    if len(encoded_description) > 0xFFFFFFFF:
        raise ValueError("network description is too long")

    yield _u32(NETWORK_VERSION)
    yield _u32(network_hash())
    yield _u32(len(encoded_description))
    yield encoded_description

    # FeatureTransformer block: hash header then parameters in read order.
    yield _u32(feature_transformer_hash())
    bias_buffer = io.BytesIO()
    write_leb128_signed(bias_buffer, network.accumulator_bias)
    yield bias_buffer.getvalue()
    yield network.threat_features.astype("<i1", copy=False).tobytes()
    threat_psqt_buffer = io.BytesIO()
    write_leb128_signed(threat_psqt_buffer, network.threat_psqt.ravel())
    yield threat_psqt_buffer.getvalue()
    yield network.psq_features.astype("<i1", copy=False).tobytes()
    psqt_buffer = io.BytesIO()
    write_leb128_signed(psqt_buffer, network.psq_psqt.ravel())
    yield psqt_buffer.getvalue()

    # Sixteen NetworkArchitecture blocks. Each has one hash header and writes
    # fc0, fc1, fc2 sequentially; the activation layers carry no parameters.
    architecture_hash = network_architecture_hash()
    for stack in network.stacks:
        yield _u32(architecture_hash)
        yield stack.fc0_bias.astype("<i4", copy=False).tobytes()
        yield stack.fc0_weight.astype("<i1", copy=False).tobytes()
        yield stack.fc1_bias.astype("<i4", copy=False).tobytes()
        yield stack.fc1_weight.astype("<i1", copy=False).tobytes()
        yield stack.fc2_bias.astype("<i4", copy=False).tobytes()
        yield stack.fc2_weight.astype("<i1", copy=False).tobytes()


def write_nnue(
    path: str | Path,
    state_dict: Mapping[str, torch.Tensor],
    *,
    description: str = "Xiangqi RL NNUE",
    compression_level: int = 3,
    config: NnueConfig = NnueConfig(),
) -> dict[str, object]:
    """Quantize a PyTorch state dict and write a Pikafish-loadable .nnue file."""
    if zstd is None:
        raise RuntimeError(
            "zstandard is required for .nnue export; install it with "
            "'pip install zstandard'"
        ) from _ZSTD_IMPORT_ERROR
    if not 1 <= compression_level <= 22:
        raise ValueError("compression_level must be in [1, 22]")
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".tmp")

    quantized = quantize_state_dict(state_dict, config)
    compressor = zstd.ZstdCompressor(level=compression_level)
    try:
        with temporary.open("wb") as output:
            with compressor.stream_writer(output, closefd=False) as compressed:
                for chunk in uncompressed_chunks(quantized, description):
                    compressed.write(chunk)
        sha256 = hashlib.sha256()
        with temporary.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                sha256.update(chunk)
        os.replace(temporary, destination)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise

    return {
        "path": str(destination),
        "bytes": destination.stat().st_size,
        "sha256": sha256.hexdigest(),
        "description": description,
        "networkVersion": hex(NETWORK_VERSION),
        "networkHash": hex(network_hash()),
    }


def load_state_dict(path: Path) -> Mapping[str, torch.Tensor]:
    checkpoint = torch.load(path, map_location="cpu", weights_only=False)
    if isinstance(checkpoint, dict) and "model" in checkpoint:
        return checkpoint["model"]
    return checkpoint


def main() -> None:
    parser = argparse.ArgumentParser(description="Export a trained XiangqiNnue checkpoint to .nnue")
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--description", default="Xiangqi RL NNUE")
    parser.add_argument("--compression-level", type=int, default=3)
    args = parser.parse_args()
    state = load_state_dict(args.checkpoint)
    report = write_nnue(
        args.output,
        state,
        description=args.description,
        compression_level=args.compression_level,
    )
    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
