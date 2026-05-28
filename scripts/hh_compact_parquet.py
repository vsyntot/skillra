from __future__ import annotations

"""Compact daily HH parquet snapshots into monthly partitions."""

import argparse
import os
import tempfile
from collections import defaultdict
from datetime import datetime
from pathlib import Path

import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq


def parse_month(value: str) -> str:
    try:
        parsed = datetime.strptime(value, "%Y-%m")
    except ValueError as exc:
        raise argparse.ArgumentTypeError("Month must be in YYYY-MM format") from exc
    return parsed.strftime("%Y-%m")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Compact daily Parquet snapshots into monthly partitions. "
            "By default, originals are kept; use --delete-originals to remove them."
        ),
    )
    parser.add_argument(
        "--storage-dir",
        default=str(Path("data") / "raw" / "hh"),
        help="Base HH storage directory (default: data/raw/hh)",
    )
    parser.add_argument(
        "--source-dir",
        default=None,
        help="Override the daily snapshots directory (default: <storage-dir>/snapshots_parquet)",
    )
    parser.add_argument(
        "--output-dir",
        default=None,
        help="Override the monthly snapshots directory (default: <storage-dir>/snapshots_parquet_monthly)",
    )
    parser.add_argument(
        "--month",
        action="append",
        default=None,
        type=parse_month,
        help="Month to compact in YYYY-MM (can be repeated). Defaults to all months.",
    )
    parser.add_argument(
        "--compression",
        default="zstd",
        help="Parquet compression codec (default: zstd)",
    )
    parser.add_argument(
        "--delete-originals",
        action="store_true",
        help="Delete daily snapshots after successful compaction.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show planned compaction without writing outputs.",
    )
    return parser.parse_args()


def group_by_month(paths: list[Path]) -> dict[str, list[Path]]:
    grouped: dict[str, list[Path]] = defaultdict(list)
    for path in paths:
        date_folder = path.parent.name
        if not date_folder.startswith("date="):
            continue
        date_value = date_folder.split("date=")[-1]
        try:
            date_obj = datetime.strptime(date_value, "%Y-%m-%d")
        except ValueError:
            continue
        month_key = date_obj.strftime("%Y-%m")
        grouped[month_key].append(path)
    return grouped


def compact_parquet_streaming(paths: list[Path], target_path: Path, compression: str) -> None:
    if not paths:
        raise ValueError("No parquet files provided for compaction.")

    schemas = [pq.ParquetFile(path).schema_arrow for path in paths]
    unified_schema = pa.unify_schemas(schemas)
    seen_fields: set[str] = set()
    ordered_names: list[str] = []
    for schema in schemas:
        for name in schema.names:
            if name not in seen_fields:
                ordered_names.append(name)
                seen_fields.add(name)

    ordered_fields = [unified_schema.field(name) for name in ordered_names]
    unified_schema = pa.schema(ordered_fields)

    target_path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_path = tempfile.mkstemp(dir=target_path.parent, suffix=".tmp.parquet")
    os.close(fd)
    temp_target = Path(temp_path)
    try:
        with pq.ParquetWriter(temp_target, schema=unified_schema, compression=compression) as writer:
            for path in paths:
                parquet_file = pq.ParquetFile(path)
                for batch in parquet_file.iter_batches():
                    arrays: list[pa.Array] = []
                    batch_schema = batch.schema
                    for field in unified_schema:
                        if field.name in batch_schema.names:
                            column = batch.column(batch_schema.get_field_index(field.name))
                            if not column.type.equals(field.type):
                                column = pc.cast(column, field.type)
                            arrays.append(column)
                        else:
                            arrays.append(pa.nulls(batch.num_rows, type=field.type))
                    writer.write_batch(pa.RecordBatch.from_arrays(arrays, schema=unified_schema))
        os.replace(temp_target, target_path)
    finally:
        if temp_target.exists():
            temp_target.unlink()


def delete_daily_paths(paths: list[Path]) -> None:
    for path in paths:
        path.unlink(missing_ok=True)
        parent = path.parent
        if parent.exists() and not any(parent.iterdir()):
            parent.rmdir()


def main() -> None:
    args = parse_args()
    storage_dir = Path(args.storage_dir)
    source_dir = Path(args.source_dir) if args.source_dir else storage_dir / "snapshots_parquet"
    output_dir = Path(args.output_dir) if args.output_dir else storage_dir / "snapshots_parquet_monthly"

    months = set(args.month) if args.month else None

    daily_files = sorted(source_dir.glob("date=*/snapshot_*.parquet"))
    if not daily_files:
        print(f"No daily parquet snapshots found in {source_dir}")
        return

    grouped = group_by_month(daily_files)
    target_months = sorted(group for group in grouped if months is None or group in months)

    if not target_months:
        print("No matching months found for compaction.")
        return

    for month_key in target_months:
        paths = sorted(grouped[month_key])
        output_month_dir = output_dir / f"month={month_key}"
        output_path = output_month_dir / f"snapshot_{month_key}.parquet"
        if output_path.exists():
            print(f"Skipping {month_key}: output already exists at {output_path}")
            continue

        print(f"Compacting {len(paths)} snapshots into {output_path}")
        if args.dry_run:
            continue

        compact_parquet_streaming(paths, output_path, args.compression)

        if args.delete_originals:
            delete_daily_paths(paths)
            print(f"Deleted {len(paths)} daily snapshots for {month_key}")


if __name__ == "__main__":
    main()
