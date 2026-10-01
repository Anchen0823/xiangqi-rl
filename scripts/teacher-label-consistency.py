"""Measure how much the teacher's own evaluation depends on its search budget.

Run from the repository root:

    .\\.venv\\Scripts\\python.exe -m scripts.teacher-label-consistency --positions 400

Why this exists: the training loss stops falling long before the corpus is
exhausted, and the two candidate explanations are a model that has run out of
capacity and labels that carry their own noise. This measures the second one
directly. If the teacher's score for the same position moves materially between
5000 and 20000 nodes, then 5000-node labels are noisy, the model is already
being asked to fit that noise, and widening the network cannot help.

Scores are stored as the teacher reports them (side to move, no sign flip), so
the two runs are compared directly. A sign flip is reported separately: it means
the teacher is unsure who is better, which is the label noise that hurts most.
"""

from __future__ import annotations

import argparse
import json
import statistics
from pathlib import Path

from xiangqi_nnue.dataset import read_records
from xiangqi_nnue.teacher import FairyStockfishTeacher

# Mate scores are encoded near +-MATE_SCORE rather than as centipawns, so mixing
# them into a centipawn statistic is meaningless: a single missed mate swamps
# the mean. Mate agreement is therefore counted separately.
MATE_THRESHOLD = 30_000


def pearson(left: list[float], right: list[float]) -> float:
    if len(left) < 2:
        return float("nan")
    mean_left = statistics.fmean(left)
    mean_right = statistics.fmean(right)
    numerator = sum((a - mean_left) * (b - mean_right) for a, b in zip(left, right))
    denominator = (
        sum((a - mean_left) ** 2 for a in left) ** 0.5
        * sum((b - mean_right) ** 2 for b in right) ** 0.5
    )
    return numerator / denominator if denominator else float("nan")


def quantile(values: list[float], fraction: float) -> float:
    if not values:
        return float("nan")
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, int(round(fraction * (len(ordered) - 1)))))
    return ordered[index]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=Path("datasets/accumulated/test"),
                        help="labeled dataset to sample positions from")
    parser.add_argument("--teacher-engine", type=Path,
                        default=Path("native/bin/fairy-stockfish-teacher.exe"))
    parser.add_argument("--positions", type=int, default=400)
    parser.add_argument("--stride", type=int, default=0,
                        help="take every Nth record; 0 derives a stride evenly covering the set")
    parser.add_argument("--cheap-nodes", type=int, default=5000,
                        help="the budget the training labels were produced with")
    parser.add_argument("--rich-nodes", type=int, default=20000)
    parser.add_argument("--threads", type=int, default=4)
    parser.add_argument("--hash-mb", type=int, default=128)
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()

    if args.positions <= 0:
        raise ValueError("positions must be positive")
    if args.cheap_nodes <= 0 or args.rich_nodes <= args.cheap_nodes:
        raise ValueError("rich-nodes must exceed cheap-nodes, both positive")

    fen_list = []
    total_records = int(
        json.loads((args.dataset / "manifest.json").read_text(encoding="utf-8"))["totalRecords"]
    )
    # Spread the sample across the whole partition, but stream: read_records
    # decodes feature payloads, so materialising a large multiple of the sample
    # would cost memory for nothing.
    step = args.stride or max(1, total_records // args.positions)
    for index, record in enumerate(read_records(args.dataset)):
        if index % step == 0:
            fen_list.append(record.fen)
        if len(fen_list) >= args.positions:
            break
    if not fen_list:
        raise ValueError(f"no records read from {args.dataset}")

    print(json.dumps({"event": "sampled", "positions": len(fen_list), "stride": step,
                      "datasetRecords": total_records, "dataset": str(args.dataset)}),
          flush=True)

    deltas: list[float] = []
    cheap_scores: list[float] = []
    rich_scores: list[float] = []
    flips = 0
    bestmove_changes = 0
    mate_disagreements = 0
    mate_agreements = 0
    mate_only_cheap = 0
    mate_only_rich = 0
    both_mate = 0

    with FairyStockfishTeacher(args.teacher_engine, threads=args.threads,
                              hash_mb=args.hash_mb) as teacher:
        for index, fen in enumerate(fen_list):
            cheap = teacher.evaluate_fen(fen, args.cheap_nodes)
            rich = teacher.evaluate_fen(fen, args.rich_nodes)
            cheap_mate = cheap.mate_ply is not None or abs(cheap.score_cp) >= MATE_THRESHOLD
            rich_mate = rich.mate_ply is not None or abs(rich.score_cp) >= MATE_THRESHOLD
            if cheap_mate and rich_mate:
                both_mate += 1
                if cheap.score_cp == rich.score_cp:
                    mate_agreements += 1
                else:
                    mate_disagreements += 1
            elif cheap_mate:
                mate_only_cheap += 1
                mate_disagreements += 1
            elif rich_mate:
                mate_only_rich += 1
                mate_disagreements += 1
            else:
                # Only non-mate evaluations are comparable as centipawns.
                deltas.append(abs(rich.score_cp - cheap.score_cp))
                cheap_scores.append(cheap.score_cp)
                rich_scores.append(rich.score_cp)
                if (cheap.score_cp > 0) != (rich.score_cp > 0):
                    flips += 1
            if cheap.bestmove != rich.bestmove:
                bestmove_changes += 1
            if (index + 1) % 50 == 0:
                mean = statistics.fmean(deltas) if deltas else float("nan")
                print(json.dumps({"event": "progress", "done": index + 1,
                                  "centipawnPositions": len(deltas),
                                  "mean_abs_delta_cp": round(mean, 1)}), flush=True)

    total = len(fen_list)
    comparable = len(deltas)
    report = {
        "dataset": str(args.dataset),
        "positions": total,
        "cheapNodes": args.cheap_nodes,
        "richNodes": args.rich_nodes,
        # Centipawn statistics exclude mate evaluations; see MATE_THRESHOLD.
        "centipawnPositions": comparable,
        "meanAbsDeltaCp": statistics.fmean(deltas) if deltas else float("nan"),
        "medianAbsDeltaCp": statistics.median(deltas) if deltas else float("nan"),
        "p90AbsDeltaCp": quantile(deltas, 0.90),
        "p99AbsDeltaCp": quantile(deltas, 0.99),
        "maxAbsDeltaCp": max(deltas) if deltas else float("nan"),
        "pearson": pearson(cheap_scores, rich_scores),
        # Fraction of comparable positions where more search changes the verdict
        # of "which side is better"; this is the noise a model can only memorise.
        "signFlipRate": flips / comparable if comparable else float("nan"),
        "bestmoveChangeRate": bestmove_changes / total,
        "matePositionsCheap": mate_only_cheap + both_mate,
        "matePositionsRich": mate_only_rich + both_mate,
        "mateAgreements": mate_agreements,
        "mateDisagreements": mate_disagreements,
        "mateDisagreementRate": mate_disagreements / total,
        "meanRichMinusCheapCp": (
            statistics.fmean([r - c for r, c in zip(rich_scores, cheap_scores)])
            if deltas else float("nan")
        ),
    }
    target = args.output or Path("reports") / "teacher-label-consistency.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2), flush=True)
    print(f"report: {target}", flush=True)


if __name__ == "__main__":
    main()
