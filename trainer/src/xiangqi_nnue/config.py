from __future__ import annotations

import math
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .model import NnueConfig

DEFAULT_CONFIG = Path(__file__).resolve().parents[2] / "config" / "train.toml"


def _require_number(data: dict[str, Any], key: str, minimum: float, default: float) -> float:
    value = data.get(key, default)
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value < minimum:
        raise ValueError(f"training.{key} must be a number >= {minimum}")
    return float(value)


def _require_int(data: dict[str, Any], key: str, minimum: int, default: int) -> int:
    value = data.get(key, default)
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ValueError(f"training.{key} must be an integer >= {minimum}")
    return value


@dataclass(frozen=True)
class TrainingConfig:
    seed: int = 823
    batch_size: int = 8192
    micro_batch_size: int = 1024
    learning_rate: float = 0.001
    weight_decay: float = 0.00001
    warmup_steps: int = 500
    checkpoint_seconds: float = 1800.0
    memory_soft_limit_gib: float = 6.5
    system_memory_limit_gib: float = 12.0
    temperature_pause_c: int = 83
    temperature_resume_c: int = 78
    max_epochs: int = 10
    val_interval_epochs: float = 0.5
    early_stop_patience_epochs: float = 2.0
    model: NnueConfig = field(default_factory=NnueConfig)

    @property
    def accumulate(self) -> int:
        if self.batch_size % self.micro_batch_size:
            raise ValueError("batch_size must be a multiple of micro_batch_size")
        return self.batch_size // self.micro_batch_size

    @classmethod
    def from_toml(cls, path: str | Path) -> TrainingConfig:
        """Load and validate the config consumed by ``train.py``.

        ``train.toml`` is the single source of truth for hyperparameters: seed,
        batch sizes, learning rate, weight decay, warmup, temperature gates,
        memory limits, max epochs, validation interval and early stopping.
        """
        source = tomllib.loads(Path(path).read_text(encoding="utf-8"))
        training = source.get("training")
        if not isinstance(training, dict):
            raise ValueError("train.toml must contain a [training] table")
        model_data = source.get("model") or {}
        if not isinstance(model_data, dict):
            raise ValueError("train.toml [model] must be a table")

        model = NnueConfig(
            psq_feature_count=_require_int(
                model_data, "psq_feature_count", 1, NnueConfig.psq_feature_count
            ),
            threat_feature_count=_require_int(
                model_data, "threat_feature_count", 1, NnueConfig.threat_feature_count
            ),
            accumulator_size=_require_int(
                model_data, "accumulator_size", 2, NnueConfig.accumulator_size
            ),
            hidden1=_require_int(model_data, "hidden1", 2, NnueConfig.hidden1),
            hidden2=_require_int(model_data, "hidden2", 1, NnueConfig.hidden2),
            layer_stacks=_require_int(model_data, "layer_stacks", 1, NnueConfig.layer_stacks),
        )
        if model.accumulator_size % 2:
            raise ValueError("model.accumulator_size must be even")

        pause = _require_int(training, "temperature_pause_c", 0, 83)
        resume = _require_int(training, "temperature_resume_c", 0, 78)
        if resume >= pause:
            raise ValueError("temperature_resume_c must be below temperature_pause_c")
        val_interval = _require_number(training, "val_interval_epochs", 0.05, 0.5)
        patience = _require_number(training, "early_stop_patience_epochs", 0.0, 2.0)
        if patience <= 0:
            raise ValueError("early_stop_patience_epochs must be positive")

        return cls(
            seed=_require_int(training, "seed", 0, 823),
            batch_size=_require_int(training, "batch_size", 1, 8192),
            micro_batch_size=_require_int(training, "micro_batch_size", 1, 1024),
            learning_rate=_require_number(training, "learning_rate", 0.0, 0.001),
            weight_decay=_require_number(training, "weight_decay", 0.0, 0.00001),
            warmup_steps=_require_int(training, "warmup_steps", 0, 500),
            checkpoint_seconds=_require_number(training, "checkpoint_seconds", 1.0, 1800.0),
            memory_soft_limit_gib=_require_number(training, "memory_soft_limit_gib", 0.1, 6.5),
            system_memory_limit_gib=_require_number(training, "system_memory_limit_gib", 0.1, 12.0),
            temperature_pause_c=pause,
            temperature_resume_c=resume,
            max_epochs=_require_int(training, "max_epochs", 1, 10),
            val_interval_epochs=val_interval,
            early_stop_patience_epochs=patience,
            model=model,
        )


def cosine_warmup_lr(step: int, warmup_steps: int, max_steps: int, base_lr: float) -> float:
    """Linear warmup then cosine decay to zero; 0 for empty or exhausted schedules."""
    if base_lr <= 0 or max_steps <= 0:
        return base_lr
    if step < warmup_steps:
        return base_lr * (step + 1) / max(warmup_steps, 1)
    progress = min(1.0, max(0.0, (step - warmup_steps) / max(1, max_steps - warmup_steps)))
    return base_lr * 0.5 * (1.0 + math.cos(math.pi * progress))
