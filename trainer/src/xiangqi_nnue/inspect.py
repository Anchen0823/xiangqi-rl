from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

from .dataset import read_records
from .rules import NativeRulesClient, RulesProtocolError


def _distribution(values: list[float]) -> dict[str, float]:
    if not values:
        return {"count": 0}
    ordered = sorted(values)
    count = len(ordered)
    mean = sum(ordered) / count
    variance = sum((value - mean) ** 2 for value in ordered) / count
    def quantile(ratio: float) -> float:
        return ordered[min(count - 1, int(ratio * count))]
    return {
        "count": count,
        "min": ordered[0],
        "max": ordered[-1],
        "mean": mean,
        "stddev": math.sqrt(variance),
        "p5": quantile(0.05),
        "p25": quantile(0.25),
        "p50": quantile(0.50),
        "p75": quantile(0.75),
        "p95": quantile(0.95),
    }


def inspect_dataset(directory: Path, *, max_records: int | None = None,
                    legality_sample: int = 0, rules_command: str | Path | None = None) -> dict:
    """Compute dataset quality statistics for the phase-3 quality gate.

    Reports record count, score/outcome distributions, duplicate-FEN ratio,
    teacher-node distribution, and (optionally) a legality spot-check of
    ``bestmove`` fields against the native rules referee.
    """
    directory = Path(directory)
    manifest_path = directory / "manifest.json"
    if not manifest_path.is_file():
        raise FileNotFoundError(f"dataset manifest missing: {manifest_path}")

    scores: list[float] = []
    outcomes: dict[str, int] = {"none": 0, "red": 0, "black": 0, "draw": 0}
    teacher_nodes: list[float] = []
    fens: dict[str, int] = {}
    bestmoves: list[tuple[str, str, int]] = []  # (fen, move, ply) for sampling
    total = 0
    for record in read_records(directory):
        total += 1
        scores.append(float(record.score_cp))
        if record.outcome is None:
            outcomes["none"] += 1
        elif record.outcome > 0.5:
            outcomes["red"] += 1
        elif record.outcome < -0.5:
            outcomes["black"] += 1
        else:
            outcomes["draw"] += 1
        teacher_nodes.append(float(record.teacher_nodes))
        fens[record.fen] = fens.get(record.fen, 0) + 1
        if record.bestmove and (len(bestmoves) < legality_sample or legality_sample <= 0):
            bestmoves.append((record.fen, record.bestmove, record.ply))
        if max_records is not None and total >= max_records:
            break

    duplicate_records = sum(count - 1 for count in fens.values() if count > 1)
    report: dict = {
        "dataset": str(directory),
        "manifest_records": json.loads(manifest_path.read_text(encoding="utf-8")).get(
            "totalRecords", 0
        ),
        "inspected_records": total,
        "score_cp": _distribution(scores),
        "outcomes": outcomes,
        "duplicate_fen_records": duplicate_records,
        "duplicate_fen_ratio": duplicate_records / total if total else 0.0,
        "unique_fens": len(fens),
        "teacher_nodes": _distribution(teacher_nodes),
    }

    if legality_sample > 0:
        if rules_command is None:
            raise ValueError("legality spot-check requires --rules-engine")
        sample = bestmoves[: legality_sample]
        checked = legal = 0
        with NativeRulesClient(rules_command, timeout=20) as rules:
            for fen, move, ply in sample:
                checked += 1
                try:
                    rules.load_fen(fen)
                    rules.play_move(move)
                    legal += 1
                except (RulesProtocolError, ValueError):
                    report.setdefault("illegal_samples", []).append(
                        {"fen": fen, "move": move, "ply": ply}
                    )
        report["legality_checked"] = checked
        report["legality_legal"] = legal
        report["legality_ratio"] = legal / checked if checked else 0.0
        report["legality_sample_requested"] = legality_sample
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Dataset quality statistics")
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--max-records", type=int, default=None)
    parser.add_argument("--legality-sample", type=int, default=0,
                        help="spot-check this many bestmoves against the rules referee")
    parser.add_argument("--rules-engine", type=Path, default=None)
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()

    report = inspect_dataset(
        args.dataset,
        max_records=args.max_records,
        legality_sample=args.legality_sample,
        rules_command=args.rules_engine,
    )
    payload = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload, encoding="utf-8")
    print(payload)


if __name__ == "__main__":
    main()
