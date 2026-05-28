from __future__ import annotations

import csv
import json
import os
import tempfile
from typing import Iterable

import pandas as pd

SCHEMA_VERSION = "1"


def read_vacancy_ids(csv_path: str) -> set[str]:
    """Read vacancy identifiers from a CSV file.

    Prefers a column named ``vacancy_id``; falls back to ``id`` or the first
    column in the file.
    """
    with open(csv_path, "r", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None:
            return set()
        fieldnames = [name.strip() for name in reader.fieldnames]
        if "vacancy_id" in fieldnames:
            id_field = "vacancy_id"
        elif "id" in fieldnames:
            id_field = "id"
        else:
            id_field = fieldnames[0]

        ids = set()
        for row in reader:
            value = row.get(id_field)
            if value is None:
                continue
            value = str(value).strip()
            if value:
                ids.add(value)

    return ids


def read_csv_columns(csv_path: str) -> list[str]:
    """Read column names from a CSV file."""
    with open(csv_path, "r", encoding="utf-8") as handle:
        reader = csv.reader(handle)
        header = next(reader, None)
        if header is None:
            return []
        return [column.strip() for column in header if column.strip()]


def compute_delta(
    prev_ids: Iterable[str],
    current_ids: Iterable[str],
) -> tuple[set[str], set[str]]:
    """Compute newly added and removed vacancy ids."""
    prev_set = set(prev_ids)
    current_set = set(current_ids)
    new_ids = current_set - prev_set
    removed_ids = prev_set - current_set
    return new_ids, removed_ids


def write_state_json(path: str, payload: dict) -> None:
    """Write state metadata JSON atomically."""
    directory = os.path.dirname(path)
    if directory:
        os.makedirs(directory, exist_ok=True)

    enriched_payload = dict(payload)
    enriched_payload.setdefault("schema_version", SCHEMA_VERSION)

    fd, temp_path = tempfile.mkstemp(dir=directory or None, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(enriched_payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        os.replace(temp_path, path)
    finally:
        if os.path.exists(temp_path):
            os.unlink(temp_path)


def append_manifest_jsonl(path: str, payload: dict) -> None:
    """Append a JSON line to the manifest file."""
    directory = os.path.dirname(path)
    if directory:
        os.makedirs(directory, exist_ok=True)

    with open(path, "a", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False)
        handle.write("\n")


def build_manifest_payload(
    state_payload: dict,
    duration_sec: float,
    parquet_snapshot_path: str,
    snapshot_csv_path: str,
    columns: list[str],
    status: str = "success",
    error: str | None = None,
    schema_version: str = SCHEMA_VERSION,
) -> dict:
    """Build manifest payload with enriched metadata."""
    payload = {
        **state_payload,
        "duration_sec": round(duration_sec, 2),
        "parquet_snapshot_path": parquet_snapshot_path,
        "status": status,
        "snapshot_csv": snapshot_csv_path,
        "snapshot_parquet": parquet_snapshot_path,
        "row_count": state_payload.get("row_count"),
        "columns": columns,
        "schema_version": schema_version,
    }
    if error:
        payload["error"] = error
    return payload


def build_failed_manifest_payload(
    run_id: str,
    run_date: str,
    duration_sec: float,
    error: str,
    query: str | None = None,
    limit: int | None = None,
    schema_version: str = SCHEMA_VERSION,
) -> dict:
    """Build manifest payload for failed runs."""
    payload = {
        "last_run_id": run_id,
        "run_date": run_date,
        "status": "failed",
        "error": error,
        "duration_sec": round(duration_sec, 2),
        "schema_version": schema_version,
    }
    if query is not None:
        payload["query"] = query
    if limit is not None:
        payload["limit"] = limit
    return payload


def write_parquet_snapshot(csv_path: str, parquet_path: str, compression: str = "zstd") -> None:
    """Write a Parquet snapshot based on a CSV source."""
    directory = os.path.dirname(parquet_path)
    if directory:
        os.makedirs(directory, exist_ok=True)

    fd, temp_path = tempfile.mkstemp(dir=directory or None, suffix=".tmp.parquet")
    os.close(fd)
    try:
        frame = pd.read_csv(csv_path, dtype=str)
        if "vacancy_id" in frame.columns:
            frame["vacancy_id"] = frame["vacancy_id"].astype(str)
        frame.to_parquet(temp_path, index=False, compression=compression)
        os.replace(temp_path, parquet_path)
    except Exception:
        if os.path.exists(temp_path):
            os.unlink(temp_path)
        raise
