from __future__ import annotations

from dataclasses import dataclass

import torch
from torch import Tensor, nn


@dataclass(frozen=True)
class NnueConfig:
    # Pikafish b97ef0f: HalfKAv2_hm::Dimensions and FullThreats::Dimensions.
    psq_feature_count: int = 6 * 4 * 689
    threat_feature_count: int = 45_547
    accumulator_size: int = 1024
    hidden1: int = 32
    hidden2: int = 32
    layer_stacks: int = 16


def clipped_relu(value: Tensor) -> Tensor:
    return torch.clamp(value, 0.0, 1.0)


def squared_clipped_relu(value: Tensor) -> Tensor:
    return clipped_relu(value).square()


class NnueLayerStack(nn.Module):
    """One Pikafish material-bucket network stack."""

    def __init__(self, config: NnueConfig) -> None:
        super().__init__()
        self.hidden1 = nn.Linear(config.accumulator_size, config.hidden1)
        self.hidden2 = nn.Linear(config.hidden1 * 2, config.hidden2)
        self.output = nn.Linear(config.hidden1 * 2 + config.hidden2 * 2, 1)

    def forward(self, transformed: Tensor) -> Tensor:
        first_raw = self.hidden1(transformed)
        first = torch.cat((squared_clipped_relu(first_raw), clipped_relu(first_raw)), dim=1)
        second_raw = self.hidden2(first)
        second = torch.cat((squared_clipped_relu(second_raw), clipped_relu(second_raw)), dim=1)
        dense = self.output(torch.cat((first, second), dim=1)).squeeze(1)
        # Pikafish adds the final two FC_0 channels as a fixed forward skip.
        return dense + first_raw[:, -2] - first_raw[:, -1]


class XiangqiNnue(nn.Module):
    """Trainable envelope matching Pikafish HalfKAv2_hm + FullThreats NNUE.

    Each perspective accumulates independent piece-square and threat feature
    bags into one shared 1024-wide accumulator. The two 512-wide halves are
    pair-multiplied before the side-to-move and opponent perspectives are
    concatenated. Sixteen material buckets own independent 1024->32->32->1
    dense stacks, while feature PSQT heads provide the bucketed residual.
    """

    def __init__(self, config: NnueConfig = NnueConfig()) -> None:
        super().__init__()
        if config.accumulator_size <= 0 or config.accumulator_size % 2:
            raise ValueError("accumulator_size must be a positive even number")
        if config.hidden1 < 2:
            raise ValueError("hidden1 must have at least two channels for the forward skip")
        self.config = config
        self.accumulator_bias = nn.Parameter(torch.zeros(config.accumulator_size))
        self.psq_features = nn.EmbeddingBag(
            config.psq_feature_count, config.accumulator_size, mode="sum", include_last_offset=True
        )
        self.threat_features = nn.EmbeddingBag(
            config.threat_feature_count,
            config.accumulator_size,
            mode="sum",
            include_last_offset=True,
        )
        self.psq_psqt = nn.EmbeddingBag(
            config.psq_feature_count, config.layer_stacks, mode="sum", include_last_offset=True
        )
        self.threat_psqt = nn.EmbeddingBag(
            config.threat_feature_count,
            config.layer_stacks,
            mode="sum",
            include_last_offset=True,
        )
        self.stacks = nn.ModuleList(NnueLayerStack(config) for _ in range(config.layer_stacks))
        self._reset_sparse_parameters()

    def _reset_sparse_parameters(self) -> None:
        for embedding in (
            self.psq_features,
            self.threat_features,
            self.psq_psqt,
            self.threat_psqt,
        ):
            nn.init.normal_(embedding.weight, mean=0.0, std=0.01)

    def _accumulate(
        self,
        psq_indices: Tensor,
        psq_offsets: Tensor,
        threat_indices: Tensor,
        threat_offsets: Tensor,
    ) -> Tensor:
        return (
            self.accumulator_bias
            + self.psq_features(psq_indices, psq_offsets)
            + self.threat_features(threat_indices, threat_offsets)
        )

    @staticmethod
    def _transform_perspective(accumulator: Tensor) -> Tensor:
        left, right = accumulator.chunk(2, dim=1)
        return clipped_relu(left) * clipped_relu(right)

    def _psqt(
        self,
        psq_indices: Tensor,
        psq_offsets: Tensor,
        threat_indices: Tensor,
        threat_offsets: Tensor,
    ) -> Tensor:
        return self.psq_psqt(psq_indices, psq_offsets) + self.threat_psqt(
            threat_indices, threat_offsets
        )

    def forward(
        self,
        stm_psq_indices: Tensor,
        stm_psq_offsets: Tensor,
        stm_threat_indices: Tensor,
        stm_threat_offsets: Tensor,
        opp_psq_indices: Tensor,
        opp_psq_offsets: Tensor,
        opp_threat_indices: Tensor,
        opp_threat_offsets: Tensor,
        layer_buckets: Tensor,
    ) -> Tensor:
        stm_accumulator = self._accumulate(
            stm_psq_indices, stm_psq_offsets, stm_threat_indices, stm_threat_offsets
        )
        opp_accumulator = self._accumulate(
            opp_psq_indices, opp_psq_offsets, opp_threat_indices, opp_threat_offsets
        )
        transformed = torch.cat(
            (
                self._transform_perspective(stm_accumulator),
                self._transform_perspective(opp_accumulator),
            ),
            dim=1,
        )

        if layer_buckets.ndim != 1 or layer_buckets.shape[0] != transformed.shape[0]:
            raise ValueError("layer_buckets must contain one bucket per position")
        if bool(((layer_buckets < 0) | (layer_buckets >= self.config.layer_stacks)).any()):
            raise ValueError("layer bucket is outside the configured range")

        dense: Tensor | None = None
        for bucket in torch.unique(layer_buckets).tolist():
            rows = torch.nonzero(layer_buckets == bucket, as_tuple=False).squeeze(1)
            bucket_output = self.stacks[bucket](transformed.index_select(0, rows))
            if dense is None:
                # Linear layers may be FP16/BF16 under autocast while sparse
                # EmbeddingBag accumulators intentionally remain FP32.
                dense = bucket_output.new_zeros(transformed.shape[0])
            dense = dense.index_copy(
                0, rows, bucket_output
            )
        if dense is None:
            raise ValueError("an NNUE batch must contain at least one position")

        stm_psqt = self._psqt(
            stm_psq_indices, stm_psq_offsets, stm_threat_indices, stm_threat_offsets
        )
        opp_psqt = self._psqt(
            opp_psq_indices, opp_psq_offsets, opp_threat_indices, opp_threat_offsets
        )
        selected_psqt = (stm_psqt - opp_psqt).gather(1, layer_buckets[:, None]).squeeze(1) / 2
        return dense + selected_psqt

    @torch.no_grad()
    def quantization_error(self, batches: tuple[Tensor, ...]) -> float:
        reference = self(*batches)
        state = self.state_dict()
        quantized = {
            name: torch.round(value * 127).clamp(-127, 127) / 127
            for name, value in state.items()
        }
        clone = XiangqiNnue(self.config).to(reference.device)
        clone.load_state_dict(quantized)
        return float((reference - clone(*batches)).abs().max().item())
