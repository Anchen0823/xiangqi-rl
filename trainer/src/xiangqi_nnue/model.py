from __future__ import annotations

from dataclasses import dataclass

import torch
from torch import Tensor, nn


@dataclass(frozen=True)
class NnueConfig:
    feature_count: int = 131_072
    accumulator_size: int = 1024
    hidden1: int = 32
    hidden2: int = 32


def squared_clipped_relu(value: Tensor) -> Tensor:
    return torch.clamp(value, 0.0, 1.0).square()


class XiangqiNnue(nn.Module):
    """Dual-perspective HalfKAv2_hm + FullThreats compatible NNUE envelope.

    The encoder owns the exact feature numbering. Each position supplies two
    sparse feature bags (side-to-move and opponent perspective). The dense tail
    is deliberately small so it can be exported to int8/int16 CPU inference.
    """

    def __init__(self, config: NnueConfig = NnueConfig()) -> None:
        super().__init__()
        self.config = config
        self.features = nn.EmbeddingBag(
            config.feature_count, config.accumulator_size, mode="sum", include_last_offset=True
        )
        self.hidden1 = nn.Linear(config.accumulator_size * 2, config.hidden1)
        self.hidden2 = nn.Linear(config.hidden1 * 2, config.hidden2)
        self.output = nn.Linear(config.hidden2 * 2, 1)

    def forward(
        self,
        stm_indices: Tensor,
        stm_offsets: Tensor,
        opp_indices: Tensor,
        opp_offsets: Tensor,
    ) -> Tensor:
        stm = torch.clamp(self.features(stm_indices, stm_offsets), 0.0, 1.0)
        opp = torch.clamp(self.features(opp_indices, opp_offsets), 0.0, 1.0)
        x = self.hidden1(torch.cat((stm, opp), dim=1))
        x = torch.cat((torch.clamp(x, 0.0, 1.0), squared_clipped_relu(x)), dim=1)
        x = self.hidden2(x)
        x = torch.cat((torch.clamp(x, 0.0, 1.0), squared_clipped_relu(x)), dim=1)
        return self.output(x).squeeze(1)

    @torch.no_grad()
    def quantization_error(self, batches: tuple[Tensor, Tensor, Tensor, Tensor]) -> float:
        reference = self(*batches)
        state = self.state_dict()
        quantized = {name: torch.round(value * 127).clamp(-127, 127) / 127 for name, value in state.items()}
        clone = XiangqiNnue(self.config).to(reference.device)
        clone.load_state_dict(quantized)
        return float((reference - clone(*batches)).abs().max().item())
