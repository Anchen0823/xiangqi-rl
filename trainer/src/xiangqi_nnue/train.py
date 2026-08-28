from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import random
import time
from pathlib import Path
from typing import Any

import numpy as np
import torch

from .dataset import TrainingRecord, read_records
from .features import collate_model_inputs
from .model import NnueConfig, XiangqiNnue
from .thermal import wait_for_safe_temperature


def synthetic_batch(device: torch.device, batch: int, active: int, config: NnueConfig):
    def bag(feature_count: int):
        indices = torch.randint(feature_count, (batch * active,), device=device)
        offsets = torch.arange(0, (batch + 1) * active, active, device=device)
        return indices, offsets

    psq = lambda: bag(config.psq_feature_count)
    threat = lambda: bag(config.threat_feature_count)
    buckets = torch.randint(config.layer_stacks, (batch,), device=device)
    return (
        *psq(), *threat(), *psq(), *threat(), buckets,
        torch.empty(batch, device=device).uniform_(-1, 1),
    )


def training_target(record: TrainingRecord) -> float:
    teacher = math.tanh(record.score_cp / 600.0)
    return teacher if record.outcome is None else 0.85 * teacher + 0.15 * record.outcome


def manifest_sha256(directory: Path) -> str:
    return hashlib.sha256((directory / "manifest.json").read_bytes()).hexdigest()


class StreamingBatchSource:
    """Bounded-memory shard shuffle with an exactly checkpointable cursor."""

    def __init__(self, directory: Path, batch_size: int, shuffle_buffer: int, seed: int = 823):
        if batch_size <= 0 or shuffle_buffer < batch_size:
            raise ValueError("shuffle_buffer must be at least one positive batch")
        self.directory = directory
        self.batch_size = batch_size
        self.shuffle_buffer = shuffle_buffer
        self.rng = random.Random(seed)
        self.epoch = 0
        self.source_offset = 0
        self.buffer: list[TrainingRecord] = []
        self._source = iter(read_records(directory))
        self._saw_record = False

    def _reset_source(self) -> None:
        self._close_source()
        self._source = iter(read_records(self.directory))
        self.source_offset = 0
        self.epoch += 1

    def _next_record(self) -> TrainingRecord:
        while len(self.buffer) < self.shuffle_buffer:
            try:
                self.buffer.append(next(self._source))
                self.source_offset += 1
                self._saw_record = True
            except StopIteration:
                if self.buffer:
                    break
                if not self._saw_record:
                    raise ValueError("training dataset contains no records")
                self._reset_source()
        return self.buffer.pop(self.rng.randrange(len(self.buffer)))

    def next_batch(self) -> list[TrainingRecord]:
        return [self._next_record() for _ in range(self.batch_size)]

    def state_dict(self) -> dict[str, Any]:
        return {
            "epoch": self.epoch,
            "source_offset": self.source_offset,
            "buffer": [record.to_dict() for record in self.buffer],
            "rng_state": self.rng.getstate(),
        }

    def load_state_dict(self, state: dict[str, Any]) -> None:
        self.epoch = int(state["epoch"])
        self.source_offset = int(state["source_offset"])
        self.buffer = [TrainingRecord.from_dict(item) for item in state["buffer"]]
        self.rng.setstate(state["rng_state"])
        self._close_source()
        self._source = iter(read_records(self.directory))
        for _ in range(self.source_offset):
            try:
                next(self._source)
            except StopIteration as error:
                raise ValueError("checkpoint cursor exceeds the current dataset") from error
        self._saw_record = self.source_offset > 0 or bool(self.buffer)

    def _close_source(self) -> None:
        close = getattr(self._source, "close", None)
        if close is not None:
            close()

    def close(self) -> None:
        self._close_source()

    def __enter__(self) -> StreamingBatchSource:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()


