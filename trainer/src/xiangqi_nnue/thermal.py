from __future__ import annotations

import shutil
import subprocess
import time


def gpu_temperature() -> int | None:
    if not shutil.which("nvidia-smi"):
        return None
    result = subprocess.run(
        ["nvidia-smi", "--query-gpu=temperature.gpu", "--format=csv,noheader,nounits"],
        check=False, capture_output=True, text=True,
    )
    try:
        return int(result.stdout.splitlines()[0].strip())
    except (IndexError, ValueError):
        return None


def wait_for_safe_temperature(pause_at: int = 83, resume_at: int = 78) -> bool:
    temperature = gpu_temperature()
    if temperature is None or temperature < pause_at:
        return False
    print({"event": "thermal_pause", "temperature_c": temperature}, flush=True)
    while temperature is not None and temperature > resume_at:
        time.sleep(15)
        temperature = gpu_temperature()
    print({"event": "thermal_resume", "temperature_c": temperature}, flush=True)
    return True
