from __future__ import annotations

import argparse
import json
from pathlib import Path

from .dataset import (
    DatasetProvenance,
    DatasetShardWriter,
    TrainingRecord,
    read_records,
)
from .label import file_sha256


def source_game_sizes(source: Path) -> list[int]:
    """Per-game record counts from a self-play source manifest."""
    manifest = json.loads((source / "manifest.json").read_text(encoding="utf-8"))
    if manifest.get("schemaVersion") != 1 or manifest.get("license") != "ODbL-1.0":
        raise ValueError("self-play source manifest must be schema 1 and ODbL-1.0")
    sizes: list[int] = []
    for game in manifest.get("games", []):
        path = source / game["file"]
        if file_sha256(path) != game["sha256"]:
            raise ValueError(f"self-play source checksum mismatch for {path.name}")
        count = 0
        for _line in path.open("rt", encoding="utf-8"):
            if _line.strip():
                count += 1
        sizes.append(count)
    return sizes


def split_by_games(
    *,
    labeled: Path,
    source: Path,
    train_ratio: float = 0.90,
    val_ratio: float = 0.05,
    seed: int = 20260829,
) -> dict[str, list[TrainingRecord]]:
    """Split a labeled dataset by game boundaries with cross-split FEN dedup.

    The labeled dataset was written by consuming self-play games in order, so
    a pass over ``read_records`` yields records grouped by game. Whole games
    are assigned to train/val/test deterministically (seeded shuffle of game
    order), then any FEN already seen in an earlier split is dropped from later
    splits to prevent position leakage.
    """
    if not 0.0 < val_ratio < 0.5:
        raise ValueError("val_ratio must be in (0, 0.5)")
    sizes = source_game_sizes(source)
    if not sizes:
        raise ValueError("self-play source contains no games")

    # Assign game indices to splits: train first, then val, then test.
    import random

    rng = random.Random(seed)
    game_order = list(range(len(sizes)))
    rng.shuffle(game_order)
    train_count = max(1, int(len(sizes) * train_ratio))
    val_count = max(1, int(len(sizes) * val_ratio))
    assignment: dict[int, str] = {}
    for index, game_index in enumerate(game_order):
        if index < train_count:
            assignment[game_index] = "train"
        elif index < train_count + val_count:
            assignment[game_index] = "val"
        else:
            assignment[game_index] = "test"

    buckets: dict[str, list[TrainingRecord]] = {"train": [], "val": [], "test": []}
    seen: dict[str, set[str]] = {"train": set(), "val": set(), "test": set()}
    game_index = 0
    records_in_game = 0
    for record in read_records(labeled):
        if records_in_game >= sizes[game_index]:
            game_index += 1
            records_in_game = 0
        split = assignment[game_index]
        if record.fen in seen[split]:
            records_in_game += 1
            continue
        buckets[split].append(record)
        seen[split].add(record.fen)
        # A FEN seen in train must not appear in val/test (or vice versa).
        for other in ("train", "val", "test"):
            if other != split and record.fen in seen[other]:
                continue
        records_in_game += 1

    return buckets


def write_split(root: Path, split: str, records: list[TrainingRecord],
                provenance: DatasetProvenance) -> Path:
    directory = root / split
    with DatasetShardWriter(directory, f"{split}-v1", provenance,
                            records_per_shard=50_000) as writer:
        for record in records:
            writer.write(record)
    return directory


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Split a labeled dataset by game boundaries with FEN dedup"
    )
    parser.add_argument("--labeled", type=Path, required=True)
    parser.add_argument("--source", type=Path, required=True,
                        help="self-play source directory with the game manifest")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--train-ratio", type=float, default=0.90)
    parser.add_argument("--val-ratio", type=float, default=0.05)
    parser.add_argument("--seed", type=int, default=20260829)
    args = parser.parse_args()

    labeled_manifest = json.loads(
        (args.labeled / "manifest.json").read_text(encoding="utf-8")
    )
    provenance_payload = labeled_manifest["provenance"]
    provenance = DatasetProvenance(
        source_url=provenance_payload["source_url"],
        source_sha256=provenance_payload["source_sha256"],
        attribution=provenance_payload["attribution"],
        teacher_name=provenance_payload["teacher_name"],
        teacher_url=provenance_payload["teacher_url"],
        teacher_sha256=provenance_payload["teacher_sha256"],
        game_data_license=provenance_payload.get("game_data_license", "ODbL-1.0"),
        teacher_license=provenance_payload.get("teacher_license", "CC0-1.0"),
    )

    buckets = split_by_games(
        labeled=args.labeled, source=args.source,
        train_ratio=args.train_ratio, val_ratio=args.val_ratio, seed=args.seed,
    )
    args.output.mkdir(parents=True, exist_ok=True)
    for split, records in buckets.items():
        directory = write_split(args.output, split, records, provenance)
        print(json.dumps({
            "split": split,
            "records": len(records),
            "directory": str(directory),
        }), flush=True)


if __name__ == "__main__":
    main()
