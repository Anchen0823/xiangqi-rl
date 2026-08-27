from __future__ import annotations

import json
import sys

import torch

from .model import NnueConfig, XiangqiNnue


def sparse_batch(device: torch.device, batch: int = 8, active: int = 32):
    indices = torch.randint(0, 4096, (batch * active,), device=device)
    offsets = torch.arange(0, (batch + 1) * active, active, device=device)
    return indices, offsets


def run() -> dict[str, object]:
    if not torch.cuda.is_available():
        raise RuntimeError("CUDA is unavailable")
    device = torch.device("cuda")
    model = XiangqiNnue(NnueConfig(feature_count=4096)).to(device)
    optim = torch.optim.AdamW(model.parameters(), lr=1e-3)
    results: dict[str, object] = {"gpu": torch.cuda.get_device_name(0)}
    for dtype in (torch.float16, torch.bfloat16):
        if dtype is torch.bfloat16 and not torch.cuda.is_bf16_supported():
            results["bf16"] = "unsupported"
            continue
        stm = sparse_batch(device)
        opp = sparse_batch(device)
        target = torch.randn(8, device=device)
        optim.zero_grad(set_to_none=True)
        with torch.autocast("cuda", dtype=dtype):
            loss = torch.nn.functional.mse_loss(model(*stm, *opp), target)
        loss.backward()
        optim.step()
        torch.cuda.synchronize()
        results[str(dtype).split(".")[-1]] = {"loss": float(loss), "backward": True}
    results["allocated_mib"] = round(torch.cuda.max_memory_allocated() / 2**20, 2)
    return results


def main() -> None:
    try:
        print(json.dumps(run(), indent=2))
    except Exception as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, indent=2), file=sys.stderr)
        raise SystemExit(1) from exc
