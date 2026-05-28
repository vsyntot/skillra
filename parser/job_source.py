from __future__ import annotations

"""Source adapter contracts for job vacancy collection."""

import csv
import hashlib
import json
import os
import shutil
import tempfile
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Protocol, Sequence


@dataclass(frozen=True)
class CollectionRequest:
    query: str
    limit: int
    output_path: Path
    dataset_scope: str
    salary_only: bool = False
    delay: float = 1.5
    max_pages: int | None = None
    proxy_list: Sequence[str] = field(default_factory=tuple)
    area_ids: Sequence[int] = field(default_factory=tuple)
    date_from: str | None = None
    date_to: str | None = None
    fixture_csv_path: Path | None = None
    collection_report_path: Path | None = None


@dataclass
class ShardResult:
    source_mode: str
    area_id: int | None = None
    experience: str | None = None
    pages_requested: int = 0
    pages_succeeded: int = 0
    search_result_count: int = 0
    records_collected: int = 0
    duplicates_skipped: int = 0
    errors: list[str] = field(default_factory=list)


@dataclass
class CollectionReport:
    source_mode: str
    adapter_name: str
    status: str
    started_at_utc: str
    finished_at_utc: str
    duration_sec: float
    requested_limit: int
    row_count: int
    output_path: str
    sha256: str | None = None
    dataset_scope: str | None = None
    salary_only: bool | None = None
    shard_results: list[ShardResult] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["shard_results"] = [asdict(shard) for shard in self.shard_results]
        return payload


@dataclass
class CollectionResult:
    records: Sequence[Any]
    output_path: Path
    report: CollectionReport


class JobSourceAdapter(Protocol):
    source_mode: str

    def collect(self, request: CollectionRequest) -> CollectionResult:
        """Collect vacancies and write them to ``request.output_path``."""


def compute_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(8192), b""):
            digest.update(chunk)
    return digest.hexdigest()


def count_csv_rows(path: Path) -> int:
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.reader(handle)
        next(reader, None)
        return sum(1 for _ in reader)


def write_json_atomic(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_path = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        os.replace(temp_path, path)
    finally:
        if os.path.exists(temp_path):
            os.unlink(temp_path)


def write_collection_report(path: Path | None, report: CollectionReport) -> None:
    if path is None:
        return
    write_json_atomic(path, report.to_dict())


class FixtureJobSourceAdapter:
    """Deterministic adapter that uses a checked-in or generated CSV fixture."""

    source_mode = "fixture"

    def collect(self, request: CollectionRequest) -> CollectionResult:
        started = datetime.now(timezone.utc)
        monotonic_start = time.monotonic()
        errors: list[str] = []
        if request.fixture_csv_path is None:
            raise ValueError("fixture_csv_path is required for FixtureJobSourceAdapter")
        if not request.fixture_csv_path.exists():
            raise FileNotFoundError(f"Fixture CSV does not exist: {request.fixture_csv_path}")

        request.output_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(request.fixture_csv_path, request.output_path)
        row_count = count_csv_rows(request.output_path)
        if row_count > request.limit:
            errors.append(f"fixture row_count={row_count} exceeds requested limit={request.limit}")

        finished = datetime.now(timezone.utc)
        report = CollectionReport(
            source_mode=self.source_mode,
            adapter_name=self.__class__.__name__,
            status="success" if not errors else "warning",
            started_at_utc=started.isoformat(),
            finished_at_utc=finished.isoformat(),
            duration_sec=round(time.monotonic() - monotonic_start, 2),
            requested_limit=request.limit,
            row_count=row_count,
            output_path=str(request.output_path),
            sha256=compute_sha256(request.output_path),
            dataset_scope=request.dataset_scope,
            salary_only=request.salary_only,
            shard_results=[
                ShardResult(
                    source_mode=self.source_mode,
                    records_collected=row_count,
                    errors=errors.copy(),
                )
            ],
            errors=errors,
        )
        write_collection_report(request.collection_report_path, report)
        return CollectionResult(records=[], output_path=request.output_path, report=report)
