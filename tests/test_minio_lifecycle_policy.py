from __future__ import annotations

from typing import Any

import pytest
from botocore.exceptions import ClientError

from scripts.minio_lifecycle_policy import (
    ABORT_INCOMPLETE_MULTIPART_DAYS,
    BucketPolicy,
    RetentionTarget,
    add_lifecycle_content_md5,
    apply_policies,
    build_bucket_policies,
    build_policy_document,
    check_policies,
    lifecycle_has_destructive_actions,
    lifecycle_has_required_safe_rule,
    merge_safe_lifecycle,
)


class FakeS3LifecycleClient:
    def __init__(
        self,
        *,
        versioning: dict[str, str] | None = None,
        lifecycle: dict[str, dict[str, Any]] | None = None,
    ) -> None:
        self.versioning = versioning or {}
        self.lifecycle = lifecycle or {}
        self.put_versioning_calls: list[dict[str, Any]] = []
        self.put_lifecycle_calls: list[dict[str, Any]] = []

    def head_bucket(self, *, Bucket: str) -> dict[str, Any]:
        return {}

    def get_bucket_versioning(self, *, Bucket: str) -> dict[str, str]:
        status = self.versioning.get(Bucket)
        return {"Status": status} if status else {}

    def get_bucket_lifecycle_configuration(self, *, Bucket: str) -> dict[str, Any]:
        if Bucket not in self.lifecycle:
            raise ClientError({"Error": {"Code": "NoSuchLifecycleConfiguration"}}, "GetBucketLifecycleConfiguration")
        return self.lifecycle[Bucket]

    def put_bucket_versioning(self, **kwargs: Any) -> None:
        self.put_versioning_calls.append(kwargs)

    def put_bucket_lifecycle_configuration(self, **kwargs: Any) -> None:
        self.put_lifecycle_calls.append(kwargs)


def make_policy(bucket: str = "skillra-raw") -> BucketPolicy:
    return BucketPolicy(
        logical_name="raw_hh",
        bucket_env_key="S3_BUCKET_RAW_HH",
        bucket=bucket,
        versioning_required=True,
        data_classification="raw",
        retention_targets=(
            RetentionTarget(
                prefix="runs/",
                target="retain indefinitely",
                enforcement="documented",
                rationale="immutable lineage",
            ),
        ),
    )


def test_build_policy_document_keeps_runtime_contract_and_all_bucket_classes() -> None:
    env = {
        "S3_BUCKET_RAW_HH": "raw",
        "S3_BUCKET_PROCESSED": "processed",
        "S3_BUCKET_BACKUPS": "backups",
        "MINIO_BUCKET_RESUMES": "resumes",
        "MINIO_BUCKET_REPORTS": "reports",
    }

    document = build_policy_document(env)

    assert document["policy_version"] == "skillra_minio_lifecycle_policy.v1"
    assert "API runtime reads local mounted processed data" in document["runtime_contract"]
    assert {bucket["logical_name"] for bucket in document["buckets"]} == {
        "raw_hh",
        "processed",
        "postgres_backups",
        "resumes",
        "reports",
    }
    versioning_by_bucket = {bucket["logical_name"]: bucket["versioning"] for bucket in document["buckets"]}
    assert versioning_by_bucket["raw_hh"]["required_status"] == "Enabled"
    assert versioning_by_bucket["processed"]["required_status"] == "Enabled"
    assert versioning_by_bucket["postgres_backups"]["required_status"] == "deferred"
    assert versioning_by_bucket["resumes"]["required_status"] == "deferred_until_versioned_delete_acceptance"
    assert versioning_by_bucket["resumes"]["managed_by_tool"] is False
    resumes = next(bucket for bucket in document["buckets"] if bucket["logical_name"] == "resumes")
    assert resumes["pii_bucket"] is True
    assert "PII" in resumes["data_classification"]


def test_safe_lifecycle_rule_has_no_expiration_or_delete_actions() -> None:
    policy = make_policy()
    lifecycle = policy.safe_lifecycle_configuration()

    assert lifecycle_has_required_safe_rule(lifecycle)
    assert lifecycle_has_destructive_actions(lifecycle) is False
    rule = lifecycle["Rules"][0]
    assert rule["AbortIncompleteMultipartUpload"]["DaysAfterInitiation"] == ABORT_INCOMPLETE_MULTIPART_DAYS


def test_add_lifecycle_content_md5_header() -> None:
    params: dict[str, Any] = {"body": b"<LifecycleConfiguration/>", "headers": {}}

    add_lifecycle_content_md5(params)

    assert params["headers"]["Content-MD5"] == "j9VfG/p/L54O4f1X84gDLQ=="


def test_build_bucket_policies_skips_unconfigured_buckets() -> None:
    policies = build_bucket_policies({"S3_BUCKET_RAW_HH": "raw"})

    assert [policy.logical_name for policy in policies] == ["raw_hh"]
    assert policies[0].bucket == "raw"


def test_check_policies_reports_missing_required_versioning() -> None:
    policy = make_policy("raw")
    client = FakeS3LifecycleClient()

    report = check_policies(client, [policy])

    assert report["ok"] is False
    assert report["buckets"][0]["versioning_status"] == "Suspended"
    assert "bucket versioning is not Enabled" in report["buckets"][0]["issues"]


