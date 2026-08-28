from __future__ import annotations

import gzip
import hashlib
import json
import math
import os
import re
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from .features import PositionFeatures, parse_training_features


SCHEMA_VERSION = 2
GAME_DATA_LICENSE = "ODbL-1.0"
TEACHER_LICENSE = "CC0-1.0"


@dataclass(frozen=True)
class DatasetProvenance:
    source_url: str
    source_sha256: str
    attribution: str
    teacher_name: str
    teacher_url: str
    teacher_sha256: str
    game_data_license: str = GAME_DATA_LICENSE
    teacher_license: str = TEACHER_LICENSE

    def validate(self) -> None:
        if self.game_data_license != GAME_DATA_LICENSE:
            raise ValueError("teacher datasets must use ODbL-1.0 game data")
        if self.teacher_license != TEACHER_LICENSE:
            raise ValueError("teacher labels must come from a CC0-1.0 network")
        for name in ("source_url", "attribution", "teacher_name", "teacher_url"):
            if not getattr(self, name).strip():
                raise ValueError(f"provenance field {name} cannot be empty")
        for name in ("source_sha256", "teacher_sha256"):
            if not re.fullmatch(r"[0-9a-f]{64}", getattr(self, name)):
                raise ValueError(f"provenance field {name} must be a lowercase SHA-256")


@dataclass(frozen=True)
class TrainingRecord:
    fen: str
    score_cp: int
    outcome: float | None
    ply: int
    features: PositionFeatures
    teacher_nodes: int = 0
    bestmove: str = ""

    def validate(self) -> None:
        if not self.fen.strip() or "\n" in self.fen or "\r" in self.fen:
            raise ValueError("record FEN must be a non-empty single line")
        if isinstance(self.score_cp, bool) or not isinstance(self.score_cp, int):
            raise ValueError("score_cp must be an integer")
        if self.outcome is not None and (
            not math.isfinite(self.outcome) or not -1.0 <= self.outcome <= 1.0
        ):
            raise ValueError("outcome must be null or finite and in [-1, 1]")
        if isinstance(self.ply, bool) or not isinstance(self.ply, int) or self.ply < 0:
            raise ValueError("ply must be a non-negative integer")
        if (
            isinstance(self.teacher_nodes, bool)
            or not isinstance(self.teacher_nodes, int)
            or self.teacher_nodes < 0
        ):
            raise ValueError("teacher_nodes must be a non-negative integer")
        if "\n" in self.bestmove or "\r" in self.bestmove:
            raise ValueError("bestmove must be a single line")

    def to_dict(self) -> dict[str, Any]:
        self.validate()
        perspectives = []
        for perspective in self.features.perspectives:
            perspectives.append(
                {
                    "color": perspective.color,
                    "featureBucket": perspective.feature_bucket,
                    "attackBucket": perspective.attack_bucket,
                    "mirror": perspective.mirror,
                    "psq": list(perspective.psq),
                    "threats": list(perspective.threats),
                }
            )
        return {
            "fen": self.fen,
            "scoreCp": self.score_cp,
            "outcome": self.outcome,
            "ply": self.ply,
            "teacherNodes": self.teacher_nodes,
            "bestmove": self.bestmove,
            "features": {
                "layerBucket": self.features.layer_bucket,
                "perspectives": perspectives,
            },
        }

    @classmethod
    def from_dict(cls, payload: Any) -> TrainingRecord:
        if not isinstance(payload, dict):
            raise ValueError("training record must be an object")
        try:
            record = cls(
                fen=payload["fen"],
                score_cp=payload["scoreCp"],
                outcome=payload["outcome"],
                ply=payload["ply"],
                features=parse_training_features(
                    json.dumps(payload["features"], separators=(",", ":"))
                ),
                teacher_nodes=payload.get("teacherNodes", 0),
                bestmove=payload.get("bestmove", ""),
            )
        except KeyError as error:
            raise ValueError(f"training record is missing {error.args[0]}") from error
        record.validate()
        return record


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


