from __future__ import annotations

import json
import platform
import shutil
import subprocess

import torch


def collect() -> dict[str, object]:
    cuda = torch.cuda.is_available()
    result: dict[str, object] = {
        "python": platform.python_version(),
        "torch": torch.__version__,
        "torch_cuda_build": torch.version.cuda,
        "cuda_available": cuda,
        "nvcc": shutil.which("nvcc"),
    }
    if cuda:
        props = torch.cuda.get_device_properties(0)
        result.update(
            gpu=props.name,
            compute_capability=f"{props.major}.{props.minor}",
            vram_gib=round(props.total_memory / 2**30, 2),
            bf16_supported=torch.cuda.is_bf16_supported(),
        )
    if shutil.which("nvidia-smi"):
        query = subprocess.run(
            ["nvidia-smi", "--query-gpu=driver_version,temperature.gpu", "--format=csv,noheader"],
            check=False, capture_output=True, text=True,
        )
        result["nvidia_smi"] = query.stdout.strip()
    return result


def main() -> None:
    print(json.dumps(collect(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
