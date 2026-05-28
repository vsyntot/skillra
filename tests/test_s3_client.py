import io
import os
from pathlib import Path
from unittest.mock import Mock

import boto3
import pytest
from botocore.response import StreamingBody
from botocore.stub import Stubber

from skillra_pda.storage.s3_client import (
    S3ClientConfigError,
    S3ClientOperationError,
    create_s3_client,
    download_bytes,
    download_file,
    get_file,
    load_s3_settings,
    put_file,
    upload_bytes,
    upload_file,
)


def test_load_s3_settings_missing_values() -> None:
    with pytest.raises(S3ClientConfigError):
        load_s3_settings({})


def test_create_s3_client_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("S3_ENDPOINT_URL", "http://localhost:9000")
    monkeypatch.setenv("S3_REGION", "us-east-1")
    monkeypatch.setenv("S3_ACCESS_KEY_ID", "test")
    monkeypatch.setenv("S3_SECRET_ACCESS_KEY", "secret")

    client = create_s3_client(os.environ)
    assert client.meta.service_model.service_name == "s3"


def test_upload_bytes_uses_put_object() -> None:
    client = boto3.client("s3", region_name="us-east-1")
    stubber = Stubber(client)

    payload = b"hello"
    stubber.add_response(
        "put_object",
        {},
        {"Bucket": "bucket", "Key": "key", "Body": payload},
    )

    stubber.activate()
    upload_bytes(client, "bucket", "key", payload)
    stubber.deactivate()


def test_put_file_uses_upload_file(tmp_path: Path) -> None:
    client = Mock()
    payload_path = tmp_path / "payload.bin"
    payload_path.write_bytes(b"payload")

    put_file(
        client,
        "bucket",
        "key",
        payload_path,
        content_type="application/octet-stream",
        metadata={"source": "test"},
    )

    client.upload_file.assert_called_once_with(
        str(payload_path),
        "bucket",
        "key",
        ExtraArgs={"ContentType": "application/octet-stream", "Metadata": {"source": "test"}},
    )


def test_upload_file_is_backward_compatible(tmp_path: Path) -> None:
    client = Mock()
    payload_path = tmp_path / "payload.bin"
    payload_path.write_bytes(b"payload")

    upload_file(client, "bucket", "key", payload_path, content_type="application/octet-stream")

    client.upload_file.assert_called_once_with(
        str(payload_path),
        "bucket",
        "key",
        ExtraArgs={"ContentType": "application/octet-stream"},
    )


def test_download_bytes() -> None:
    client = boto3.client("s3", region_name="us-east-1")
    stubber = Stubber(client)

    payload = b"payload"
    body = StreamingBody(io.BytesIO(payload), len(payload))
    stubber.add_response(
        "get_object",
        {"Body": body},
        {"Bucket": "bucket", "Key": "key"},
    )

    stubber.activate()
    assert download_bytes(client, "bucket", "key") == payload
    stubber.deactivate()


def test_download_bytes_handles_errors() -> None:
    client = boto3.client("s3", region_name="us-east-1")
    stubber = Stubber(client)

    stubber.add_client_error("get_object", service_error_code="NoSuchKey")

    stubber.activate()
    with pytest.raises(S3ClientOperationError):
        download_bytes(client, "bucket", "missing")
    stubber.deactivate()


def test_get_file_uses_download_file(tmp_path: Path) -> None:
    client = Mock()
    destination = tmp_path / "out" / "file.bin"

    get_file(client, "bucket", "key", destination)

    client.download_file.assert_called_once_with("bucket", "key", str(destination))
    assert destination.parent.exists()


def test_download_file_is_backward_compatible(tmp_path: Path) -> None:
    client = Mock()
    destination = tmp_path / "out" / "file.bin"

    download_file(client, "bucket", "key", destination)

    client.download_file.assert_called_once_with("bucket", "key", str(destination))