class DatasetShardWriter:
    """Atomically finalize gzip JSONL shards and resume from their manifest."""

    def __init__(
        self,
        directory: Path,
        dataset_id: str,
        provenance: DatasetProvenance,
        records_per_shard: int = 50_000,
    ) -> None:
        if not dataset_id.strip():
            raise ValueError("dataset_id cannot be empty")
        if records_per_shard <= 0:
            raise ValueError("records_per_shard must be positive")
        provenance.validate()
        self.directory = directory
        self.directory.mkdir(parents=True, exist_ok=True)
        self.manifest_path = directory / "manifest.json"
        self.records_per_shard = records_per_shard
        self._stream = None
        self._partial_path: Path | None = None
        self._final_path: Path | None = None
        self._count = 0
        if self.manifest_path.exists():
            self.manifest = json.loads(self.manifest_path.read_text(encoding="utf-8"))
            if self.manifest.get("schemaVersion") != SCHEMA_VERSION:
                raise ValueError("dataset manifest schema is unsupported")
            if self.manifest.get("datasetId") != dataset_id:
                raise ValueError("dataset_id does not match the existing manifest")
            if self.manifest.get("provenance") != asdict(provenance):
                raise ValueError("provenance does not match the existing manifest")
        else:
            self.manifest = {
                "schemaVersion": SCHEMA_VERSION,
                "datasetId": dataset_id,
                "createdAt": datetime.now(timezone.utc).isoformat(),
                "provenance": asdict(provenance),
                "totalRecords": 0,
                "shards": [],
            }
            self._write_manifest()

    def _write_manifest(self) -> None:
        temporary = self.manifest_path.with_suffix(".json.tmp")
        temporary.write_text(
            json.dumps(self.manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        os.replace(temporary, self.manifest_path)

    def _open_shard(self) -> None:
        index = len(self.manifest["shards"])
        self._final_path = self.directory / f"shard-{index:06d}.jsonl.gz"
        self._partial_path = self.directory / f"shard-{index:06d}.jsonl.gz.partial"
        self._stream = gzip.open(self._partial_path, "wt", encoding="utf-8", newline="\n")
        self._count = 0

    def write(self, record: TrainingRecord) -> None:
        payload = record.to_dict()
        if self._stream is None:
            self._open_shard()
        assert self._stream is not None
        self._stream.write(json.dumps(payload, separators=(",", ":")) + "\n")
        self._count += 1
        if self._count >= self.records_per_shard:
            self._finalize_shard()

    def _finalize_shard(self) -> None:
        if self._stream is None:
            return
        assert self._partial_path is not None and self._final_path is not None
        self._stream.close()
        self._stream = None
        if self._count == 0:
            self._partial_path.unlink(missing_ok=True)
            return
        os.replace(self._partial_path, self._final_path)
        self.manifest["shards"].append(
            {
                "file": self._final_path.name,
                "records": self._count,
                "compressedBytes": self._final_path.stat().st_size,
                "sha256": _sha256(self._final_path),
            }
        )
        self.manifest["totalRecords"] += self._count
        self._write_manifest()
        self._count = 0

    def close(self) -> None:
        self._finalize_shard()

    def __enter__(self) -> DatasetShardWriter:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()


def read_records(directory: Path, verify: bool = True) -> Iterator[TrainingRecord]:
    manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    if manifest.get("schemaVersion") != SCHEMA_VERSION:
        raise ValueError("dataset manifest schema is unsupported")
    for shard in manifest.get("shards", []):
        path = directory / shard["file"]
        if verify and _sha256(path) != shard["sha256"]:
            raise ValueError(f"checksum mismatch for {path.name}")
        with gzip.open(path, "rt", encoding="utf-8") as stream:
            for line in stream:
                yield TrainingRecord.from_dict(json.loads(line))
