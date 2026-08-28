from __future__ import annotations

import argparse
import json
import queue
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

import torch
from torch import Tensor

from .model import NnueConfig


class FeatureProtocolError(RuntimeError):
    """Raised when the pinned engine returns an invalid feature response."""


@dataclass(frozen=True)
class PerspectiveFeatures:
    color: str
    feature_bucket: int
    attack_bucket: int
    mirror: bool
    psq: tuple[int, ...]
    threats: tuple[int, ...]


@dataclass(frozen=True)
class PositionFeatures:
    layer_bucket: int
    perspectives: tuple[PerspectiveFeatures, PerspectiveFeatures]

    @property
    def side_to_move(self) -> PerspectiveFeatures:
        return self.perspectives[0]

    @property
    def opponent(self) -> PerspectiveFeatures:
        return self.perspectives[1]


def _integer(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise FeatureProtocolError(f"{field} must be an integer")
    return value


def _indices(value: Any, field: str, upper_bound: int) -> tuple[int, ...]:
    if not isinstance(value, list):
        raise FeatureProtocolError(f"{field} must be an array")
    result = tuple(_integer(index, field) for index in value)
    if any(index < 0 or index >= upper_bound for index in result):
        raise FeatureProtocolError(f"{field} contains an out-of-range feature index")
    return result


def parse_training_features(
    line: str, config: NnueConfig = NnueConfig()
) -> PositionFeatures:
    try:
        payload = json.loads(line)
    except json.JSONDecodeError as error:
        raise FeatureProtocolError("engine feature response is not valid JSON") from error
    if not isinstance(payload, dict):
        raise FeatureProtocolError("engine feature response must be an object")

    layer_bucket = _integer(payload.get("layerBucket"), "layerBucket")
    if not 0 <= layer_bucket < config.layer_stacks:
        raise FeatureProtocolError("layerBucket is outside the configured range")
    raw_perspectives = payload.get("perspectives")
    if not isinstance(raw_perspectives, list) or len(raw_perspectives) != 2:
        raise FeatureProtocolError("exactly two perspectives are required")

    perspectives: list[PerspectiveFeatures] = []
    for index, raw in enumerate(raw_perspectives):
        if not isinstance(raw, dict):
            raise FeatureProtocolError(f"perspectives[{index}] must be an object")
        color = raw.get("color")
        if color not in ("red", "black"):
            raise FeatureProtocolError(f"perspectives[{index}].color is invalid")
        mirror = raw.get("mirror")
        if not isinstance(mirror, bool):
            raise FeatureProtocolError(f"perspectives[{index}].mirror must be boolean")
        perspectives.append(
            PerspectiveFeatures(
                color=color,
                feature_bucket=_integer(
                    raw.get("featureBucket"), f"perspectives[{index}].featureBucket"
                ),
                attack_bucket=_integer(
                    raw.get("attackBucket"), f"perspectives[{index}].attackBucket"
                ),
                mirror=mirror,
                psq=_indices(
                    raw.get("psq"),
                    f"perspectives[{index}].psq",
                    config.psq_feature_count,
                ),
                threats=_indices(
                    raw.get("threats"),
                    f"perspectives[{index}].threats",
                    config.threat_feature_count,
                ),
            )
        )
    if perspectives[0].color == perspectives[1].color:
        raise FeatureProtocolError("perspective colors must be different")
    return PositionFeatures(layer_bucket, (perspectives[0], perspectives[1]))


def _bag(
    positions: Sequence[PositionFeatures],
    perspective: int,
    field: str,
    device: torch.device | str | None,
) -> tuple[Tensor, Tensor]:
    flattened: list[int] = []
    offsets = [0]
    for position in positions:
        flattened.extend(getattr(position.perspectives[perspective], field))
        offsets.append(len(flattened))
    return (
        torch.tensor(flattened, dtype=torch.long, device=device),
        torch.tensor(offsets, dtype=torch.long, device=device),
    )


def collate_model_inputs(
    positions: Sequence[PositionFeatures], device: torch.device | str | None = None
) -> tuple[Tensor, ...]:
    """Convert validated engine responses to XiangqiNnue.forward inputs."""
    if not positions:
        raise ValueError("cannot collate an empty position batch")
    return (
        *_bag(positions, 0, "psq", device),
        *_bag(positions, 0, "threats", device),
        *_bag(positions, 1, "psq", device),
        *_bag(positions, 1, "threats", device),
        torch.tensor(
            [position.layer_bucket for position in positions],
            dtype=torch.long,
            device=device,
        ),
    )


class PikafishFeatureClient:
    """Long-lived JSONL client for the maintained Pikafish training patch."""

    def __init__(self, command: str | Path | Sequence[str | Path], timeout: float = 10.0):
        if isinstance(command, (str, Path)):
            argv = [str(command)]
        else:
            argv = [str(part) for part in command]
        if not argv:
            raise ValueError("engine command cannot be empty")
        self.timeout = timeout
        self._process = subprocess.Popen(
            argv,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
        )
        self._lines: queue.Queue[str | None] = queue.Queue()
        self._lock = threading.Lock()
        self._reader = threading.Thread(target=self._read_output, daemon=True)
        self._reader.start()

    def _read_output(self) -> None:
        assert self._process.stdout is not None
        try:
            for line in self._process.stdout:
                self._lines.put(line.rstrip("\r\n"))
        finally:
            self._lines.put(None)

    def _send(self, command: str) -> None:
        if self._process.poll() is not None:
            raise FeatureProtocolError(
                f"Pikafish exited before the request (code {self._process.returncode})"
            )
        assert self._process.stdin is not None
        self._process.stdin.write(command + "\n")
        self._process.stdin.flush()

    def _query(self, position_command: str, expected_color: str) -> PositionFeatures:
        with self._lock:
            self._send(position_command)
            self._send("training_features")
            deadline = time.monotonic() + self.timeout
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError("timed out waiting for Pikafish training features")
                try:
                    line = self._lines.get(timeout=remaining)
                except queue.Empty as error:
                    raise TimeoutError(
                        "timed out waiting for Pikafish training features"
                    ) from error
                if line is None:
                    raise FeatureProtocolError(
                        f"Pikafish exited during the request (code {self._process.poll()})"
                    )
                if line.startswith('{"layerBucket"'):
                    result = parse_training_features(line)
                    if result.side_to_move.color != expected_color:
                        raise FeatureProtocolError(
                            "engine perspective order does not match the FEN side to move"
                        )
                    return result

    def start_position(self) -> PositionFeatures:
        return self._query("position startpos", "red")

    def fen(self, fen: str) -> PositionFeatures:
        if "\n" in fen or "\r" in fen:
            raise ValueError("FEN cannot contain a newline")
        fields = fen.split()
        if len(fields) < 2 or fields[1] not in ("w", "b"):
            raise ValueError("FEN must include a w or b side-to-move field")
        return self._query("position fen " + fen, "red" if fields[1] == "w" else "black")

    def close(self) -> None:
        with self._lock:
            if self._process.poll() is None:
                try:
                    self._send("quit")
                    self._process.wait(timeout=2)
                except (BrokenPipeError, subprocess.TimeoutExpired):
                    self._process.kill()
                    self._process.wait(timeout=2)
            if self._process.stdin is not None:
                self._process.stdin.close()
            if self._process.stdout is not None:
                self._process.stdout.close()

    def __enter__(self) -> PikafishFeatureClient:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Inspect exact Pikafish NNUE features")
    parser.add_argument("--engine", type=Path, required=True)
    parser.add_argument("--fen")
    args = parser.parse_args()
    with PikafishFeatureClient(args.engine) as client:
        features = client.fen(args.fen) if args.fen else client.start_position()
    print(json.dumps(features, default=lambda value: value.__dict__, separators=(",", ":")))


if __name__ == "__main__":
    main()
