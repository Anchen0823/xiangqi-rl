import json
import tempfile
import unittest
from pathlib import Path

from xiangqi_nnue.dataset import (
    DatasetProvenance,
    DatasetShardWriter,
    TrainingRecord,
    read_records,
)
from xiangqi_nnue.features import PerspectiveFeatures, PositionFeatures
from xiangqi_nnue.label import file_sha256
from xiangqi_nnue.split import split_by_games, write_split

FEATURES = PositionFeatures(
    1,
    (
        PerspectiveFeatures("red", 0, 0, False, (1,), (2,)),
        PerspectiveFeatures("black", 0, 0, False, (3,), (4,)),
    ),
)


def make_game_file(root: Path, name: str, fens: list[str]) -> None:
    path = root / name
    with path.open("w", encoding="utf-8") as handle:
        for fen in fens:
            handle.write(json.dumps({"fen": fen, "ply": 0}) + "\n")


def make_source(root: Path, games: list[list[str]]) -> dict:
    manifest = {
        "schemaVersion": 1,
        "license": "ODbL-1.0",
        "attribution": "test",
        "config": {},
        "totalRecords": 0,
        "games": [],
    }
    for index, fens in enumerate(games):
        name = f"game-{index:06d}.jsonl"
        make_game_file(root, name, fens)
        path = root / name
        manifest["games"].append({
            "file": name,
            "records": len(fens),
            "sha256": file_sha256(path),
        })
        manifest["totalRecords"] += len(fens)
    (root / "manifest.json").write_text(
        json.dumps(manifest, indent=2), encoding="utf-8"
    )
    return manifest


def make_labeled(root: Path, fens: list[str]) -> None:
    provenance = DatasetProvenance(
        "https://example.test/source", "0" * 64, "Example", "Teacher",
        "https://example.test/teacher", "1" * 64,
    )
    with DatasetShardWriter(root, "labeled", provenance, 50) as writer:
        for index, fen in enumerate(fens):
            writer.write(TrainingRecord(fen, index * 10, None, index,
                                        FEATURES, 5000, "a0a1"))


class SplitTests(unittest.TestCase):
    def test_games_split_with_cross_split_dedup(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source"
            source.mkdir()
            # 10 games x 4 records; games 0 and 9 share a FEN to test dedup.
            games = [[f"fen-{g}-{p}" for p in range(4)] for g in range(10)]
            games[9][0] = games[0][0]  # cross-game duplicate FEN
            make_source(source, games)

            labeled = root / "labeled"
            all_fens = [fen for game in games for fen in game]
            make_labeled(labeled, all_fens)

            buckets = split_by_games(
                labeled=labeled, source=source,
                train_ratio=0.8, val_ratio=0.1, seed=3,
            )
            self.assertEqual(set(buckets), {"train", "val", "test"})
            total = sum(len(records) for records in buckets.values())
            # 40 records minus the 1 duplicated FEN dropped from a later split.
            self.assertLessEqual(total, 40)
            seen: set[str] = set()
            for split in ("train", "val", "test"):
                for record in buckets[split]:
                    self.assertNotIn(record.fen, seen,
                                     f"{record.fen} leaked into {split}")
                    seen.add(record.fen)

    def test_write_split_round_trip(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            provenance = DatasetProvenance(
                "https://example.test/source", "0" * 64, "Example", "Teacher",
                "https://example.test/teacher", "1" * 64,
            )
            records = [TrainingRecord(f"fen-{i}", i, None, i, FEATURES, 5000, "a0a1")
                       for i in range(5)]
            out = write_split(root, "val", records, provenance)
            self.assertEqual(
                len(list(read_records(out))), 5,
            )
            manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["datasetId"], "val-v1")


if __name__ == "__main__":
    unittest.main()
