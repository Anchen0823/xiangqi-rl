from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import random
import time
from pathlib import Path
from typing import Any, Iterator

import numpy as np
import torch
from torch import Tensor

from .config import TrainingConfig, cosine_warmup_lr
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


def manifest_total_records(directory: Path) -> int:
    manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    total = int(manifest.get("totalRecords", 0))
    if total <= 0:
        raise ValueError(f"dataset manifest has no records: {directory}")
    return total


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


class MetricAccumulator:
    """Running Huber / MAE / Pearson statistics over prediction-target pairs."""

    def __init__(self) -> None:
        self.huber_sum = 0.0
        self.mae_sum = 0.0
        self.count = 0
        self.n = 0.0
        self.sx = self.sy = self.sxy = self.sx2 = self.sy2 = 0.0

    def update(self, prediction: Tensor, target: Tensor) -> None:
        pred = prediction.detach().float()
        tgt = target.detach().float()
        self.huber_sum += float(torch.nn.functional.huber_loss(pred, tgt, reduction="sum"))
        self.mae_sum += float((pred - tgt).abs().sum())
        batch = pred.numel()
        self.count += batch
        self.n += batch
        self.sx += float(pred.sum())
        self.sy += float(tgt.sum())
        self.sxy += float((pred * tgt).sum())
        self.sx2 += float((pred * pred).sum())
        self.sy2 += float((tgt * tgt).sum())

    def summary(self) -> dict[str, float]:
        if self.count == 0:
            return {"huber": math.nan, "mae": math.nan, "pearson": math.nan, "records": 0}
        denom = math.sqrt(max(0.0, self.n * self.sx2 - self.sx * self.sx) * max(
            0.0, self.n * self.sy2 - self.sy * self.sy
        ))
        pearson = (self.n * self.sxy - self.sx * self.sy) / denom if denom > 0 else 0.0
        return {
            "huber": self.huber_sum / self.count,
            "mae": self.mae_sum / self.count,
            "pearson": float(np.clip(pearson, -1.0, 1.0)),
            "records": self.count,
        }


@torch.no_grad()
def evaluate_records(
    model: XiangqiNnue,
    records: Iterator[TrainingRecord],
    device: torch.device,
    micro_batch: int,
    *,
    limit: int | None = None,
) -> dict[str, float]:
    """Compute Huber / MAE / Pearson over a record iterator in eval mode."""
    model.eval()
    accumulator = MetricAccumulator()
    batch_records: list[TrainingRecord] = []
    for record in records:
        if limit is not None and accumulator.count >= limit:
            break
        batch_records.append(record)
        if len(batch_records) >= micro_batch:
            features = list(collate_model_inputs([r.features for r in batch_records], device))
            target = torch.tensor(
                [training_target(r) for r in batch_records], dtype=torch.float32, device=device
            )
            with torch.autocast(device.type, enabled=device.type == "cuda", dtype=torch.float16):
                accumulator.update(model(*features), target)
            batch_records = []
    if batch_records:
        features = list(collate_model_inputs([r.features for r in batch_records], device))
        target = torch.tensor(
            [training_target(r) for r in batch_records], dtype=torch.float32, device=device
        )
        with torch.autocast(device.type, enabled=device.type == "cuda", dtype=torch.float16):
            accumulator.update(model(*features), target)
    model.train()
    return accumulator.summary()


