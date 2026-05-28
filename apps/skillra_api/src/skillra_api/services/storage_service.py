"""Async S3/MinIO storage wrapper."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any

from skillra_api.config import Settings

try:  # boto3 is installed via the base runtime lock.
    import boto3
except ModuleNotFoundError:  # pragma: no cover - exercised only in broken images
    boto3 = None  # type: ignore[assignment]

try:
    from botocore.config import Config as BotoConfig
except ModuleNotFoundError:  # pragma: no cover - boto3 normally brings botocore
    BotoConfig = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)


class StorageNotConfiguredError(RuntimeError):
    """Raised when an S3 operation is requested without MinIO settings."""


class StorageService:
    """Small async S3 client wrapper with methods used by API endpoints."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._semaphores: dict[int, asyncio.Semaphore] = {}

    def _client(self) -> Any:
        self._ensure_configured()
        if boto3 is None:
            raise StorageNotConfiguredError("boto3 is not installed")
        kwargs: dict[str, Any] = {
            "endpoint_url": self._settings.minio_endpoint_url,
            "aws_access_key_id": self._settings.minio_access_key,
            "aws_secret_access_key": self._settings.minio_secret_key,
            "region_name": "us-east-1",
        }
        if BotoConfig is not None:
            timeout = float(self._settings.storage_s3_timeout_seconds)
            kwargs["config"] = BotoConfig(
                connect_timeout=timeout,
                read_timeout=timeout,
                retries={"max_attempts": int(self._settings.storage_s3_max_attempts), "mode": "standard"},
            )
        return boto3.client("s3", **kwargs)

    async def _call(self, method_name: str, **kwargs: Any) -> Any:
        attempts = int(self._settings.storage_s3_max_attempts)
        timeout = float(self._settings.storage_s3_timeout_seconds)
        last_exc: BaseException | None = None

        for attempt in range(1, attempts + 1):
            client = self._client()
            try:
                method = getattr(client, method_name)
                async with self._semaphore():
                    return await asyncio.wait_for(asyncio.to_thread(method, **kwargs), timeout=timeout)
            except Exception as exc:  # noqa: BLE001
                last_exc = exc
                if attempt >= attempts:
                    raise
                logger.warning(
                    "S3 operation failed, retrying",
                    extra={"method": method_name, "attempt": attempt, "max_attempts": attempts},
                )
                await asyncio.sleep(min(0.2 * attempt, 1.0))
            finally:
                close = getattr(client, "close", None)
                if close is not None:
                    await asyncio.to_thread(close)

        if last_exc is not None:  # pragma: no cover
            raise last_exc
        raise RuntimeError("S3 operation failed without an exception")  # pragma: no cover

    def _semaphore(self) -> asyncio.Semaphore:
        loop = asyncio.get_running_loop()
        key = id(loop)
        semaphore = self._semaphores.get(key)
        if semaphore is None:
            semaphore = asyncio.Semaphore(int(self._settings.storage_s3_max_concurrency))
            self._semaphores[key] = semaphore
        return semaphore

    async def upload_resume(self, telegram_user_id: int, file_bytes: bytes, content_type: str) -> str:
        """Upload a resume and return its S3 key."""

        s3_key = self._object_key("resumes", telegram_user_id, "pdf")
        await self._call(
            "put_object",
            Bucket=self._settings.minio_bucket_resumes,
            Key=s3_key,
            Body=file_bytes,
            ContentType=content_type,
        )
        return s3_key

    async def get_resume_presigned_url(self, s3_key: str, ttl: int = 3600) -> str:
        """Generate a presigned resume download URL."""

        result = await self._call(
            "generate_presigned_url",
            ClientMethod="get_object",
            Params={"Bucket": self._settings.minio_bucket_resumes, "Key": s3_key},
            ExpiresIn=ttl,
        )
        return str(result)

    async def delete_resume(self, s3_key: str) -> None:
        """Delete all current and noncurrent versions of a resume object."""

        await self._delete_object_all_versions(self._settings.minio_bucket_resumes, s3_key)

    async def upload_report_pdf(self, telegram_user_id: int, pdf_bytes: bytes) -> str:
        """Upload a generated PDF report and return its S3 key."""

        s3_key = self._object_key("reports", telegram_user_id, "pdf")
        await self._call(
            "put_object",
            Bucket=self._settings.minio_bucket_reports,
            Key=s3_key,
            Body=pdf_bytes,
            ContentType="application/pdf",
        )
        return s3_key

    async def delete_report_pdf(self, s3_key: str) -> None:
        """Delete all current and noncurrent versions of a generated report."""

        await self._delete_object_all_versions(self._settings.minio_bucket_reports, s3_key)

    async def _delete_object_all_versions(self, bucket: str, s3_key: str) -> None:
        """Delete a key from unversioned and versioned S3 buckets.

        Versioned buckets retain noncurrent versions and delete markers after a
        plain DeleteObject. PII-bearing objects must remove every version when
        the bucket is versioned.
        """

        versions = await self._list_object_versions(bucket, s3_key)
        if not versions:
            await self._call("delete_object", Bucket=bucket, Key=s3_key)
            return

        for version in versions:
            await self._call("delete_object", Bucket=bucket, Key=version["Key"], VersionId=version["VersionId"])

    async def _list_object_versions(self, bucket: str, s3_key: str) -> list[dict[str, str]]:
        marker_args: dict[str, str] = {}
        objects: list[dict[str, str]] = []
        while True:
            response = await self._call("list_object_versions", Bucket=bucket, Prefix=s3_key, **marker_args)
            for section in ("Versions", "DeleteMarkers"):
                for item in response.get(section, []) if isinstance(response, dict) else []:
                    if not isinstance(item, dict) or item.get("Key") != s3_key:
                        continue
                    version_id = item.get("VersionId")
                    if version_id:
                        objects.append({"Key": s3_key, "VersionId": str(version_id)})

            if not isinstance(response, dict) or not response.get("IsTruncated"):
                break
            marker_args = {}
            next_key_marker = response.get("NextKeyMarker")
            next_version_marker = response.get("NextVersionIdMarker")
            if next_key_marker:
                marker_args["KeyMarker"] = str(next_key_marker)
            if next_version_marker:
                marker_args["VersionIdMarker"] = str(next_version_marker)
            if not marker_args:
                break
        return objects

    def _ensure_configured(self) -> None:
        if not (
            self._settings.minio_endpoint_url and self._settings.minio_access_key and self._settings.minio_secret_key
        ):
            raise StorageNotConfiguredError("MinIO settings are not configured")

    @staticmethod
    def _object_key(prefix: str, telegram_user_id: int, extension: str) -> str:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        return f"{prefix}/{telegram_user_id}/{stamp}.{extension}"
