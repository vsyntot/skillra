from __future__ import annotations

import argparse
import os
import subprocess
import tempfile
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Mapping

from botocore.exceptions import BotoCoreError, ClientError

from skillra_pda.storage.s3_client import create_s3_client, put_file


@dataclass(frozen=True)
class PgSettings:
    database: str
    user: str
    password: str | None
    host: str | None
    port: str | None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Create pg_dump backup (custom format) and upload to S3.",
    )
    parser.add_argument(
        "--bucket",
        default=None,
        help="Override S3 bucket (default: S3_BUCKET_BACKUPS env)",
    )
    parser.add_argument(
        "--prefix",
        default="postgres",
        help="S3 key prefix (default: postgres)",
    )
    parser.add_argument(
        "--retention-days",
        type=int,
        default=None,
        help="Delete backups older than N days in the same prefix.",
    )
    parser.add_argument(
        "--dump-dir",
        default=None,
        help="Directory for temporary dump file (default: system temp).",
    )
    parser.add_argument(
        "--keep-local",
        action="store_true",
        help="Keep local dump file after upload.",
    )
    parser.add_argument(
        "--pg-database",
        default=None,
        help="Database name (default: PGDATABASE/POSTGRES_DB env).",
    )
    parser.add_argument(
        "--pg-user",
        default=None,
        help="Database user (default: PGUSER/POSTGRES_USER env).",
    )
    parser.add_argument(
        "--pg-password",
        default=None,
        help="Database password (default: PGPASSWORD/POSTGRES_PASSWORD env).",
    )
    parser.add_argument(
        "--pg-host",
        default=None,
        help="Database host (default: PGHOST/POSTGRES_HOST env).",
    )
    parser.add_argument(
        "--pg-port",
        default=None,
        help="Database port (default: PGPORT/POSTGRES_PORT env).",
    )
    parser.add_argument(
        "--pg-dump-bin",
        default="pg_dump",
        help="pg_dump binary (default: pg_dump)",
    )
    parser.add_argument(
        "--use-docker-compose",
        action="store_true",
        help="Run pg_dump inside docker compose postgres service.",
    )
    parser.add_argument(
        "--docker-compose-file",
        default="infra/docker-compose.prod.yml",
        help="docker compose file to use when --use-docker-compose is set.",
    )
    parser.add_argument(
        "--postgres-service",
        default="postgres",
        help="docker compose service name for postgres (default: postgres).",
    )
    parser.add_argument(
        "--metrics-file",
        default=os.environ.get("SKILLRA_PG_BACKUP_METRICS_FILE"),
        help="Optional Prometheus textfile collector path for backup freshness metrics.",
    )
    return parser.parse_args()


def resolve_pg_settings(args: argparse.Namespace) -> PgSettings:
    database = args.pg_database or os.environ.get("PGDATABASE") or os.environ.get("POSTGRES_DB")
    user = args.pg_user or os.environ.get("PGUSER") or os.environ.get("POSTGRES_USER")
    password = args.pg_password or os.environ.get("PGPASSWORD") or os.environ.get("POSTGRES_PASSWORD")
    host = args.pg_host or os.environ.get("PGHOST") or os.environ.get("POSTGRES_HOST")
    port = args.pg_port or os.environ.get("PGPORT") or os.environ.get("POSTGRES_PORT")

    if not database:
        raise SystemExit("Postgres database not provided. Set PGDATABASE/POSTGRES_DB or pass --pg-database.")
    if not user:
        raise SystemExit("Postgres user not provided. Set PGUSER/POSTGRES_USER or pass --pg-user.")

    return PgSettings(database=database, user=user, password=password, host=host, port=port)


def build_dump_filename(now: datetime) -> str:
    return f"skillra_pg_{now.strftime('%Y%m%d_%H%M%S')}.dump"


def backup_s3_env(env: Mapping[str, str] | None = None) -> dict[str, str]:
    """Prefer backup-scoped S3 credentials while keeping S3 client compatibility."""

    source = os.environ if env is None else env
    resolved = dict(source)
    backup_access_key = source.get("S3_BACKUP_ACCESS_KEY_ID")
    backup_secret_key = source.get("S3_BACKUP_SECRET_ACCESS_KEY")

    if bool(backup_access_key) != bool(backup_secret_key):
        raise SystemExit(
            "Set both S3_BACKUP_ACCESS_KEY_ID and S3_BACKUP_SECRET_ACCESS_KEY, "
            "or leave both unset to use S3_ACCESS_KEY_ID/S3_SECRET_ACCESS_KEY."
        )

    if backup_access_key and backup_secret_key:
        resolved["S3_ACCESS_KEY_ID"] = backup_access_key
        resolved["S3_SECRET_ACCESS_KEY"] = backup_secret_key

    return resolved


