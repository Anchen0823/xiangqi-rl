from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path

import numpy as np
import torch

from .model import NnueConfig, XiangqiNnue
from .thermal import wait_for_safe_temperature


def synthetic_batch(device: torch.device, batch: int, active: int, features: int):
    def bag():
        indices = torch.randint(features, (batch * active,), device=device)
        offsets = torch.arange(0, (batch + 1) * active, active, device=device)
        return indices, offsets
    return (*bag(), *bag(), torch.empty(batch, device=device).uniform_(-1, 1))


def save_checkpoint(path: Path, model: XiangqiNnue, optimizer: torch.optim.Optimizer, step: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    torch.save({"model": model.state_dict(), "optimizer": optimizer.state_dict(), "step": step}, temporary)
    os.replace(temporary, path)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--steps", type=int, default=1000)
    parser.add_argument("--micro-batch", type=int, default=1024)
    parser.add_argument("--accumulate", type=int, default=8)
    parser.add_argument("--checkpoint", type=Path, default=Path("checkpoints/latest.pt"))
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()

    torch.manual_seed(823)
    np.random.seed(823)
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    model = XiangqiNnue().to(device)
    optimizer = torch.optim.AdamW(model.parameters(), lr=1e-3, weight_decay=1e-5)
    start = 0
    if args.resume and args.checkpoint.exists():
        state = torch.load(args.checkpoint, map_location=device, weights_only=False)
        model.load_state_dict(state["model"]); optimizer.load_state_dict(state["optimizer"])
        start = int(state["step"]) + 1
    checkpoint_at = time.monotonic() + 1800
    for step in range(start, args.steps):
        wait_for_safe_temperature()
        optimizer.zero_grad(set_to_none=True)
        loss_value = 0.0
        for _ in range(args.accumulate):
            stm_i, stm_o, opp_i, opp_o, target = synthetic_batch(
                device, args.micro_batch, 32, model.config.feature_count
            )
            with torch.autocast(device.type, enabled=device.type == "cuda", dtype=torch.float16):
                prediction = model(stm_i, stm_o, opp_i, opp_o)
                loss = torch.nn.functional.huber_loss(prediction, target) / args.accumulate
            loss.backward(); loss_value += float(loss.detach())
        optimizer.step()
        if device.type == "cuda" and torch.cuda.memory_allocated() > int(6.5 * 2**30):
            raise RuntimeError("GPU allocation exceeded the configured 6.5 GiB soft limit")
        if step % 10 == 0:
            print(json.dumps({"step": step, "loss": loss_value, "device": str(device)}), flush=True)
        if time.monotonic() >= checkpoint_at:
            save_checkpoint(args.checkpoint, model, optimizer, step)
            checkpoint_at = time.monotonic() + 1800
    save_checkpoint(args.checkpoint, model, optimizer, max(start, args.steps - 1))
