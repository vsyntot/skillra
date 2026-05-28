"""Tests for API S3/MinIO storage wrapper."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from skillra_api.config import Settings
from skillra_api.services import storage_service
from skillra_api.services.storage_service import StorageNotConfiguredError, StorageService


class FakeS3Client:
    def __init__(
        self,
        *,
        object_versions: list[dict[str, Any]] | None = None,
        delete_markers: list[dict[str, Any]] | None = None,
        delete_error: Exception | None = None,
    ) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.closed = False
        self.object_versions = object_versions or []
        self.delete_markers = delete_markers or []
        self.delete_error = delete_error

    def put_object(self, **kwargs: Any) -> None:
        self.calls.append(("put_object", kwargs))

    def generate_presigned_url(self, **kwargs: Any) -> str:
        self.calls.append(("generate_presigned_url", kwargs))
        return "https://minio.example/presigned"

    def delete_object(self, **kwargs: Any) -> None:
        self.calls.append(("delete_object", kwargs))
        if self.delete_error is not None:
            raise self.delete_error

    def list_object_versions(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(("list_object_versions", kwargs))
        prefix = kwargs["Prefix"]
        return {
            "Versions": [item for item in self.object_versions if str(item.get("Key", "")).startswith(prefix)],
            "DeleteMarkers": [item for item in self.delete_markers if str(item.get("Key", "")).startswith(prefix)],
            "IsTruncated": False,
        }

    def close(self) -> None:
        self.closed = True


class FlakyS3Client(FakeS3Client):
    def __init__(self) -> None:
        super().__init__()
        self.failures_remaining = 1

    def put_object(self, **kwargs: Any) -> None:
        if self.failures_remaining > 0:
            self.failures_remaining -= 1
            raise TimeoutError("temporary timeout")
        super().put_object(**kwargs)


class FakeBoto3:
    def __init__(self, client: FakeS3Client) -> None:
        self.client_instance = client
        self.client_kwargs: dict[str, Any] | None = None

    def client(self, service_name: str, **kwargs: Any) -> FakeS3Client:
        assert service_name == "s3"
        self.client_kwargs = kwargs
        return self.client_instance


def _settings() -> Settings:
    return Settings(
        log_level="CRITICAL",
        api_token="test",
        minio_endpoint_url="http://minio:9000",
        minio_access_key="access",
        minio_secret_key="secret",
        minio_bucket_resumes="resumes",
        minio_bucket_reports="reports",
    )


def test_storage_service_uses_boto3_runtime_client(monkeypatch: pytest.MonkeyPatch) -> None:
    client = FakeS3Client()
    fake_boto3 = FakeBoto3(client)
    monkeypatch.setattr(storage_service, "boto3", fake_boto3)

    service = StorageService(_settings())

    resume_key = asyncio.run(service.upload_resume(42, b"%PDF", "application/pdf"))
    presigned_url = asyncio.run(service.get_resume_presigned_url(resume_key, ttl=600))
    asyncio.run(service.delete_resume(resume_key))
    report_key = asyncio.run(service.upload_report_pdf(42, b"report"))

    assert resume_key.startswith("resumes/42/")
    assert resume_key.endswith(".pdf")
    assert report_key.startswith("reports/42/")
    assert presigned_url == "https://minio.example/presigned"
    client_kwargs = dict(fake_boto3.client_kwargs or {})
    config = client_kwargs.pop("config", None)
    assert client_kwargs == {
        "endpoint_url": "http://minio:9000",
        "aws_access_key_id": "access",
        "aws_secret_access_key": "secret",
        "region_name": "us-east-1",
    }
    assert config is not None
    assert config.connect_timeout == 10.0
    assert config.read_timeout == 10.0
    assert client.calls[0] == (
        "put_object",
        {"Bucket": "resumes", "Key": resume_key, "Body": b"%PDF", "ContentType": "application/pdf"},
    )
    assert client.calls[1] == (
        "generate_presigned_url",
        {"ClientMethod": "get_object", "Params": {"Bucket": "resumes", "Key": resume_key}, "ExpiresIn": 600},
    )
    assert client.calls[2] == (
        "list_object_versions",
        {"Bucket": "resumes", "Prefix": resume_key},
    )
    assert client.calls[3] == ("delete_object", {"Bucket": "resumes", "Key": resume_key})
    assert client.calls[4] == (
        "put_object",
        {"Bucket": "reports", "Key": report_key, "Body": b"report", "ContentType": "application/pdf"},
    )
    assert client.closed is True


def test_storage_service_retries_transient_failures(monkeypatch: pytest.MonkeyPatch) -> None:
    client = FlakyS3Client()
    fake_boto3 = FakeBoto3(client)
    monkeypatch.setattr(storage_service, "boto3", fake_boto3)

    service = StorageService(_settings())

    resume_key = asyncio.run(service.upload_resume(42, b"%PDF", "application/pdf"))

    assert resume_key.startswith("resumes/42/")
    assert client.calls == [
        ("put_object", {"Bucket": "resumes", "Key": resume_key, "Body": b"%PDF", "ContentType": "application/pdf"})
    ]


def test_storage_service_requires_minio_settings() -> None:
    service = StorageService(
        Settings(
            log_level="CRITICAL",
            api_token="test",
            minio_endpoint_url=None,
            minio_access_key=None,
            minio_secret_key=None,
        )
    )

    with pytest.raises(StorageNotConfiguredError, match="MinIO settings"):
        asyncio.run(service.upload_resume(42, b"%PDF", "application/pdf"))


def test_storage_service_deletes_all_resume_versions(monkeypatch: pytest.MonkeyPatch) -> None:
    client = FakeS3Client(
        object_versions=[
            {"Key": "resumes/42/a.pdf", "VersionId": "v3"},
            {"Key": "resumes/42/a.pdf", "VersionId": "v2"},
            {"Key": "resumes/42/a.pdf.extra", "VersionId": "ignored"},
        ],
        delete_markers=[{"Key": "resumes/42/a.pdf", "VersionId": "delete-marker"}],
    )
    monkeypatch.setattr(storage_service, "boto3", FakeBoto3(client))

    service = StorageService(_settings())

    asyncio.run(service.delete_resume("resumes/42/a.pdf"))

    assert client.calls == [
        ("list_object_versions", {"Bucket": "resumes", "Prefix": "resumes/42/a.pdf"}),
        (
            "delete_object",
            {"Bucket": "resumes", "Key": "resumes/42/a.pdf", "VersionId": "v3"},
        ),
        (
            "delete_object",
            {"Bucket": "resumes", "Key": "resumes/42/a.pdf", "VersionId": "v2"},
        ),
        (
            "delete_object",
            {"Bucket": "resumes", "Key": "resumes/42/a.pdf", "VersionId": "delete-marker"},
        ),
    ]


def test_storage_service_deletes_report_versions(monkeypatch: pytest.MonkeyPatch) -> None:
    client = FakeS3Client(object_versions=[{"Key": "reports/42/a.pdf", "VersionId": "v1"}])
    monkeypatch.setattr(storage_service, "boto3", FakeBoto3(client))

    service = StorageService(_settings())

    asyncio.run(service.delete_report_pdf("reports/42/a.pdf"))

    assert client.calls[-1] == ("delete_object", {"Bucket": "reports", "Key": "reports/42/a.pdf", "VersionId": "v1"})


def test_storage_service_surfaces_versioned_delete_failures(monkeypatch: pytest.MonkeyPatch) -> None:
    client = FakeS3Client(
        object_versions=[{"Key": "resumes/42/a.pdf", "VersionId": "v1"}],
        delete_error=RuntimeError("AccessDenied"),
    )
    monkeypatch.setattr(storage_service, "boto3", FakeBoto3(client))

    service = StorageService(_settings())

    with pytest.raises(RuntimeError, match="AccessDenied"):
        asyncio.run(service.delete_resume("resumes/42/a.pdf"))
