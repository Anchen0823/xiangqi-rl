from __future__ import annotations

import argparse
import json
import queue
import re
import subprocess
import threading
import time
from pathlib import Path

import numpy as np
import torch

from .export_nnue import QuantizedNetwork
from .features import PositionFeatures, collate_model_inputs
from .model import XiangqiNnue

EVAL_PATTERN = re.compile(r"NNUE evaluation\s+([+-]?\d+)\s+\(side to move")


def trunc_div(numerator: int, denominator: int) -> int:
    """C++ signed integer division truncates toward zero."""
    quotient = abs(numerator) // abs(denominator)
    return -quotient if (numerator < 0) != (denominator < 0) else quotient


def clipped_linear(values: np.ndarray, shift: int) -> np.ndarray:
    return np.clip(values >> shift, 0, 127).astype(np.int32)


def clipped_square(values: np.ndarray, shift: int) -> np.ndarray:
    squared = (values.astype(np.int64) * values.astype(np.int64)) >> shift
    return np.clip(squared, 0, 127).astype(np.int32)


def transformed_accumulator(q: QuantizedNetwork, psq: tuple[int, ...], threats: tuple[int, ...]) -> np.ndarray:
    """Return the 512 u8 pairwise transform for one perspective."""
    acc = q.accumulator_bias.astype(np.int64).copy()
    if psq:
        acc += q.psq_features[np.asarray(psq, dtype=np.int64)].sum(axis=0, dtype=np.int64)
    if threats:
        acc += q.threat_features[np.asarray(threats, dtype=np.int64)].sum(axis=0, dtype=np.int64)
    left = np.clip(acc[:512], 0, 255)
    right = np.clip(acc[512:], 0, 255)
    return ((left * right) // 512).astype(np.int32)


def psqt_accumulation(q: QuantizedNetwork, psq: tuple[int, ...], threats: tuple[int, ...]) -> np.ndarray:
    acc = np.zeros(16, dtype=np.int64)
    if psq:
        acc += q.psq_psqt[np.asarray(psq, dtype=np.int64)].sum(axis=0, dtype=np.int64)
    if threats:
        acc += q.threat_psqt[np.asarray(threats, dtype=np.int64)].sum(axis=0, dtype=np.int64)
    return acc


def simulate_quantized_forward(q: QuantizedNetwork, features: PositionFeatures) -> int:
    """Integer-exact Python model of Pikafish's quantized NNUE evaluation.

    The returned integer is in Pikafish side-to-move internal units, matching
    the first value printed by the UCI ``eval`` command.
    """
    q.validate()
    stm = features.side_to_move
    opp = features.opponent
    transformed = np.concatenate(
        (
            transformed_accumulator(q, stm.psq, stm.threats),
            transformed_accumulator(q, opp.psq, opp.threats),
        )
    )
    layer_bucket = features.layer_bucket
    stack = q.stacks[layer_bucket]

    fc0 = stack.fc0_weight.astype(np.int64) @ transformed.astype(np.int64)
    fc0 += stack.fc0_bias.astype(np.int64)
    first = np.concatenate((clipped_square(fc0, 21), clipped_linear(fc0, 7)))

    fc1 = stack.fc1_weight.astype(np.int64) @ first.astype(np.int64)
    fc1 += stack.fc1_bias.astype(np.int64)
    second = np.concatenate((clipped_square(fc1, 19), clipped_linear(fc1, 6)))

    dense_input = np.concatenate((first, second))
    fwd_out = int(np.asarray(stack.fc2_weight.astype(np.int64) @ dense_input.astype(np.int64)).item())
    fwd_out += int(stack.fc2_bias[0])
    fwd_out += int(fc0[-2]) - int(fc0[-1])

    # NetworkArchitecture::propagate then Network::evaluate / OutputScale.
    positional = trunc_div(trunc_div(fwd_out * (600 * 16), 16_384), 16)

    stm_psqt = psqt_accumulation(q, stm.psq, stm.threats)
    opp_psqt = psqt_accumulation(q, opp.psq, opp.threats)
    materialist = trunc_div(int(stm_psqt[layer_bucket]) - int(opp_psqt[layer_bucket]), 2)
    psqt_internal = trunc_div(materialist, 16)
    return positional + psqt_internal


def float_forward_internal(
    model: XiangqiNnue, features: PositionFeatures, device: torch.device | str = "cpu"
) -> float:
    model.eval()
    inputs = collate_model_inputs([features], torch.device(device))
    with torch.no_grad():
        return float(model(*inputs).detach().cpu().item() * 600.0)


class PikafishEvalClient:
    """Minimal UCI client used only for the ``eval`` trace readback."""

    def __init__(self, engine: str | Path, network: str | Path, *, timeout: float = 30.0):
        if timeout <= 0:
            raise ValueError("timeout must be positive")
        engine_path = Path(engine)
        network_path = Path(network)
        if not engine_path.is_file():
            raise FileNotFoundError(f"Pikafish engine not found: {engine_path}")
        if not network_path.is_file():
            raise FileNotFoundError(f"NNUE network not found: {network_path}")
        self.timeout = timeout
        self._process = subprocess.Popen(
            [str(engine_path)],
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
        threading.Thread(target=self._read_output, daemon=True).start()
        self._send("uci")
        self._wait_for("uciok")
        self._send(f"setoption name EvalFile value {network_path}")
        self._send("isready")
        self._wait_for("readyok")

    def _read_output(self) -> None:
        assert self._process.stdout is not None
        try:
            for line in self._process.stdout:
                self._lines.put(line.rstrip("\r\n"))
        finally:
            self._lines.put(None)

    def _send(self, value: str) -> None:
        if self._process.poll() is not None:
            raise RuntimeError(f"Pikafish exited with code {self._process.returncode}")
        assert self._process.stdin is not None
        self._process.stdin.write(value + "\n")
        self._process.stdin.flush()

    def _next_line(self, deadline: float) -> str:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError("timed out waiting for Pikafish output")
        try:
            line = self._lines.get(timeout=remaining)
        except queue.Empty as error:
            raise TimeoutError("timed out waiting for Pikafish output") from error
        if line is None:
            raise RuntimeError(
                f"Pikafish exited while waiting for output (code {self._process.poll()})"
            )
        return line

    def _wait_for(self, expected: str) -> None:
        deadline = time.monotonic() + self.timeout
        while True:
            line = self._next_line(deadline)
            if line == expected:
                return
            if "ERROR" in line:
                raise RuntimeError(line)

    def eval_fen(self, fen: str) -> int:
        if "\n" in fen or "\r" in fen or not fen.strip():
            raise ValueError("FEN must be a non-empty single line")
        with self._lock:
            self._send("position fen " + fen)
            self._send("eval")
            deadline = time.monotonic() + self.timeout
            while True:
                line = self._next_line(deadline)
                match = EVAL_PATTERN.search(line)
                if match:
                    return int(match.group(1))

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

    def __enter__(self) -> PikafishEvalClient:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()


def compare_position(
    *,
    model: XiangqiNnue,
    quantized: QuantizedNetwork,
    features: PositionFeatures,
    fen: str,
    engine: PikafishEvalClient,
) -> dict[str, object]:
    quantized_internal = simulate_quantized_forward(quantized, features)
    engine_internal = engine.eval_fen(fen)
    float_internal = float_forward_internal(model, features)
    return {
        "fen": fen,
        "float_internal": float_internal,
        "quantized_internal": quantized_internal,
        "engine_internal": engine_internal,
        "float_minus_engine": float_internal - engine_internal,
        "quantized_minus_engine": quantized_internal - engine_internal,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Readback-verify an exported .nnue against Pikafish")
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--network", type=Path, required=True)
    parser.add_argument("--engine", type=Path, required=True)
    parser.add_argument("--fen", action="append", default=[])
    args = parser.parse_args()

    from .export_nnue import load_state_dict, quantize_state_dict
    from .features import PikafishFeatureClient

    state = load_state_dict(args.checkpoint)
    model = XiangqiNnue().eval()
    model.load_state_dict(state)
    quantized = quantize_state_dict(state)
    fens = list(args.fen)

    with PikafishFeatureClient(args.engine) as features_client, PikafishEvalClient(
        args.engine, args.network
    ) as engine:
        for fen in fens:
            features = features_client.fen(fen)
            print(json.dumps(compare_position(
                model=model, quantized=quantized, features=features, fen=fen, engine=engine
            )))


if __name__ == "__main__":
    main()
