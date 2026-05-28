"""Create required MinIO/S3 buckets if they do not exist."""

from __future__ import annotations

import argparse
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

import boto3
from botocore.exceptions import ClientError


DEFAULT_BUCKET_ENV_KEYS = (
    "S3_BUCKET_RAW_HH",
    "S3_BUCKET_PROCESSED",
    "S3_BUCKET_BACKUPS",
    "MINIO_BUCKET_RESUMES",
    "MINIO_BUCKET_REPORTS",
)


@dataclass(frozen=True)
class MinioInitSettings:
    endpoint_url: str
    region_name: str
    access_key_id: str
    secret_access_key: str
    buckets: tuple[str, ...]


def first_env(env: Mapping[str, str], *keys: str) -> str | None:
    for key in keys:
        value = env.get(key)
        if value:
            return value
    return None


def unique_non_empty(values: list[str]) -> tuple[str, ...]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        normalized = value.strip()
        if normalized and normalized not in seen:
            seen.add(normalized)
            result.append(normalized)
    return tuple(result)


def load_env_file(path: Path) -> dict[str, str]:
    if not path.exists():
        raise SystemExit(f"Env file not found: {path}")

    values: dict[str, str] = {}
    for line_number, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            raise SystemExit(f"Invalid env line in {path}:{line_number}")
        key, value = line.split("=", 1)
        key = key.strip()
        if not key:
            raise SystemExit(f"Invalid empty env key in {path}:{line_number}")
        values[key] = value.strip().strip("'\"")
    return values


def load_effective_env(env_file: str | None) -> dict[str, str]:
    env: dict[str, str] = {}
    if env_file:
        env.update(load_env_file(Path(env_file)))
    else:
        for candidate in (Path(".env.prod"), Path(".env")):
            if candidate.exists():
                env.update(load_env_file(candidate))
                break
    env.update(os.environ)
    return env


def load_settings(args: argparse.Namespace, env: Mapping[str, str]) -> MinioInitSettings:
    endpoint_url = args.endpoint_url or first_env(env, "MINIO_ENDPOINT_URL", "S3_ENDPOINT_URL")
    region_name = args.region or env.get("S3_REGION") or "us-east-1"
    access_key_id = args.access_key or first_env(env, "MINIO_ROOT_USER", "MINIO_ACCESS_KEY", "S3_ACCESS_KEY_ID")
    secret_access_key = args.secret_key or first_env(
        env,
        "MINIO_ROOT_PASSWORD",
        "MINIO_SECRET_KEY",
        "S3_SECRET_ACCESS_KEY",
    )

    bucket_values = list(args.bucket)
    for key in DEFAULT_BUCKET_ENV_KEYS:
        value = env.get(key)
        if value:
            bucket_values.append(value)
    buckets = unique_non_empty(bucket_values)

    missing = []
    if not endpoint_url:
        missing.append("MINIO_ENDPOINT_URL or S3_ENDPOINT_URL")
    if not access_key_id:
        missing.append("MINIO_ACCESS_KEY, S3_ACCESS_KEY_ID, or MINIO_ROOT_USER")
    if not secret_access_key:
        missing.append("MINIO_SECRET_KEY, S3_SECRET_ACCESS_KEY, or MINIO_ROOT_PASSWORD")
    if not buckets:
        missing.append("at least one bucket env or --bucket")
    if missing:
        raise SystemExit("Missing MinIO configuration: " + ", ".join(missing))

    return MinioInitSettings(
        endpoint_url=endpoint_url,
        region_name=region_name,
        access_key_id=access_key_id,
        secret_access_key=secret_access_key,
        buckets=buckets,
    )


def create_client(settings: MinioInitSettings):
    session = boto3.session.Session()
    return session.client(
        "s3",
        endpoint_url=settings.endpoint_url,
        region_name=settings.region_name,
        aws_access_key_id=settings.access_key_id,
        aws_secret_access_key=settings.secret_access_key,
    )


def bucket_exists(client, bucket: str) -> bool:
    try:
        client.head_bucket(Bucket=bucket)
    except ClientError as exc:
        code = str(exc.response.get("Error", {}).get("Code", ""))
        if code in {"404", "NoSuchBucket", "NotFound"}:
            return False
        raise
    return True


def create_bucket(client, bucket: str, region_name: str) -> None:
    if region_name == "us-east-1":
        client.create_bucket(Bucket=bucket)
        return
    client.create_bucket(
        Bucket=bucket,
        CreateBucketConfiguration={"LocationConstraint": region_name},
    )


def ensure_buckets(settings: MinioInitSettings, *, dry_run: bool) -> None:
    if dry_run:
        for bucket in settings.buckets:
            print(f"[dry-run] ensure bucket exists: s3://{bucket}")
        return

    client = create_client(settings)
    for bucket in settings.buckets:
        if bucket_exists(client, bucket):
            print(f"Bucket exists: s3://{bucket}")
            continue
        if dry_run:
            print(f"[dry-run] create bucket: s3://{bucket}")
            continue
        create_bucket(client, bucket, settings.region_name)
        print(f"Created bucket: s3://{bucket}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Create Skillra MinIO buckets.")
    parser.add_argument("--endpoint-url", default=None, help="Override MINIO_ENDPOINT_URL/S3_ENDPOINT_URL.")
    parser.add_argument("--region", default=None, help="Override S3_REGION (default: us-east-1).")
    parser.add_argument("--access-key", default=None, help="Override MINIO_ACCESS_KEY/S3_ACCESS_KEY_ID.")
    parser.add_argument("--secret-key", default=None, help="Override MINIO_SECRET_KEY/S3_SECRET_ACCESS_KEY.")
    parser.add_argument("--env-file", default=None, help="Load settings from an env file (default: .env.prod or .env).")
    parser.add_argument("--bucket", action="append", default=[], help="Additional bucket to create.")
    parser.add_argument("--dry-run", action="store_true", help="Print planned changes without creating buckets.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    settings = load_settings(args, load_effective_env(args.env_file))
    ensure_buckets(settings, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
