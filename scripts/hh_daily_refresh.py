from __future__ import annotations

"""Daily HH ingestion entrypoint (snapshot, delta, latest, state)."""

import argparse
import csv
import hashlib
import os
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import date, datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from parser import hh_scraper  # noqa: E402
from parser.job_source import CollectionRequest, FixtureJobSourceAdapter  # noqa: E402
from src.skillra_pda.ingest.hh_daily import (  # noqa: E402
    SCHEMA_VERSION,
    append_manifest_jsonl,
    build_failed_manifest_payload,
    build_manifest_payload,
    compute_delta,
    read_csv_columns,
    read_vacancy_ids,
    write_parquet_snapshot,
    write_state_json,
)
from src.skillra_pda.ingest.source_registry import build_source_capability_ref  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Daily HH ingestion: snapshot, delta, latest, state/manifest.",
    )
    parser.add_argument("--query", default=hh_scraper.DEFAULT_QUERY, help="HH search query")
    parser.add_argument("--limit", type=int, default=hh_scraper.DEFAULT_LIMIT, help="Vacancy limit")
    parser.add_argument(
        "--storage-dir",
        default=str(Path("data") / "raw" / "hh"),
        help=(
            "Storage directory for HH artifacts. When --skip-scrape is set, this can also be "
            "a path to a CSV file to use as the snapshot source."
        ),
    )
    parser.add_argument(
        "--run-date",
        default=datetime.now(timezone.utc).date().isoformat(),
        help="Run date in YYYY-MM-DD (defaults to UTC today)",
    )
    parser.add_argument("--dry-run", action="store_true", help="Compute without writing outputs")
    parser.add_argument(
        "--skip-scrape",
        action="store_true",
        help="Skip running hh_scraper and use an existing snapshot file",
    )
    parser.add_argument(
        "--salary-only",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="Limit HH scrape to vacancies with disclosed salary.",
    )
    parser.add_argument(
        "--dataset-scope",
        default=None,
        help=(
            "Explicit dataset scope label stored in state.json. Defaults to "
            "all_vacancies or salary_disclosed based on --salary-only."
        ),
    )
    parser.add_argument(
        "--source-mode",
        choices=("hh_html", "fixture"),
        default=os.getenv("SKILLRA_JOB_SOURCE_MODE", "hh_html"),
        help="Vacancy source adapter mode. fixture is intended for deterministic CI/pipeline smoke.",
    )
    parser.add_argument(
        "--fixture-csv",
        default=os.getenv("SKILLRA_JOB_FIXTURE_CSV"),
        help="CSV fixture path used when --source-mode=fixture.",
    )
    return parser.parse_args()


def parse_run_date(value: str) -> date:
    return datetime.strptime(value, "%Y-%m-%d").date()


def utc_run_id() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%SZ")


def ensure_dir(path: Path, dry_run: bool) -> None:
    if dry_run:
        return
    path.mkdir(parents=True, exist_ok=True)


def run_scraper(
    output_path: Path,
    query: str,
    limit: int,
    *,
    salary_only: bool,
    dataset_scope: str,
    source_mode: str = "hh_html",
    fixture_csv_path: Path | None = None,
    collection_report_path: Path | None = None,
) -> None:
    if source_mode == "fixture":
        FixtureJobSourceAdapter().collect(
            CollectionRequest(
                query=query,
                limit=limit,
                output_path=output_path,
                dataset_scope=dataset_scope,
                salary_only=salary_only,
                fixture_csv_path=fixture_csv_path,
                collection_report_path=collection_report_path,
            )
        )
        return

    command = [
        sys.executable,
        str(ROOT / "parser" / "hh_scraper.py"),
        "--query",
        query,
        "--limit",
        str(limit),
        "--output",
        str(output_path),
        "--dataset-scope",
        dataset_scope,
    ]
    command.append("--salary-only" if salary_only else "--no-salary-only")
    if collection_report_path is not None:
        command.extend(["--collection-report", str(collection_report_path)])
    subprocess.run(command, check=True)


def count_rows(csv_path: Path) -> int:
    with csv_path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.reader(handle)
        next(reader, None)
        return sum(1 for _ in reader)


def compute_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(8192), b""):
            digest.update(chunk)
    return digest.hexdigest()