def save_checkpoint(
    path: Path,
    model: XiangqiNnue,
    optimizer: torch.optim.Optimizer,
    step: int,
    *,
    data_source: StreamingBatchSource | None = None,
    dataset_hash: str | None = None,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    payload: dict[str, Any] = {
        "model": model.state_dict(), "optimizer": optimizer.state_dict(), "step": step
    }
    if data_source is not None:
        payload["data"] = data_source.state_dict()
        payload["dataset_manifest_sha256"] = dataset_hash
    torch.save(payload, temporary)
    os.replace(temporary, path)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", type=Path)
    parser.add_argument("--synthetic-smoke", action="store_true")
    parser.add_argument("--steps", type=int, default=1000)
    parser.add_argument("--micro-batch", type=int, default=1024)
    parser.add_argument("--accumulate", type=int, default=8)
    parser.add_argument("--shuffle-buffer", type=int, default=8192)
    parser.add_argument("--checkpoint", type=Path, default=Path("checkpoints/latest.pt"))
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()
    if args.synthetic_smoke == (args.dataset is not None):
        parser.error("choose exactly one of --dataset or --synthetic-smoke")
    if args.steps <= 0 or args.micro_batch <= 0 or args.accumulate <= 0:
        parser.error("steps, micro-batch, and accumulate must be positive")

    torch.manual_seed(823)
    np.random.seed(823)
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    model = XiangqiNnue().to(device)
    optimizer = torch.optim.AdamW(model.parameters(), lr=1e-3, weight_decay=1e-5)
    data_source = None
    dataset_hash = None
    if args.dataset is not None:
        dataset_hash = manifest_sha256(args.dataset)
        data_source = StreamingBatchSource(args.dataset, args.micro_batch, args.shuffle_buffer)

    start = 0
    if args.resume and args.checkpoint.exists():
        state = torch.load(args.checkpoint, map_location=device, weights_only=False)
        model.load_state_dict(state["model"])
        optimizer.load_state_dict(state["optimizer"])
        start = int(state["step"]) + 1
        if data_source is not None:
            if state.get("dataset_manifest_sha256") != dataset_hash:
                raise ValueError("checkpoint dataset manifest SHA-256 does not match")
            data_source.load_state_dict(state["data"])

    checkpoint_at = time.monotonic() + 1800
    for step in range(start, args.steps):
        wait_for_safe_temperature()
        optimizer.zero_grad(set_to_none=True)
        loss_value = 0.0
        for _ in range(args.accumulate):
            if data_source is None:
                *features, target = synthetic_batch(device, args.micro_batch, 32, model.config)
            else:
                records = data_source.next_batch()
                features = list(collate_model_inputs([record.features for record in records], device))
                target = torch.tensor(
                    [training_target(record) for record in records],
                    dtype=torch.float32,
                    device=device,
                )
            with torch.autocast(device.type, enabled=device.type == "cuda", dtype=torch.float16):
                prediction = model(*features)
                loss = torch.nn.functional.huber_loss(prediction, target) / args.accumulate
            loss.backward()
            loss_value += float(loss.detach())
        optimizer.step()
        if device.type == "cuda" and torch.cuda.memory_allocated() > int(6.5 * 2**30):
            raise RuntimeError("GPU allocation exceeded the configured 6.5 GiB soft limit")
        if step % 10 == 0:
            print(json.dumps({
                "step": step,
                "loss": loss_value,
                "device": str(device),
                "data": "synthetic-smoke" if data_source is None else str(args.dataset),
            }), flush=True)
        if time.monotonic() >= checkpoint_at:
            save_checkpoint(
                args.checkpoint, model, optimizer, step,
                data_source=data_source, dataset_hash=dataset_hash,
            )
            checkpoint_at = time.monotonic() + 1800
    save_checkpoint(
        args.checkpoint, model, optimizer, max(start, args.steps - 1),
        data_source=data_source, dataset_hash=dataset_hash,
    )
    if data_source is not None:
        data_source.close()


if __name__ == "__main__":
    main()