def save_checkpoint(
    path: Path,
    model: XiangqiNnue,
    optimizer: torch.optim.Optimizer,
    step: int,
    *,
    data_source: StreamingBatchSource | None = None,
    dataset_hash: str | None = None,
    best_val_huber: float | None = None,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    payload: dict[str, Any] = {
        "model": model.state_dict(), "optimizer": optimizer.state_dict(), "step": step
    }
    if best_val_huber is not None:
        payload["best_val_huber"] = best_val_huber
    if data_source is not None:
        payload["data"] = data_source.state_dict()
        payload["dataset_manifest_sha256"] = dataset_hash
    torch.save(payload, temporary)
    os.replace(temporary, path)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, default=Path("trainer/config/train.toml"))
    parser.add_argument("--dataset", type=Path)
    parser.add_argument("--val-dataset", type=Path)
    parser.add_argument("--synthetic-smoke", action="store_true")
    parser.add_argument("--steps", type=int, default=None)
    parser.add_argument("--micro-batch", type=int, default=None)
    parser.add_argument("--accumulate", type=int, default=None)
    parser.add_argument("--shuffle-buffer", type=int, default=None)
    parser.add_argument("--checkpoint", type=Path, default=Path("checkpoints/latest.pt"))
    parser.add_argument("--best-checkpoint", type=Path, default=Path("checkpoints/best.pt"))
    parser.add_argument("--metrics", type=Path, default=Path("checkpoints/metrics.jsonl"))
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()
    if args.synthetic_smoke == (args.dataset is not None):
        parser.error("choose exactly one of --dataset or --synthetic-smoke")
    if args.steps is not None and args.steps <= 0:
        parser.error("steps must be positive")

    config = TrainingConfig.from_toml(args.config)
    micro_batch = args.micro_batch or config.micro_batch_size
    accumulate = args.accumulate or config.accumulate
    shuffle_buffer = args.shuffle_buffer or config.shuffle_buffer
    if micro_batch <= 0 or accumulate <= 0 or shuffle_buffer < micro_batch:
        parser.error("micro-batch, accumulate, and shuffle-buffer must be positive and consistent")

    torch.manual_seed(config.seed)
    np.random.seed(config.seed)
    random.seed(config.seed)
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    model = XiangqiNnue(config.model).to(device)
    optimizer = torch.optim.AdamW(model.parameters(), lr=config.learning_rate,
                                  weight_decay=config.weight_decay)
    data_source = None
    dataset_hash = None
    total_records = 0
    if args.dataset is not None:
        dataset_hash = manifest_sha256(args.dataset)
        total_records = manifest_total_records(args.dataset)
        data_source = StreamingBatchSource(args.dataset, micro_batch, shuffle_buffer,
                                           seed=config.seed)

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

    steps_per_epoch = max(1, total_records // (micro_batch * accumulate)) if data_source else 1
    max_steps = args.steps if args.steps is not None else (
        config.max_epochs * steps_per_epoch if data_source else 1000
    )
    if max_steps <= start:
        print(json.dumps({"event": "already_done", "step": start, "max_steps": max_steps}))
        return

    checkpoint_at = time.monotonic() + config.checkpoint_seconds
    metrics_handle = args.metrics.open("a", encoding="utf-8") if args.val_dataset else None
    train_metrics = MetricAccumulator()
    next_val_epoch = config.val_interval_epochs
    best_val_huber = math.inf
    best_val_epoch = 0.0
    early_stopped = False

    def log_metrics(step: int, epoch: float, lr: float, *, val: dict[str, float] | None) -> None:
        line = {
            "step": step, "epoch": round(epoch, 3), "lr": lr,
            "train": train_metrics.summary(), "val": val,
            "best_val_huber": None if math.isinf(best_val_huber) else best_val_huber,
        }
        print(json.dumps(line), flush=True)
        if metrics_handle is not None:
            metrics_handle.write(json.dumps(line) + "\n")
            metrics_handle.flush()

    try:
        for step in range(start, max_steps):
            wait_for_safe_temperature(config.temperature_pause_c, config.temperature_resume_c)
            lr = cosine_warmup_lr(step, config.warmup_steps, max_steps, config.learning_rate)
            for group in optimizer.param_groups:
                group["lr"] = lr
            optimizer.zero_grad(set_to_none=True)
            loss_value = 0.0
            for _ in range(accumulate):
                if data_source is None:
                    *features, target = synthetic_batch(device, micro_batch, 32, config.model)
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
                    loss = torch.nn.functional.huber_loss(prediction, target) / accumulate
                loss.backward()
                loss_value += float(loss.detach())
                train_metrics.update(prediction, target)
            optimizer.step()
            if device.type == "cuda" and torch.cuda.memory_allocated() > int(
                config.memory_soft_limit_gib * 2**30
            ):
                raise RuntimeError("GPU allocation exceeded the configured soft limit")
            if step % 10 == 0:
                print(json.dumps({
                    "step": step,
                    "loss": loss_value,
                    "lr": lr,
                    "device": str(device),
                    "data": "synthetic-smoke" if data_source is None else str(args.dataset),
                }), flush=True)
            if data_source is not None:
                epoch = step / steps_per_epoch
                if epoch >= next_val_epoch:
                    if args.val_dataset is not None:
                        val = evaluate_records(
                            model, read_records(args.val_dataset), device, micro_batch
                        )
                        if val["huber"] < best_val_huber:
                            best_val_huber = val["huber"]
                            best_val_epoch = epoch
                            save_checkpoint(
                                args.best_checkpoint, model, optimizer, step,
                                best_val_huber=best_val_huber,
                            )
                        if epoch - best_val_epoch >= config.early_stop_patience_epochs:
                            early_stopped = True
                    else:
                        val = None
                    log_metrics(step, epoch, lr, val=val)
                    train_metrics = MetricAccumulator()
                    next_val_epoch += config.val_interval_epochs
                    if early_stopped:
                        print(json.dumps({
                            "event": "early_stop",
                            "step": step,
                            "epoch": round(epoch, 3),
                            "best_val_huber": best_val_huber,
                        }), flush=True)
                        break
            if time.monotonic() >= checkpoint_at:
                save_checkpoint(
                    args.checkpoint, model, optimizer, step,
                    data_source=data_source, dataset_hash=dataset_hash,
                    best_val_huber=None if math.isinf(best_val_huber) else best_val_huber,
                )
                checkpoint_at = time.monotonic() + config.checkpoint_seconds
        save_checkpoint(
            args.checkpoint, model, optimizer, max(start, max_steps - 1),
            data_source=data_source, dataset_hash=dataset_hash,
            best_val_huber=None if math.isinf(best_val_huber) else best_val_huber,
        )
        if data_source is not None and not early_stopped and args.val_dataset is not None:
            epoch = max_steps / steps_per_epoch
            val = evaluate_records(model, read_records(args.val_dataset), device, micro_batch)
            log_metrics(max_steps - 1, epoch, lr, val=val)
    finally:
        if metrics_handle is not None:
            metrics_handle.close()
        if data_source is not None:
            data_source.close()


if __name__ == "__main__":
    main()
