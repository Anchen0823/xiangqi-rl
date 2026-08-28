from __future__ import annotations

import argparse
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator, Protocol

from .dataset import DatasetProvenance, DatasetShardWriter, TrainingRecord
from .features import PikafishFeatureClient, PositionFeatures
from .teacher import FairyStockfishTeacher, TeacherEvaluation


@dataclass(frozen=True)
class SourcePosition:
    fen: str
    ply: int
    outcome: float | None
    teacher_score_cp: int | None = None
    teacher_nodes: int | None = None
    teacher_bestmove: str | None = None


class FeatureSource(Protocol):
    def fen(self, fen: str) -> PositionFeatures: ...


class TeacherSource(Protocol):
    def evaluate_fen(self, fen: str, nodes: int) -> TeacherEvaluation: ...


def file_sha256(path: Path) -> str:
    if path.is_dir():
        path = path / "manifest.json"
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_source_file(path: Path) -> Iterator[SourcePosition]:
    with path.open("rt", encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, 1):
            if not line.strip():
                continue
            try:
                payload = json.loads(line)
                fen = payload["fen"]
                ply = payload.get("ply", line_number - 1)
                outcome = payload.get("outcome")
                position = SourcePosition(
                    fen,
                    ply,
                    outcome,
                    payload.get("teacherScoreCp"),
                    payload.get("teacherNodes"),
                    payload.get("teacherBestmove"),
                )
                TrainingRecord(fen, 0, outcome, ply, _DUMMY_FEATURES).validate()
                cached = (
                    position.teacher_score_cp,
                    position.teacher_nodes,
                    position.teacher_bestmove,
                )
                if any(value is not None for value in cached):
                    if not all(value is not None for value in cached):
                        raise ValueError("cached teacher fields must be all present or all absent")
                    TrainingRecord(
                        fen,
                        position.teacher_score_cp,
                        outcome,
                        ply,
                        _DUMMY_FEATURES,
                        position.teacher_nodes,
                        position.teacher_bestmove,
                    ).validate()
            except (json.JSONDecodeError, KeyError, TypeError, ValueError) as error:
                raise ValueError(f"invalid source record at line {line_number}: {error}") from error
            yield position


def read_source(path: Path) -> Iterator[SourcePosition]:
    if path.is_file():
        yield from _read_source_file(path)
        return
    manifest_path = path / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("schemaVersion") != 1 or manifest.get("license") != "ODbL-1.0":
        raise ValueError("self-play source manifest must be schema 1 and ODbL-1.0")
    for game in manifest.get("games", []):
        game_path = path / game["file"]
        if file_sha256(game_path) != game["sha256"]:
            raise ValueError(f"self-play source checksum mismatch for {game_path.name}")
        yield from _read_source_file(game_path)


# Used only to reuse TrainingRecord's scalar/FEN validation before feature extraction.
from .features import PerspectiveFeatures  # noqa: E402

_DUMMY_FEATURES = PositionFeatures(
    0,
    (
        PerspectiveFeatures("red", 0, 0, False, (), ()),
        PerspectiveFeatures("black", 0, 0, False, (), ()),
    ),
)


def label_records(
    source: Iterator[SourcePosition],
    writer: DatasetShardWriter,
    features: FeatureSource,
    teacher: TeacherSource,
    *,
    nodes: int,
    skip: int = 0,
    limit: int | None = None,
) -> int:
    if nodes <= 0 or skip < 0 or (limit is not None and limit <= 0):
        raise ValueError("nodes and limit must be positive; skip cannot be negative")
    accepted = 0
    for index, position in enumerate(source):
        if index < skip:
            continue
        if limit is not None and accepted >= limit:
            break
        if position.teacher_score_cp is None:
            evaluation = teacher.evaluate_fen(position.fen, nodes)
        else:
            assert position.teacher_nodes is not None and position.teacher_bestmove is not None
            evaluation = TeacherEvaluation(
                position.teacher_score_cp,
                position.teacher_bestmove,
                position.teacher_nodes,
            )
        writer.write(
            TrainingRecord(
                fen=position.fen,
                score_cp=evaluation.score_cp,
                outcome=position.outcome,
                ply=position.ply,
                features=features.fen(position.fen),
                teacher_nodes=evaluation.nodes,
                bestmove=evaluation.bestmove,
            )
        )
        accepted += 1
        if accepted % 100 == 0:
            print(json.dumps({"accepted": accepted, "sourceOffset": index + 1}), flush=True)
    return accepted


def main() -> None:
    parser = argparse.ArgumentParser(description="Create resumable CC0 teacher label shards")
    parser.add_argument(
        "--source", type=Path, required=True,
        help="ODbL JSONL positions or a verified self-play source directory",
    )
    parser.add_argument("--source-url", required=True)
    parser.add_argument("--attribution", required=True)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--dataset-id", required=True)
    parser.add_argument("--feature-engine", type=Path, required=True)
    parser.add_argument("--teacher-engine", type=Path, required=True)
    parser.add_argument("--teacher-manifest", type=Path, required=True)
    parser.add_argument("--nodes", type=int, default=10_000)
    parser.add_argument("--threads", type=int, default=1)
    parser.add_argument("--hash-mb", type=int, default=128)
    parser.add_argument("--records-per-shard", type=int, default=50_000)
    parser.add_argument("--max-records", type=int)
    args = parser.parse_args()

    teacher_manifest = json.loads(args.teacher_manifest.read_text(encoding="utf-8"))
    teacher_hash = file_sha256(args.teacher_engine)
    if teacher_manifest.get("networkLicense") != "CC0-1.0":
        raise ValueError("teacher manifest does not grant CC0-1.0 for the network")
    if teacher_hash != teacher_manifest.get("assetSha256"):
        raise ValueError("teacher executable does not match the pinned manifest SHA-256")
    if args.source.is_dir():
        source_manifest = json.loads((args.source / "manifest.json").read_text(encoding="utf-8"))
        if source_manifest.get("config", {}).get("teacherSha256") != teacher_hash:
            raise ValueError("self-play source teacher SHA-256 does not match the labeler teacher")
    provenance = DatasetProvenance(
        source_url=args.source_url,
        source_sha256=file_sha256(args.source),
        attribution=args.attribution,
        teacher_name=teacher_manifest["name"],
        teacher_url=teacher_manifest["networkReleaseUrl"],
        teacher_sha256=teacher_hash,
    )
    with DatasetShardWriter(
        args.dataset, args.dataset_id, provenance, args.records_per_shard
    ) as writer:
        skip = int(writer.manifest["totalRecords"])
        with PikafishFeatureClient(args.feature_engine) as feature_client:
            with FairyStockfishTeacher(
                args.teacher_engine, threads=args.threads, hash_mb=args.hash_mb
            ) as teacher:
                accepted = label_records(
                    read_source(args.source),
                    writer,
                    feature_client,
                    teacher,
                    nodes=args.nodes,
                    skip=skip,
                    limit=args.max_records,
                )
    print(json.dumps({"accepted": accepted, "resumedFrom": skip}), flush=True)


if __name__ == "__main__":
    main()
