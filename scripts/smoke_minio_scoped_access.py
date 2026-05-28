#!/usr/bin/env python3
"""Verify MinIO least-privilege policies for API, pipeline and backup users."""

from __future__ import annotations

import argparse
import os
import sys
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Sequence

from botocore.exceptions import ClientError

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from skillra_pda.storage.s3_client import create_s3_client


ACCESS_DENIED_CODES = {"AccessDenied", "AllAccessDisabled", "InvalidAccessKeyId", "SignatureDoesNotMatch"}


class MinioScopeSmokeError(RuntimeError):
    """Raised when MinIO scoped access smoke fails."""


@dataclass(frozen=True)
class RoleScope:
    name: str
    access_key_id: str
    secret_access_key: str
    allowed_buckets: tuple[str, ...]
    denied_buckets: tuple[str, ...]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Smoke-test scoped MinIO/S3 users and bucket policies.")
    parser.add_argument("--endpoint-url", default=None, help="Override S3 endpoint URL.")
    parser.add_argument("--region", default=None, help="Override S3 region.")
    parser.add_argument("--prefix", default="scope-smoke", help="Object key prefix for temporary smoke objects.")
    return parser.parse_args()


def _required(env: Mapping[str, str], key: str) -> str:
    value = env.get(key)
    if not value:
        raise SystemExit(f"{key} is required for MinIO scoped access smoke.")
    return value


def _endpoint_url(env: Mapping[str, str], override: str | None) -> str:
    return override or env.get("S3_ENDPOINT_URL") or env.get("MINIO_ENDPOINT_URL") or ""


def load_role_scopes(env: Mapping[str, str]) -> tuple[RoleScope, ...]:
    resumes_bucket = _required(env, "MINIO_BUCKET_RESUMES")
    reports_bucket = _required(env, "MINIO_BUCKET_REPORTS")
    raw_bucket = _required(env, "S3_BUCKET_RAW_HH")
    processed_bucket = _required(env, "S3_BUCKET_PROCESSED")
    backup_bucket = _required(env, "S3_BUCKET_BACKUPS")

    return (
        RoleScope(
            name="api",
            access_key_id=_required(env, "MINIO_ACCESS_KEY"),
            secret_access_key=_required(env, "MINIO_SECRET_KEY"),
            allowed_buckets=(resumes_bucket, reports_bucket),
            denied_buckets=(raw_bucket, processed_bucket, backup_bucket),
        ),
        RoleScope(
            name="pipeline",
            access_key_id=_required(env, "S3_ACCESS_KEY_ID"),
            secret_access_key=_required(env, "S3_SECRET_ACCESS_KEY"),
            allowed_buckets=(raw_bucket, processed_bucket),
            denied_buckets=(resumes_bucket, reports_bucket, backup_bucket),
        ),
        RoleScope(
            name="backup",
            access_key_id=_required(env, "S3_BACKUP_ACCESS_KEY_ID"),
            secret_access_key=_required(env, "S3_BACKUP_SECRET_ACCESS_KEY"),
            allowed_buckets=(backup_bucket,),
            denied_buckets=(resumes_bucket, reports_bucket, raw_bucket, processed_bucket),
        ),
    )


def validate_distinct_roles(scopes: Sequence[RoleScope]) -> None:
    seen: dict[str, str] = {}
    duplicates: list[str] = []
    for scope in scopes:
        previous = seen.get(scope.access_key_id)
        if previous:
            duplicates.append(f"{previous}/{scope.name}")
        else:
            seen[scope.access_key_id] = scope.name

    if duplicates:
        raise MinioScopeSmokeError("MinIO role access keys must be distinct: " + ", ".join(duplicates))


def role_client(scope: RoleScope, endpoint_url: str, region: str):
    return create_s3_client(
        {
            "S3_ENDPOINT_URL": endpoint_url,
            "S3_REGION": region,
            "S3_ACCESS_KEY_ID": scope.access_key_id,
            "S3_SECRET_ACCESS_KEY": scope.secret_access_key,
        }
    )


def is_access_denied(exc: ClientError) -> bool:
    code = str(exc.response.get("Error", {}).get("Code", ""))
    status = exc.response.get("ResponseMetadata", {}).get("HTTPStatusCode")
    return code in ACCESS_DENIED_CODES or status in {401, 403}


def assert_allowed(client, scope: RoleScope, bucket: str, key: str, payload: bytes) -> None:
    try:
        client.put_object(Bucket=bucket, Key=key, Body=payload)
        response = client.get_object(Bucket=bucket, Key=key)
        body = response["Body"].read()
        if body != payload:
            raise MinioScopeSmokeError(f"{scope.name} read unexpected payload from {bucket}")
    except ClientError as exc:
        raise MinioScopeSmokeError(f"{scope.name} cannot read/write allowed bucket {bucket}") from exc
    finally:
        try:
            client.delete_object(Bucket=bucket, Key=key)
        except ClientError:
            pass


def assert_denied(client, scope: RoleScope, bucket: str, key: str, payload: bytes) -> None:
    try:
        client.put_object(Bucket=bucket, Key=key, Body=payload)
    except ClientError as exc:
        if is_access_denied(exc):
            return
        raise MinioScopeSmokeError(f"{scope.name} got non-deny error for forbidden bucket {bucket}") from exc

    try:
        client.delete_object(Bucket=bucket, Key=key)
    except ClientError:
        pass
    raise MinioScopeSmokeError(f"{scope.name} can write forbidden bucket {bucket}")


def run_scope_smoke(env: Mapping[str, str], *, endpoint_url: str, region: str, prefix: str) -> None:
    if not endpoint_url:
        raise SystemExit("S3_ENDPOINT_URL or MINIO_ENDPOINT_URL is required for MinIO scoped access smoke.")

    scopes = load_role_scopes(env)
    validate_distinct_roles(scopes)
    payload = b"skillra-minio-scope-smoke"
    run_id = uuid.uuid4().hex

    for scope in scopes:
        client = role_client(scope, endpoint_url, region)
        for bucket in scope.allowed_buckets:
            key = f"{prefix}/{run_id}/{scope.name}/allowed/{bucket}.txt"
            assert_allowed(client, scope, bucket, key, payload)
        for bucket in scope.denied_buckets:
            key = f"{prefix}/{run_id}/{scope.name}/denied/{bucket}.txt"
            assert_denied(client, scope, bucket, key, payload)
        print(f"[minio-scope-smoke] OK: {scope.name} scope enforced")


def main() -> None:
    args = parse_args()
    env = os.environ
    run_scope_smoke(
        env,
        endpoint_url=_endpoint_url(env, args.endpoint_url),
        region=args.region or env.get("S3_REGION") or "us-east-1",
        prefix=args.prefix.strip("/") or "scope-smoke",
    )


if __name__ == "__main__":
    main()