def test_check_policies_does_not_require_versioning_for_deferred_bucket() -> None:
    policy = BucketPolicy(
        logical_name="resumes",
        bucket_env_key="MINIO_BUCKET_RESUMES",
        bucket="resumes",
        versioning_required=False,
        data_classification="pii",
        retention_targets=(),
    )
    client = FakeS3LifecycleClient(lifecycle={"resumes": policy.safe_lifecycle_configuration()})

    report = check_policies(client, [policy])

    assert report["ok"] is True
    assert report["buckets"][0]["versioning_status"] == "Suspended"


def test_check_policies_passes_when_versioning_and_safe_rule_exist() -> None:
    policy = make_policy("raw")
    client = FakeS3LifecycleClient(versioning={"raw": "Enabled"})

    report = check_policies(client, [policy])

    assert report["ok"] is True
    assert report["buckets"][0]["safe_lifecycle_rule_present"] is False


def test_check_policies_reports_destructive_lifecycle_rules() -> None:
    policy = make_policy("raw")
    client = FakeS3LifecycleClient(
        versioning={"raw": "Enabled"},
        lifecycle={"raw": {"Rules": [{"ID": "expire-current", "Status": "Enabled", "Expiration": {"Days": 30}}]}},
    )

    report = check_policies(client, [policy])

    assert report["ok"] is False
    assert report["buckets"][0]["destructive_lifecycle_present"] is True
    assert any("expiration/delete lifecycle" in issue for issue in report["buckets"][0]["issues"])


def test_apply_requires_explicit_confirmation() -> None:
    with pytest.raises(SystemExit, match="without --confirm-apply"):
        apply_policies(
            FakeS3LifecycleClient(),
            [make_policy()],
            confirm_apply=False,
            allow_destructive_retention=False,
        )


def test_apply_enables_versioning_and_safe_lifecycle() -> None:
    policy = make_policy("raw")
    client = FakeS3LifecycleClient()

    result = apply_policies(client, [policy], confirm_apply=True, allow_destructive_retention=False)

    assert result["destructive_retention_applied"] is False
    assert client.put_versioning_calls == [
        {"Bucket": "raw", "VersioningConfiguration": {"Status": "Enabled"}},
    ]
    assert client.put_lifecycle_calls == []
    assert result["buckets"][0]["lifecycle"] == "not_changed"


def test_apply_does_not_enable_versioning_for_deferred_bucket() -> None:
    policy = BucketPolicy(
        logical_name="resumes",
        bucket_env_key="MINIO_BUCKET_RESUMES",
        bucket="resumes",
        versioning_required=False,
        data_classification="pii",
        retention_targets=(),
    )
    client = FakeS3LifecycleClient()

    result = apply_policies(client, [policy], confirm_apply=True, allow_destructive_retention=False)

    assert result["buckets"][0]["versioning"] == "not_changed"
    assert client.put_versioning_calls == []
    assert client.put_lifecycle_calls == []


def test_apply_refuses_pii_versioning_without_delete_test_confirmation() -> None:
    policy = BucketPolicy(
        logical_name="resumes",
        bucket_env_key="MINIO_BUCKET_RESUMES",
        bucket="resumes",
        versioning_required=False,
        data_classification="pii",
        retention_targets=(),
        pii_bucket=True,
    )

    with pytest.raises(SystemExit, match="confirm-pii-versioned-delete-tests"):
        apply_policies(
            FakeS3LifecycleClient(),
            [policy],
            confirm_apply=True,
            allow_destructive_retention=False,
            allow_pii_versioning=True,
        )


def test_apply_can_enable_pii_versioning_with_explicit_confirmations() -> None:
    policy = BucketPolicy(
        logical_name="resumes",
        bucket_env_key="MINIO_BUCKET_RESUMES",
        bucket="resumes",
        versioning_required=False,
        data_classification="pii",
        retention_targets=(),
        pii_bucket=True,
    )
    client = FakeS3LifecycleClient()

    result = apply_policies(
        client,
        [policy],
        confirm_apply=True,
        allow_destructive_retention=False,
        allow_pii_versioning=True,
        confirm_pii_versioned_delete_tests=True,
    )

    assert client.put_versioning_calls == [
        {"Bucket": "resumes", "VersioningConfiguration": {"Status": "Enabled"}},
    ]
    assert result["buckets"][0]["versioning"] == "Enabled"


def test_merge_safe_lifecycle_preserves_unrelated_non_destructive_rules() -> None:
    safe = make_policy("raw").safe_lifecycle_configuration()
    existing = {
        "Rules": [
            {
                "ID": "keep-existing-rule",
                "Status": "Enabled",
                "Filter": {"Prefix": "tmp/"},
                "AbortIncompleteMultipartUpload": {"DaysAfterInitiation": 3},
            }
        ]
    }

    merged = merge_safe_lifecycle(existing, safe)

    assert [rule["ID"] for rule in merged["Rules"]] == [
        "keep-existing-rule",
        "skillra-abort-incomplete-multipart-uploads-7d",
    ]


def test_apply_refuses_to_modify_existing_destructive_lifecycle_without_allowance() -> None:
    policy = make_policy("raw")
    client = FakeS3LifecycleClient(
        lifecycle={"raw": {"Rules": [{"ID": "expire-current", "Status": "Enabled", "Expiration": {"Days": 30}}]}}
    )

    with pytest.raises(SystemExit, match="existing expiration/delete actions"):
        apply_policies(client, [policy], confirm_apply=True, allow_destructive_retention=False)

    assert client.put_versioning_calls == []
    assert client.put_lifecycle_calls == []


def test_destructive_lifecycle_detection_blocks_expiration_rules() -> None:
    assert lifecycle_has_destructive_actions({"Rules": [{"Status": "Enabled", "Expiration": {"Days": 30}}]}) is True
