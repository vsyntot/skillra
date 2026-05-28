from __future__ import annotations

from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from scripts.hh_compact_parquet import compact_parquet_streaming


def _write_snapshot(path: Path, rows: list[dict[str, str]]) -> None:
    table = pa.Table.from_pylist(rows)
    path.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(table, path)


def test_compact_parquet_streaming(tmp_path: Path) -> None:
    source_dir = tmp_path / "snapshots_parquet"
    output_dir = tmp_path / "snapshots_parquet_monthly"
    dates = ["2025-01-01", "2025-01-02", "2025-01-03"]
    paths: list[Path] = []
    for idx, date_value in enumerate(dates, start=1):
        path = source_dir / f"date={date_value}" / f"snapshot_{date_value}.parquet"
        rows = [
            {"vacancy_id": f"{idx}-a", "title": "Engineer"},
            {"vacancy_id": f"{idx}-b", "title": "Analyst"},
        ]
        _write_snapshot(path, rows)
        paths.append(path)

    output_path = output_dir / "month=2025-01" / "snapshot_2025-01.parquet"
    compact_parquet_streaming(paths, output_path, compression="zstd")

    assert output_path.exists()
    table = pq.read_table(output_path, partitioning=None)
    assert table.num_rows == 6


def test_compact_parquet_streaming_schema_union(tmp_path: Path) -> None:
    source_dir = tmp_path / "snapshots_parquet"
    output_dir = tmp_path / "snapshots_parquet_monthly"
    first_path = source_dir / "date=2025-02-01" / "snapshot_2025-02-01.parquet"
    second_path = source_dir / "date=2025-02-02" / "snapshot_2025-02-02.parquet"

    _write_snapshot(first_path, [{"A": "one", "B": "two"}])
    _write_snapshot(second_path, [{"A": "three", "B": "four", "C": "five"}])

    output_path = output_dir / "month=2025-02" / "snapshot_2025-02.parquet"
    compact_parquet_streaming([first_path, second_path], output_path, compression="zstd")

    table = pq.read_table(output_path, partitioning=None)
    assert table.column_names == ["A", "B", "C"]
    assert table.num_rows == 2
    assert table.column("C").to_pylist() == [None, "five"]