def run_pg_dump_local(settings: PgSettings, dump_path: Path, pg_dump_bin: str) -> None:
    cmd = [
        pg_dump_bin,
        "-Fc",
        "-f",
        str(dump_path),
        "-U",
        settings.user,
        "-d",
        settings.database,
    ]
    if settings.host:
        cmd.extend(["-h", settings.host])
    if settings.port:
        cmd.extend(["-p", settings.port])

    env = os.environ.copy()
    if settings.password:
        env["PGPASSWORD"] = settings.password

    subprocess.run(cmd, check=True, env=env)


def run_pg_dump_docker(
    settings: PgSettings,
    dump_path: Path,
    compose_file: str,
    service_name: str,
    pg_dump_bin: str,
) -> None:
    cmd = [
        "docker",
        "compose",
        "-f",
        compose_file,
        "exec",
        "-T",
    ]
    if settings.password:
        cmd.extend(["-e", f"PGPASSWORD={settings.password}"])
    cmd.extend(
        [
            service_name,
            pg_dump_bin,
            "-Fc",
            "-U",
            settings.user,
            "-d",
            settings.database,
        ]
    )

    with dump_path.open("wb") as handle:
        subprocess.run(cmd, check=True, stdout=handle)


def upload_backup(
    bucket: str,
    prefix: str,
    dump_path: Path,
    now: datetime,
) -> str:
    key_prefix = prefix.strip("/")
    filename = build_dump_filename(now)
    key = f"{key_prefix}/{filename}" if key_prefix else filename

    client = create_s3_client(backup_s3_env())
    put_file(client, bucket, key, dump_path)
    return f"s3://{bucket}/{key}"


def rotate_backups(
    bucket: str,
    prefix: str,
    retention_days: int,
    now: datetime,
) -> int:
    client = create_s3_client(backup_s3_env())
    paginator = client.get_paginator("list_objects_v2")
    cutoff = now - timedelta(days=retention_days)
    key_prefix = prefix.strip("/")

    keys_to_delete: list[str] = []
    for page in paginator.paginate(Bucket=bucket, Prefix=key_prefix):
        for obj in page.get("Contents", []):
            last_modified = obj.get("LastModified")
            if last_modified and last_modified < cutoff:
                keys_to_delete.append(obj["Key"])

    for key in keys_to_delete:
        try:
            client.delete_object(Bucket=bucket, Key=key)
        except (BotoCoreError, ClientError) as exc:
            raise SystemExit("Failed to delete old backups from S3") from exc
    return len(keys_to_delete)


def write_backup_metrics(
    metrics_file: Path,
    *,
    timestamp: datetime,
    dump_size_bytes: int,
    retention_deleted: int,
) -> None:
    """Write pg backup freshness metrics for node-exporter textfile collector."""

    metrics_file.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = metrics_file.with_name(f"{metrics_file.name}.tmp")
    payload = "\n".join(
        (
            f"skillra_pg_backup_last_success_timestamp_seconds {int(timestamp.timestamp())}",
            f"skillra_pg_backup_last_size_bytes {dump_size_bytes}",
            f"skillra_pg_backup_last_retention_deleted_objects {retention_deleted}",
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
    now = datetime.now(timezone.utc)
    dump_dir = Path(args.dump_dir) if args.dump_dir else Path(tempfile.gettempdir())
    dump_dir.mkdir(parents=True, exist_ok=True)
    dump_path = dump_dir / build_dump_filename(now)

    try:
        if args.use_docker_compose:
            run_pg_dump_docker(
                settings,
                dump_path,
                args.docker_compose_file,
                args.postgres_service,
                args.pg_dump_bin,
            )
        else:
            run_pg_dump_local(settings, dump_path, args.pg_dump_bin)

        s3_uri = upload_backup(bucket, args.prefix, dump_path, now)
        print(f"Uploaded backup to {s3_uri}")

        deleted = 0
        if args.retention_days is not None:
            deleted = rotate_backups(bucket, args.prefix, args.retention_days, now)
            if deleted:
                print(f"Removed {deleted} old backups from s3://{bucket}/{args.prefix}")
        if args.metrics_file:
            write_backup_metrics(
                Path(args.metrics_file),
                timestamp=now,
                dump_size_bytes=dump_path.stat().st_size,
                retention_deleted=deleted,
            )
    finally:
        if dump_path.exists() and not args.keep_local:
            dump_path.unlink()


if __name__ == "__main__":
    main()
