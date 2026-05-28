from __future__ import annotations

import argparse
import os
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from botocore.exceptions import BotoCoreError, ClientError

from skillra_pda.storage.s3_client import create_s3_client, get_file

try:
    from scripts.pg_backup_to_s3 import backup_s3_env, resolve_pg_settings
except ModuleNotFoundError:  # pragma: no cover - direct script execution path
    from pg_backup_to_s3 import backup_s3_env, resolve_pg_settings


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Restore the latest Postgres backup into a temporary database and validate it.",
    )
    parser.add_argument("--bucket", default=None, help="Override S3 bucket (default: S3_BUCKET_BACKUPS env).")
    parser.add_argument("--prefix", default="postgres", help="S3 backup key prefix (default: postgres).")
    parser.add_argument(
        "--pg-database", default=os.environ.get("POSTGRES_DB"), help="Source database name for env resolution."
    )
    parser.add_argument("--pg-user", default=os.environ.get("POSTGRES_USER"), help="Postgres user.")
    parser.add_argument("--pg-password", default=os.environ.get("POSTGRES_PASSWORD"), help="Postgres password.")
    parser.add_argument("--pg-host", default=os.environ.get("POSTGRES_HOST"), help="Postgres host.")
    parser.add_argument("--pg-port", default=os.environ.get("POSTGRES_PORT"), help="Postgres port.")
    parser.add_argument("--database-prefix", default="skillra_restore_drill", help="Temporary database name prefix.")
    parser.add_argument("--keep-database", action="store_true", help="Keep temporary database for manual inspection.")
    parser.add_argument(
        "--metrics-file",
        default=os.environ.get("SKILLRA_PG_RESTORE_DRILL_METRICS_FILE"),
        help="Optional Prometheus textfile collector path for restore drill metrics.",
    )
    return parser.parse_args()


def latest_backup_key(client: Any, bucket: str, prefix: str) -> str:
    paginator = client.get_paginator("list_objects_v2")
    key_prefix = prefix.strip("/")
    latest: tuple[datetime, str] | None = None

    try:
        pages = paginator.paginate(Bucket=bucket, Prefix=key_prefix)
        for page in pages:
            for obj in page.get("Contents", []):
                key = obj.get("Key")
                last_modified = obj.get("LastModified")
                if not key or not key.endswith(".dump") or last_modified is None:
                    continue
                if latest is None or last_modified > latest[0]:
                    latest = (last_modified, key)
    except (BotoCoreError, ClientError) as exc:
        raise SystemExit(f"Failed to list backups in s3://{bucket}/{key_prefix}") from exc

    if latest is None:
        raise SystemExit(f"No .dump backups found in s3://{bucket}/{key_prefix}")
    return latest[1]


def pg_env(password: str | None) -> dict[str, str]:
    env = os.environ.copy()
    if password:
        env["PGPASSWORD"] = password
    return env


def pg_base_args(host: str | None, port: str | None, user: str) -> list[str]:
    args: list[str] = []
    if host:
        args.extend(["-h", host])
    if port:
        args.extend(["-p", port])
    args.extend(["-U", user])
    return args


def run_pg_command(cmd: list[str], *, password: str | None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd,
        check=True,
        env=pg_env(password),
        text=True,
        capture_output=True,
    )


def write_restore_metrics(metrics_file: Path, *, timestamp: datetime, restored_tables: int) -> None:
    metrics_file.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = metrics_file.with_name(f"{metrics_file.name}.tmp")
    payload = "\n".join(
        (
            f"skillra_pg_restore_drill_last_success_timestamp_seconds {int(timestamp.timestamp())}",
            f"skillra_pg_restore_drill_restored_tables {restored_tables}",
            "",
        )
    )
    tmp_path.write_text(payload, encoding="utf-8")
    tmp_path.replace(metrics_file)


def main() -> None:
    args = parse_args()
    bucket = args.bucket or os.environ.get("S3_BUCKET_BACKUPS")
    if not bucket:
        raise SystemExit("S3 bucket not provided. Set S3_BUCKET_BACKUPS or pass --bucket.")

    settings = resolve_pg_settings(args)
    if not settings.host:
        raise SystemExit("Postgres host not provided. Set POSTGRES_HOST or pass --pg-host.")

    client = create_s3_client(backup_s3_env())
    key = latest_backup_key(client, bucket, args.prefix)
    restore_db = f"{args.database_prefix}_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}"
    base_args = pg_base_args(settings.host, settings.port, settings.user)

    with tempfile.TemporaryDirectory() as tmp_dir:
        dump_path = Path(tmp_dir) / "restore_drill.dump"
        get_file(client, bucket, key, dump_path)

        run_pg_command(["createdb", *base_args, restore_db], password=settings.password)
        try:
            run_pg_command(["pg_restore", "--list", str(dump_path)], password=settings.password)
            run_pg_command(
                [
                    "pg_restore",
                    *base_args,
                    "--dbname",
                    restore_db,
                    "--no-owner",
                    "--no-privileges",
                    "--exit-on-error",
                    str(dump_path),
                ],
                password=settings.password,
            )
            result = run_pg_command(
                [
                    "psql",
                    *base_args,
                    "--dbname",
                    restore_db,
                    "--tuples-only",
                    "--no-align",
                    "--command",
                    "select count(*) from information_schema.tables where table_schema = 'public';",
                ],
                password=settings.password,
            )
            restored_tables = int(result.stdout.strip())
            if restored_tables <= 0:
                raise SystemExit("Restore drill failed: restored database has no public tables.")

            now = datetime.now(timezone.utc)
            if args.metrics_file:
                write_restore_metrics(Path(args.metrics_file), timestamp=now, restored_tables=restored_tables)
            print(f"Restore drill succeeded from s3://{bucket}/{key}; tables={restored_tables}; database={restore_db}")
        finally:
            if not args.keep_database:
                run_pg_command(["dropdb", "--if-exists", *base_args, restore_db], password=settings.password)


if __name__ == "__main__":
    main()
