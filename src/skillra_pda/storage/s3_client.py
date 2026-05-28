"""S3 client helpers for MinIO/S3 operations."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

import boto3
from botocore.exceptions import BotoCoreError, ClientError


@dataclass(frozen=True)
class S3ClientSettings:
    """Settings for building an S3 client from environment variables."""

    endpoint_url: str
    region_name: str
    access_key_id: str
    secret_access_key: str


class S3ClientError(RuntimeError):
    """Base error for S3 client helpers."""


class S3ClientConfigError(S3ClientError):
    """Raised when required S3 configuration is missing."""


class S3ClientOperationError(S3ClientError):
    """Raised when an S3 operation fails."""


def load_s3_settings(env: Mapping[str, str] | None = None) -> S3ClientSettings:
    """Load S3 settings from the provided environment mapping."""

    if env is None:
        env = os.environ

    required_keys = {
        "S3_ENDPOINT_URL": None,
        "S3_REGION": None,
        "S3_ACCESS_KEY_ID": None,
        "S3_SECRET_ACCESS_KEY": None,
    }

    for key in required_keys:
        value = env.get(key)
        if value:
            required_keys[key] = value

    missing = [key for key, value in required_keys.items() if not value]
    if missing:
        raise S3ClientConfigError("Missing S3 configuration values: " + ", ".join(missing))

    return S3ClientSettings(
        endpoint_url=required_keys["S3_ENDPOINT_URL"],
        region_name=required_keys["S3_REGION"],
        access_key_id=required_keys["S3_ACCESS_KEY_ID"],
        secret_access_key=required_keys["S3_SECRET_ACCESS_KEY"],
    )


def create_s3_client(env: Mapping[str, str] | None = None) -> boto3.client:
    """Create a boto3 S3 client using environment configuration."""

    settings = load_s3_settings(env)
    session = boto3.session.Session()
    return session.client(
        "s3",
        endpoint_url=settings.endpoint_url,
        region_name=settings.region_name,
        aws_access_key_id=settings.access_key_id,
        aws_secret_access_key=settings.secret_access_key,
    )


def upload_bytes(
    client: boto3.client,
    bucket: str,
    key: str,
    payload: bytes,
    *,
    content_type: str | None = None,
) -> None:
    """Upload raw bytes to S3 using put_object."""

    params: dict[str, object] = {"Bucket": bucket, "Key": key, "Body": payload}
    if content_type:
        params["ContentType"] = content_type

    try:
        client.put_object(**params)
    except (BotoCoreError, ClientError) as exc:
        raise S3ClientOperationError(f"Failed to upload bytes to s3://{bucket}/{key}") from exc


def put_file(
    client: boto3.client,
    bucket: str,
    key: str,
    local_path: str | Path,
    *,
    content_type: str | None = None,
    metadata: Mapping[str, str] | None = None,
) -> None:
    """Upload a local file to S3 using multipart uploads."""

    source = Path(local_path)
    extra_args: dict[str, object] = {}
    if content_type:
        extra_args["ContentType"] = content_type
    if metadata:
        extra_args["Metadata"] = dict(metadata)

    try:
        if extra_args:
            client.upload_file(str(source), bucket, key, ExtraArgs=extra_args)
        else:
            client.upload_file(str(source), bucket, key)
    except (BotoCoreError, ClientError) as exc:
        raise S3ClientOperationError(f"Failed to upload file to s3://{bucket}/{key}") from exc


def upload_file(
    client: boto3.client,
    bucket: str,
    key: str,
    source: str | Path,
    *,
    content_type: str | None = None,
) -> None:
    """Upload a local file to S3."""

    put_file(client, bucket, key, source, content_type=content_type)


def download_bytes(client: boto3.client, bucket: str, key: str) -> bytes:
    """Download an object from S3 and return its bytes."""

    try:
        response = client.get_object(Bucket=bucket, Key=key)
    except (BotoCoreError, ClientError) as exc:
        raise S3ClientOperationError(f"Failed to download s3://{bucket}/{key}") from exc

    body = response["Body"]
    return body.read()


def get_file(client: boto3.client, bucket: str, key: str, local_path: str | Path) -> None:
    """Download an object from S3 to a local file."""

    target = Path(local_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        client.download_file(bucket, key, str(target))
    except (BotoCoreError, ClientError) as exc:
        raise S3ClientOperationError(f"Failed to download s3://{bucket}/{key}") from exc


def download_file(client: boto3.client, bucket: str, key: str, destination: str | Path) -> None:
    """Download an object from S3 and save it locally."""

    get_file(client, bucket, key, destination)