def atomic_copy(src: Path, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_path = tempfile.mkstemp(dir=dest.parent, suffix=".tmp")
    os.close(fd)
    temp_target = Path(temp_path)
    try:
        shutil.copyfile(src, temp_target)
        os.replace(temp_target, dest)
    finally:
        if temp_target.exists():
            temp_target.unlink()


def write_delta_csv(delta_path: Path, new_ids: set[str], removed_ids: set[str]) -> None:
    fd, temp_path = tempfile.mkstemp(dir=delta_path.parent, suffix=".tmp")
    os.close(fd)
    temp_target = Path(temp_path)
    try:
        with temp_target.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(["vacancy_id", "change"])
            for vacancy_id in sorted(new_ids):
                writer.writerow([vacancy_id, "new"])
            for vacancy_id in sorted(removed_ids):
                writer.writerow([vacancy_id, "removed"])
        os.replace(temp_target, delta_path)
    finally:
        if temp_target.exists():
            temp_target.unlink()


def resolve_storage(storage_arg: str, skip_scrape: bool) -> tuple[Path, Path | None]:
    storage_path = Path(storage_arg)
    if skip_scrape and storage_path.suffix.lower() == ".csv":
        return storage_path.parent, storage_path
    return storage_path, None


def format_error_message(exc: BaseException, limit: int = 200) -> str:
    message = str(exc).strip()
    if not message:
        message = exc.__class__.__name__
    else:
        message = f"{exc.__class__.__name__}: {message}"
    message = " ".join(message.splitlines()).strip()
    if len(message) > limit:
        message = f"{message[: max(0, limit - 3)]}..."
    return message


def main() -> None:
    args = parse_args()
    run_date = parse_run_date(args.run_date)
    run_id = utc_run_id()
    dataset_scope = args.dataset_scope or ("salary_disclosed" if args.salary_only else "all_vacancies")

    storage_dir, snapshot_source = resolve_storage(args.storage_dir, args.skip_scrape)
    snapshots_dir = storage_dir / "snapshots"
    deltas_dir = storage_dir / "deltas"
    snapshot_path = snapshots_dir / f"snapshot_{run_id}.csv"
    parquet_snapshots_dir = storage_dir / "snapshots_parquet" / f"date={run_date.isoformat()}"
    parquet_snapshot_path = parquet_snapshots_dir / f"snapshot_{run_id}.parquet"
    delta_path = deltas_dir / f"delta_{run_id}.csv"
    latest_path = storage_dir / "latest.csv"
    state_path = storage_dir / "state.json"
    manifest_path = storage_dir / "manifest.jsonl"
    collection_report_path = storage_dir / "collection_reports" / f"collection_{run_id}.json"
    fixture_csv_path = Path(args.fixture_csv) if args.fixture_csv else None

    start_time = time.monotonic()

    try:
        if args.skip_scrape and snapshot_source is None:
            if not snapshot_path.exists():
                raise FileNotFoundError(
                    "--skip-scrape expects a snapshot file. Provide --storage-dir pointing to a CSV "
                    "or pre-create the snapshot file: "
                    f"{snapshot_path}"
                )
            snapshot_source = snapshot_path

        if not args.skip_scrape and snapshot_path.exists():
            raise FileExistsError(f"Snapshot already exists: {snapshot_path}")

        if args.dry_run and not args.skip_scrape:
            with tempfile.TemporaryDirectory() as temp_dir:
                temp_snapshot = Path(temp_dir) / "snapshot.csv"
                run_scraper(
                    temp_snapshot,
                    args.query,
                    args.limit,
                    salary_only=args.salary_only,
                    dataset_scope=dataset_scope,
                    source_mode=args.source_mode,
                    fixture_csv_path=fixture_csv_path,
                    collection_report_path=Path(temp_dir) / "collection_report.json",
                )
                current_snapshot = temp_snapshot
                current_ids = read_vacancy_ids(str(current_snapshot))
                current_rows = count_rows(current_snapshot)
                current_columns = read_csv_columns(str(current_snapshot))
        else:
            if args.skip_scrape:
                ensure_dir(snapshots_dir, args.dry_run)
                if args.dry_run or snapshot_source == snapshot_path:
                    current_snapshot = snapshot_source
                else:
                    if snapshot_path.exists():
                        raise FileExistsError(f"Snapshot already exists: {snapshot_path}")
                    fd, temp_path = tempfile.mkstemp(dir=snapshots_dir, suffix=".tmp")
                    os.close(fd)
                    temp_snapshot = Path(temp_path)
                    try:
                        shutil.copyfile(snapshot_source, temp_snapshot)
                        os.replace(temp_snapshot, snapshot_path)
                        current_snapshot = snapshot_path
                    finally:
                        if temp_snapshot.exists():
                            temp_snapshot.unlink()
                current_ids = read_vacancy_ids(str(current_snapshot))
                current_rows = count_rows(current_snapshot)
                current_columns = read_csv_columns(str(current_snapshot))
            else:
                ensure_dir(snapshots_dir, args.dry_run)
                fd, temp_path = tempfile.mkstemp(dir=snapshots_dir, suffix=".tmp")
                os.close(fd)
                temp_snapshot = Path(temp_path)
                current_snapshot: Path | None = None
                try:
                    run_scraper(
                        temp_snapshot,
                        args.query,
                        args.limit,
                        salary_only=args.salary_only,
                        dataset_scope=dataset_scope,
                        source_mode=args.source_mode,
                        fixture_csv_path=fixture_csv_path,
                        collection_report_path=collection_report_path,
                    )
                    if args.dry_run:
                        current_snapshot = temp_snapshot
                    else:
                        os.replace(temp_snapshot, snapshot_path)
                        current_snapshot = snapshot_path
                    current_ids = read_vacancy_ids(str(current_snapshot))
                    current_rows = count_rows(current_snapshot)
                    current_columns = read_csv_columns(str(current_snapshot))
                finally:
                    if temp_snapshot.exists() and current_snapshot != snapshot_path:
                        temp_snapshot.unlink()

        prev_ids = set()
        if latest_path.exists():
            prev_ids = read_vacancy_ids(str(latest_path))
        new_ids, removed_ids = compute_delta(prev_ids, current_ids)

        if args.dry_run:
            duration = time.monotonic() - start_time
            print(f"[dry-run] run_id={run_id} date={run_date.isoformat()}")
            print(f"[dry-run] snapshot_rows={current_rows} new={len(new_ids)} removed={len(removed_ids)}")
            print(f"[dry-run] duration_sec={duration:.2f}")
            return

        if parquet_snapshot_path.exists():
            raise FileExistsError(f"Parquet snapshot already exists: {parquet_snapshot_path}")

        write_parquet_snapshot(
            str(current_snapshot),
            str(parquet_snapshot_path),
            compression="zstd",
        )

        ensure_dir(deltas_dir, args.dry_run)
        if delta_path.exists():
            raise FileExistsError(f"Delta already exists: {delta_path}")

        write_delta_csv(delta_path, new_ids, removed_ids)
        atomic_copy(Path(current_snapshot), latest_path)

        sha256 = compute_sha256(latest_path)
        duration = time.monotonic() - start_time

        snapshot_rel = snapshot_path.relative_to(storage_dir)
        delta_rel = delta_path.relative_to(storage_dir)
        parquet_rel = parquet_snapshot_path.relative_to(storage_dir)

        state_payload = {
            "last_run_id": run_id,
            "run_date": run_date.isoformat(),
            "snapshot_path": snapshot_rel.as_posix(),
            "delta_path": delta_rel.as_posix(),
            "parquet_snapshot_path": parquet_rel.as_posix(),
            "latest_path": latest_path.relative_to(storage_dir).as_posix(),
            "sha256": sha256,
            "row_count": current_rows,
            "new_count": len(new_ids),
            "removed_count": len(removed_ids),
            "generated_at_utc": datetime.now(timezone.utc).isoformat(),
            "query": args.query,
            "limit": args.limit,
            "salary_only": args.salary_only,
            "dataset_scope": dataset_scope,
            "schema_version": SCHEMA_VERSION,
            "source_mode": args.source_mode,
            "source_capability_ref": build_source_capability_ref(
                source_mode=args.source_mode,
                use_case="current_snapshot",
                capability_status="supported",
                evidence_type="registry",
                dataset_scope=dataset_scope,
                salary_only=args.salary_only,
                areas=list(hh_scraper.DEFAULT_AREA_IDS),
            ),
            "collection_report_path": collection_report_path.relative_to(storage_dir).as_posix()
            if collection_report_path.exists()
            else None,
        }

        manifest_payload = build_manifest_payload(
            state_payload=state_payload,
            duration_sec=duration,
            parquet_snapshot_path=parquet_rel.as_posix(),
            snapshot_csv_path=snapshot_rel.as_posix(),
            columns=current_columns,
            schema_version=SCHEMA_VERSION,
        )
        append_manifest_jsonl(str(manifest_path), manifest_payload)
        write_state_json(str(state_path), state_payload)

        print(f"Saved snapshot to {snapshot_path}")
        print(f"Saved delta to {delta_path}")
        print(f"Updated latest to {latest_path}")
    except Exception as exc:
        duration = time.monotonic() - start_time
        error_message = format_error_message(exc)
        manifest_payload = build_failed_manifest_payload(
            run_id=run_id,
            run_date=run_date.isoformat(),
            duration_sec=duration,
            error=error_message,
            query=args.query,
            limit=args.limit,
            schema_version=SCHEMA_VERSION,
        )
        append_manifest_jsonl(str(manifest_path), manifest_payload)
        print(f"Failed run_id={run_id}: {error_message}", file=sys.stderr)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
