from botocore.exceptions import ClientError

from scripts.smoke_minio_scoped_access import (
    MinioScopeSmokeError,
    RoleScope,
    assert_denied,
    is_access_denied,
    load_role_scopes,
    validate_distinct_roles,
)


def _client_error(code: str, status: int) -> ClientError:
    return ClientError(
        {"Error": {"Code": code}, "ResponseMetadata": {"HTTPStatusCode": status}},
        "PutObject",
    )


class _DeniedClient:
    def put_object(self, **kwargs: object) -> None:
        raise _client_error("AccessDenied", 403)


class _AllowedClient:
    def __init__(self) -> None:
        self.deleted = False

    def put_object(self, **kwargs: object) -> None:
        return None

    def delete_object(self, **kwargs: object) -> None:
        self.deleted = True


def test_load_role_scopes_maps_buckets_by_role() -> None:
    scopes = load_role_scopes(
        {
            "MINIO_ACCESS_KEY": "api",
            "MINIO_SECRET_KEY": "api-secret",
            "S3_ACCESS_KEY_ID": "pipeline",
            "S3_SECRET_ACCESS_KEY": "pipeline-secret",
            "S3_BACKUP_ACCESS_KEY_ID": "backup",
            "S3_BACKUP_SECRET_ACCESS_KEY": "backup-secret",
            "MINIO_BUCKET_RESUMES": "resumes",
            "MINIO_BUCKET_REPORTS": "reports",
            "S3_BUCKET_RAW_HH": "raw",
            "S3_BUCKET_PROCESSED": "processed",
            "S3_BUCKET_BACKUPS": "backups",
        }
    )

    assert scopes[0].name == "api"
    assert scopes[0].allowed_buckets == ("resumes", "reports")
    assert scopes[0].denied_buckets == ("raw", "processed", "backups")
    assert scopes[1].allowed_buckets == ("raw", "processed")
    assert scopes[2].allowed_buckets == ("backups",)


def test_validate_distinct_roles_rejects_duplicate_access_key() -> None:
    scopes = (
        RoleScope("api", "same", "secret", ("resumes",), ("raw",)),
        RoleScope("pipeline", "same", "secret", ("raw",), ("resumes",)),
    )

    try:
        validate_distinct_roles(scopes)
    except MinioScopeSmokeError as exc:
        assert "api/pipeline" in str(exc)
    else:
        raise AssertionError("duplicate access keys must fail")


def test_is_access_denied_accepts_minio_and_s3_denials() -> None:
    assert is_access_denied(_client_error("AccessDenied", 403))
    assert is_access_denied(_client_error("SignatureDoesNotMatch", 403))
    assert not is_access_denied(_client_error("NoSuchBucket", 404))


def test_assert_denied_passes_on_access_denied() -> None:
    scope = RoleScope("api", "api", "secret", ("resumes",), ("raw",))

    assert_denied(_DeniedClient(), scope, "raw", "key", b"payload")


def test_assert_denied_fails_when_put_succeeds() -> None:
    scope = RoleScope("api", "api", "secret", ("resumes",), ("raw",))
    client = _AllowedClient()

    try:
        assert_denied(client, scope, "raw", "key", b"payload")
    except MinioScopeSmokeError as exc:
        assert "can write forbidden bucket" in str(exc)
        assert client.deleted
    else:
        raise AssertionError("successful forbidden write must fail")
