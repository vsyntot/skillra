from __future__ import annotations

import csv
import re
from collections import Counter, defaultdict
from datetime import date, datetime
from pathlib import Path
from typing import Any, Iterable, Mapping

DATE_COLUMNS = ("published_at_iso", "published_at")
ID_COLUMNS = ("vacancy_id", "hh_vacancy_id", "id")


def parse_date_value(value: Any) -> date | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip()
    if not text:
        return None
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
        try:
            return date.fromisoformat(text)
        except ValueError:
            return None
    if len(text) >= 10 and re.fullmatch(r"\d{4}-\d{2}-\d{2}", text[:10]):
        try:
            return date.fromisoformat(text[:10])
        except ValueError:
            return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).date()
    except ValueError:
        return None


def require_date_value(value: Any, *, label: str) -> date:
    parsed = parse_date_value(value)
    if parsed is None:
        raise ValueError(f"{label} must be an ISO date or datetime, got {value!r}")
    return parsed


def published_date_from_row(row: Mapping[str, Any], *, date_columns: Iterable[str] = DATE_COLUMNS) -> date | None:
    for column in date_columns:
        parsed = parse_date_value(row.get(column))
        if parsed is not None:
            return parsed
    return None


def evaluate_date_semantics(
    rows: Iterable[Mapping[str, Any]],
    *,
    requested_date_from: Any,
    requested_date_to: Any,
    max_unknown_share: float = 0.05,
    max_out_of_window_share: float = 0.0,
    date_columns: Iterable[str] = DATE_COLUMNS,
) -> dict[str, Any]:
    start = require_date_value(requested_date_from, label="requested_date_from")
    end = require_date_value(requested_date_to, label="requested_date_to")
    if end < start:
        raise ValueError("requested_date_to must be greater than or equal to requested_date_from")

    row_count = 0
    known_count = 0
    unknown_count = 0
    out_of_window_count = 0
    observed_dates: list[date] = []
    out_of_window_examples: list[dict[str, str | None]] = []

    for row in rows:
        row_count += 1
        published_date = published_date_from_row(row, date_columns=date_columns)
        if published_date is None:
            unknown_count += 1
            continue
        known_count += 1
        observed_dates.append(published_date)
        if published_date < start or published_date > end:
            out_of_window_count += 1
            if len(out_of_window_examples) < 10:
                vacancy_id = next((str(row.get(column) or "") for column in ID_COLUMNS if row.get(column)), "")
                out_of_window_examples.append(
                    {
                        "vacancy_id": vacancy_id or None,
                        "published_at": published_date.isoformat(),
                    }
                )

    unknown_share = unknown_count / row_count if row_count else 0.0
    out_of_window_share = out_of_window_count / row_count if row_count else 0.0
    failures: list[str] = []
    if unknown_share > max_unknown_share:
        failures.append(f"unknown_date_share {unknown_share:.6f} > max_unknown_share {max_unknown_share:.6f}")
    if out_of_window_share > max_out_of_window_share:
        failures.append(
            "out_of_window_share " f"{out_of_window_share:.6f} > max_out_of_window_share {max_out_of_window_share:.6f}"
        )

    return {
        "status": "passed" if not failures else "failed",
        "failures": failures,
        "requested_date_from": start.isoformat(),
        "requested_date_to": end.isoformat(),
        "observed_published_at_from": min(observed_dates).isoformat() if observed_dates else None,
        "observed_published_at_to": max(observed_dates).isoformat() if observed_dates else None,
        "row_count": row_count,
        "known_published_at_count": known_count,
        "unknown_published_at_count": unknown_count,
        "out_of_window_count": out_of_window_count,
        "unknown_date_share": round(unknown_share, 6),
        "out_of_window_share": round(out_of_window_share, 6),
        "max_unknown_share": max_unknown_share,
        "max_out_of_window_share": max_out_of_window_share,
        "out_of_window_examples": out_of_window_examples,
    }


def evaluate_csv_date_semantics(
    csv_path: Path,
    *,
    requested_date_from: Any,
    requested_date_to: Any,
    max_unknown_share: float = 0.05,
    max_out_of_window_share: float = 0.0,
    date_columns: Iterable[str] = DATE_COLUMNS,
) -> dict[str, Any]:
    with csv_path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        return evaluate_date_semantics(
            reader,
            requested_date_from=requested_date_from,
            requested_date_to=requested_date_to,
            max_unknown_share=max_unknown_share,
            max_out_of_window_share=max_out_of_window_share,
            date_columns=date_columns,
        )


def detect_id_column(headers: Iterable[str], *, id_columns: Iterable[str] = ID_COLUMNS) -> str:
    header_set = {str(header) for header in headers}
    for column in id_columns:
        if column in header_set:
            return column
    raise ValueError(f"Cannot detect vacancy id column; expected one of {', '.join(id_columns)}")


def build_cross_partition_duplicate_report(partition_paths: Mapping[str, Path]) -> dict[str, Any]:
    partition_rows: dict[str, int] = {}
    partition_unique_ids: dict[str, int] = {}
    partition_ids: dict[str, set[str]] = {}
    id_total_counts: Counter[str] = Counter()
    id_partitions: dict[str, set[str]] = defaultdict(set)
    raw_rows = 0
    missing_id_rows = 0

    for partition, path in sorted(partition_paths.items()):
        ids: set[str] = set()
        rows = 0
        with path.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            if reader.fieldnames is None:
                partition_rows[partition] = 0
                partition_unique_ids[partition] = 0
                partition_ids[partition] = set()
                continue
            id_column = detect_id_column(reader.fieldnames)
            for row in reader:
                rows += 1
                raw_rows += 1
                vacancy_id = str(row.get(id_column) or "").strip()
                if not vacancy_id:
                    missing_id_rows += 1
                    continue
                ids.add(vacancy_id)
                id_total_counts[vacancy_id] += 1
                id_partitions[vacancy_id].add(partition)
        partition_rows[partition] = rows
        partition_unique_ids[partition] = len(ids)
        partition_ids[partition] = ids

    unique_ids = len(id_total_counts)
    duplicate_rows = max(raw_rows - missing_id_rows - unique_ids, 0)
    repeated_partition_distribution = Counter(str(len(partitions)) for partitions in id_partitions.values())
    adjacent_partition_overlap: dict[str, int] = {}
    sorted_partitions = sorted(partition_paths)
    for left, right in zip(sorted_partitions, sorted_partitions[1:], strict=False):
        adjacent_partition_overlap[f"{left}..{right}"] = len(partition_ids[left] & partition_ids[right])

    return {
        "raw_rows": raw_rows,
        "unique_ids": unique_ids,
        "duplicate_rows": duplicate_rows,
        "missing_id_rows": missing_id_rows,
        "partition_rows": partition_rows,
        "partition_unique_ids": partition_unique_ids,
        "repeated_id_count": sum(1 for count in id_total_counts.values() if count > 1),
        "partition_occurrence_distribution": dict(sorted(repeated_partition_distribution.items())),
        "adjacent_partition_overlap": adjacent_partition_overlap,
        "dedup_policy": "keep latest selected partition by iterating selected dates in reverse order",
    }
