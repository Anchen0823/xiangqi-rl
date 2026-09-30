"""Build the expanded 20260930 training set with leakage-safe splits.

Run from the repository root:

    .\\.venv\\Scripts\\python.exe -m xiangqi_nnue.split ...

This script is a thin, explicit driver over the existing dataset primitives. It
keeps the 2026-09-30 holdouts untouched and out of the new training partition:

* the previous candidate was already fitted on the ``trial-split`` train
  partition, so those board positions are removed from the new train set;
* the previous ``trial-continue-20260930`` val/test positions are removed
  everywhere, so they stay usable as a like-for-like regression holdout;
* a fresh game-separated split of the remaining selfplay-v1 games supplies the
  new train/val/holdout partitions.
"""
from __future__ import annotations

import json
from pathlib import Path

from xiangqi_nnue.dataset import DatasetProvenance, DatasetShardWriter, TrainingRecord, read_records
from xiangqi_nnue.split import source_game_sizes

V1 = Path("datasets/selfplay-v1")
LABELED = Path("datasets/v1-labeled")
OUT = Path("datasets/v1-split-20260930")
OLD_TRAIN = Path("datasets/trial-split/train")
OLD_VAL = Path("datasets/trial-continue-20260930/val")
OLD_TEST = Path("datasets/trial-continue-20260930/test")
REPORT = Path("reports/training-20260930b")

TRAIN_RATIO = 0.94
VAL_RATIO = 0.03


def position_key(fen: str) -> str:
    """Board plus side to move, so counters and repetition fields cannot leak."""
    fields = fen.split(" ")
    return " ".join(fields[:2])


def game_of_record(sizes: list[int]) -> list[int]:
    """Map every record index in the labeled stream onto its source game."""
    owners: list[int] = []
    for game_index, size in enumerate(sizes):
        owners.extend([game_index] * size)
    return owners


def main() -> None:
    sizes = source_game_sizes(V1)
    labeled_manifest = json.loads((LABELED / "manifest.json").read_text(encoding="utf-8"))
    payload = labeled_manifest["provenance"]
    provenance = DatasetProvenance(
        source_url=payload["source_url"],
        source_sha256=payload["source_sha256"],
        attribution=payload["attribution"],
        teacher_name=payload["teacher_name"],
        teacher_url=payload["teacher_url"],
        teacher_sha256=payload["teacher_sha256"],
        game_data_license=payload.get("game_data_license", "ODbL-1.0"),
        teacher_license=payload.get("teacher_license", "CC0-1.0"),
    )

    old_train_keys = {position_key(record.fen) for record in read_records(OLD_TRAIN)}
    holdout_keys = {position_key(record.fen) for record in read_records(OLD_VAL)}
    holdout_keys |= {position_key(record.fen) for record in read_records(OLD_TEST)}
    excluded = old_train_keys | holdout_keys

    owners = game_of_record(sizes)
    records = list(read_records(LABELED))
    if len(records) != len(owners):
        raise ValueError(f"labeled stream has {len(records)} records, source has {len(owners)}")

    # Keep every game whose records are not dominated by excluded positions so
    # the split stays game-separated, then drop the excluded positions.
    game_hits: dict[int, int] = {}
    kept: list[tuple[int, TrainingRecord]] = []
    for index, record in enumerate(records):
        game_index = owners[index]
        if position_key(record.fen) in excluded:
            game_hits[game_index] = game_hits.get(game_index, 0) + 1
            continue
        kept.append((game_index, record))

    eligible_games = sorted({game for game, _ in kept})
    import random

    rng = random.Random(20260930)
    order = list(eligible_games)
    rng.shuffle(order)
    train_games = max(1, int(len(order) * TRAIN_RATIO))
    val_games = max(1, int(len(order) * VAL_RATIO))
    assignment: dict[int, str] = {}
    for rank, game_index in enumerate(order):
        if rank < train_games:
            assignment[game_index] = "train"
        elif rank < train_games + val_games:
            assignment[game_index] = "val"
        else:
            assignment[game_index] = "holdout"

    buckets: dict[str, list[TrainingRecord]] = {"train": [], "val": [], "holdout": []}
    seen: dict[str, set[str]] = {"train": set(), "val": set(), "holdout": set()}
    for game_index, record in kept:
        split = assignment[game_index]
        key = position_key(record.fen)
        if key in seen[split] or key in seen_global(buckets, seen, split):
            continue
        buckets[split].append(record)
        seen[split].add(key)

    counts = {split: len(items) for split, items in buckets.items()}
    leakage = {
        split: len({position_key(item.fen) for item in items} & holdout_keys)
        for split, items in buckets.items()
    }
    train_overlap = len({position_key(item.fen) for item in buckets["train"]} & old_train_keys)

    OUT.mkdir(parents=True, exist_ok=True)
    for split, items in buckets.items():
        directory = OUT / split
        with DatasetShardWriter(directory, f"{split}-v1", provenance,
                                records_per_shard=50_000) as writer:
            for record in items:
                writer.write(record)
        print(json.dumps({"split": split, "records": len(items), "directory": str(directory)}),
              flush=True)

    REPORT.mkdir(parents=True, exist_ok=True)
    (REPORT / "data-preflight.json").write_text(json.dumps({
        "labeled_source": str(LABELED),
        "labeled_records": len(records),
        "source_games": len(sizes),
        "games_with_excluded_positions": len(game_hits),
        "excluded_position_keys": len(excluded),
        "old_training_keys": len(old_train_keys),
        "old_holdout_keys": len(holdout_keys),
        "counts": counts,
        "old_holdout_leakage": leakage,
        "train_overlap_with_old_training": train_overlap,
        "game_assignment": {split: sum(1 for value in assignment.values() if value == split)
                            for split in ("train", "val", "holdout")},
    }, indent=2), encoding="utf-8")
    print(json.dumps({"counts": counts, "leakage": leakage,
                      "train_overlap_with_old_training": train_overlap}), flush=True)
    if any(leakage.values()) or train_overlap:
        raise SystemExit("holdout leakage detected")


def seen_global(buckets, seen, split) -> set[str]:
    """Keys already used by any other split, keeping partitions disjoint."""
    keys: set[str] = set()
    for other, values in seen.items():
        if other != split:
            keys |= values
    return keys


if __name__ == "__main__":
    main()
