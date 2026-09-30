"""Build an accumulated training set by appending fresh games to an existing corpus.

Run from the repository root, driven by scripts/train-night.ps1:

    .\\.venv\\Scripts\\python.exe -m scripts.prepare-accumulated-split ...

Why this exists instead of re-splitting everything with a new seed: the
warm-start checkpoint has already been fitted on the previous training
partition. Re-running the split script with a different seed would hand some of
those exact positions to validation, so early stop and best-checkpoint selection
would be scored on data the model has memorised. Position keys are therefore
partitioned by provenance, not by chance:

* the base training partition stays training, forever;
* the base val/test partitions and the older trial holdouts stay validation
  references, never trained on;
* only games generated tonight may enter the new val/test, so every partition
  the run is judged on is data the model has never seen.

The self-play corpora are concatenated game by game, so ownership is derived
from each source manifest rather than from record order alone. Positions are
deduplicated by board plus side to move (move counters cannot disguise a
repeat), and any position already present in a frozen holdout is dropped from
this run's training data rather than duplicated.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from xiangqi_nnue.dataset import (
    DatasetProvenance,
    DatasetShardWriter,
    read_records,
)
from xiangqi_nnue.split import position_key, source_game_sizes


def default_library() -> Path:
    return Path("datasets/accumulated")


def load_provenance(directory: Path) -> DatasetProvenance:
    manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    payload = manifest["provenance"]
    return DatasetProvenance(
        source_url=payload["source_url"],
        source_sha256=payload["source_sha256"],
        attribution=payload["attribution"],
        teacher_name=payload["teacher_name"],
        teacher_url=payload["teacher_url"],
        teacher_sha256=payload["teacher_sha256"],
        game_data_license=payload.get("game_data_license", "ODbL-1.0"),
        teacher_license=payload.get("teacher_license", "CC0-1.0"),
    )


def records_in(directory: Path) -> int:
    return int(json.loads((directory / "manifest.json").read_text(encoding="utf-8"))["totalRecords"])


def read_holdout_keys(directories: list[Path]) -> dict[str, set[str]]:
    keys: dict[str, set[str]] = {}
    for directory in directories:
        if not (directory / "manifest.json").is_file():
            continue
        keys[str(directory)] = {position_key(record.fen) for record in read_records(directory)}
    return keys


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-labeled", type=Path, required=True,
                        help="existing labeled corpus that becomes the training foundation")
    parser.add_argument("--new-labeled", type=Path, required=True,
                        help="tonight's labeled corpus")
    parser.add_argument("--new-source", type=Path, required=True,
                        help="tonight's self-play source, for game boundaries")
    parser.add_argument("--holdout", type=Path, action="append", default=[],
                        help="frozen evaluation partition; may be repeated")
    parser.add_argument("--output", type=Path, default=None,
                        help="accumulated library root (default datasets/accumulated)")
    parser.add_argument("--train-output", type=Path)
    parser.add_argument("--val-output", type=Path)
    parser.add_argument("--test-output", type=Path)
    parser.add_argument("--holdout-output", type=Path)
    parser.add_argument("--val-ratio", type=float, default=0.12,
                        help="share of tonight's games reserved for validation")
    parser.add_argument("--test-ratio", type=float, default=0.04,
                        help="share of tonight's games reserved for the test partition")
    parser.add_argument("--seed", type=int, default=20261001)
    parser.add_argument("--dataset-tag", default="accum")
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()

    library = (args.output or default_library()).resolve()
    train_out = args.train_output or (library / "train")
    val_out = args.val_output or (library / "val")
    test_out = args.test_output or (library / "test")
    holdout_out = args.holdout_output or (library / "holdout-reference")

    if records_in(args.base_labeled) <= 0:
        raise ValueError(f"base corpus {args.base_labeled} is empty")
    new_records = records_in(args.new_labeled)
    if new_records <= 0:
        raise ValueError(f"new corpus {args.new_labeled} is empty")

    provenance = load_provenance(args.new_labeled)

    # Frozen holdouts are read first: their positions must be removed from the
    # training stream, so they are needed before that stream is written.
    holdouts = read_holdout_keys([path for path in args.holdout if path])
    frozen = {key for keys in holdouts.values() for key in keys}

    # Tonight's games are assigned by whole game so a game can never straddle
    # two partitions and leak its own positions across the boundary.
    sizes = source_game_sizes(args.new_source)
    if sum(sizes) != new_records:
        raise ValueError(
            f"new source describes {sum(sizes)} records but the labeled corpus has {new_records}"
        )
    import random

    rng = random.Random(args.seed)
    order = list(range(len(sizes)))
    rng.shuffle(order)
    test_games = max(1, int(len(order) * args.test_ratio))
    val_games = max(1, int(len(order) * args.val_ratio))
    assignment: dict[int, str] = {}
    for rank, game_index in enumerate(order):
        if rank < test_games:
            assignment[game_index] = "test"
        elif rank < test_games + val_games:
            assignment[game_index] = "val"
        else:
            assignment[game_index] = "train"

    counts = {"train": 0, "val": 0, "test": 0, "holdout": 0, "dropped_frozen": 0, "dropped_duplicate": 0}
    seen: dict[str, set[str]] = {"train": set(), "val": set(), "test": set()}

    def emit(writer: DatasetShardWriter, split: str, record) -> None:
        key = position_key(record.fen)
        if key in seen[split]:
            counts["dropped_duplicate"] += 1
            return
        for other, keys in seen.items():
            if other != split and key in keys:
                counts["dropped_duplicate"] += 1
                return
        seen[split].add(key)
        writer.write(record)
        counts[split] += 1

    train_out.mkdir(parents=True, exist_ok=True)
    val_out.mkdir(parents=True, exist_ok=True)
    test_out.mkdir(parents=True, exist_ok=True)
    with DatasetShardWriter(train_out, f"train-{args.dataset_tag}", provenance, 50_000) as train_writer, \
         DatasetShardWriter(val_out, f"val-{args.dataset_tag}", provenance, 50_000) as val_writer, \
         DatasetShardWriter(test_out, f"test-{args.dataset_tag}", provenance, 50_000) as test_writer:
        # The base corpus is the foundation: all of it trains, minus positions
        # that a frozen holdout already owns.
        for record in read_records(args.base_labeled):
            key = position_key(record.fen)
            if key in frozen:
                counts["dropped_frozen"] += 1
                continue
            emit(train_writer, "train", record)

        # Tonight's games land in the partition their game was assigned to.
        game_index = 0
        records_in_game = 0
        for record in read_records(args.new_labeled):
            if records_in_game >= sizes[game_index]:
                game_index += 1
                records_in_game = 0
            records_in_game += 1
            split = assignment[game_index]
            if split == "train":
                if position_key(record.fen) in frozen:
                    counts["dropped_frozen"] += 1
                    continue
                emit(train_writer, "train", record)
            elif split == "val":
                emit(val_writer, "val", record)
            else:
                emit(test_writer, "test", record)

    # The frozen partitions are republished under the library so every later run
    # reads one stable location, and they remain read-only references.
    if holdout_out:
        holdout_out.mkdir(parents=True, exist_ok=True)
        for index, (path, keys) in enumerate(sorted(holdouts.items())):
            target = holdout_out / f"reference-{index}"
            target.mkdir(parents=True, exist_ok=True)
            with DatasetShardWriter(target, f"holdout-{args.dataset_tag}-{index}", provenance,
                                    50_000) as writer:
                for record in read_records(Path(path)):
                    writer.write(record)
            counts["holdout"] += len(keys)

    report = {
        "library": str(library),
        "baseLabeled": str(args.base_labeled),
        "newLabeled": str(args.new_labeled),
        "newGames": len(sizes),
        "newRecords": new_records,
        "gameAssignment": {
            split: sum(1 for value in assignment.values() if value == split)
            for split in ("train", "val", "test")
        },
        "counts": counts,
        # Reported separately from `counts`: the published references are full
        # copies, while the frozen filter above works on unique position keys.
        "frozenHoldoutKeys": sum(len(keys) for keys in holdouts.values()),
        "frozenHoldoutCopies": sum(
            1 for path in holdouts for _ in read_records(Path(path))
        ),
        "frozenHoldouts": {path: len(keys) for path, keys in holdouts.items()},
        "provenance": provenance.source_url,
    }
    target = args.report or (library / "accumulation.json")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False), flush=True)

    if counts["val"] <= 0 or counts["test"] <= 0:
        raise SystemExit("a partition came out empty; lower the new-game ratios or add games")


if __name__ == "__main__":
    main()
