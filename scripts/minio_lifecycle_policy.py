from __future__ import annotations

import argparse
import base64
import hashlib
import json
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from botocore.exceptions import ClientError

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from scripts.minio_init import create_client, load_effective_env, load_settings


POLICY_VERSION = "skillra_minio_lifecycle_policy.v1"
ABORT_INCOMPLETE_MULTIPART_DAYS = 7

DESTRUCTIVE_LIFECYCLE_KEYS = {
    "Expiration",
    "NoncurrentVersionExpiration",
    "ExpiredObjectDeleteMarker",
}


def add_lifecycle_content_md5(params: dict[str, Any], **_: Any) -> None:
    """Add Content-MD5 for MinIO lifecycle PUT compatibility."""

    body = params.get("body", b"")
    if isinstance(body, str):
        payload = body.encode("utf-8")
    elif isinstance(body, bytes):
        payload = body
    elif hasattr(body, "read"):
        position = body.tell()
        payload = body.read()
        body.seek(position)
    else:
        payload = bytes(body)

    headers = params.setdefault("headers", {})
    headers.setdefault("Content-MD5", base64.b64encode(hashlib.md5(payload).digest()).decode("ascii"))


def register_lifecycle_content_md5(client: Any) -> None:
    events = getattr(getattr(client, "meta", None), "events", None)
    if events is not None:
        events.register("before-call.s3.PutBucketLifecycleConfiguration", add_lifecycle_content_md5)


@dataclass(frozen=True)
class RetentionTarget:
    prefix: str
    target: str
    enforcement: str
    rationale: str


@dataclass(frozen=True)
class BucketPolicy:
    logical_name: str
    bucket_env_key: str
    bucket: str
    versioning_required: bool
    data_classification: str
    retention_targets: tuple[RetentionTarget, ...]
    pii_bucket: bool = False

    def safe_lifecycle_configuration(self) -> dict[str, Any]:
        return {
            "Rules": [
                {
                    "ID": f"skillra-abort-incomplete-multipart-uploads-{ABORT_INCOMPLETE_MULTIPART_DAYS}d",
                    "Status": "Enabled",
                    "Prefix": "",
                    "AbortIncompleteMultipartUpload": {
                        "DaysAfterInitiation": ABORT_INCOMPLETE_MULTIPART_DAYS,
                    },
                }
            ]
        }


def _retention(prefix: str, target: str, enforcement: str, rationale: str) -> RetentionTarget:
    return RetentionTarget(prefix=prefix, target=target, enforcement=enforcement, rationale=rationale)


def build_bucket_policies(env: Mapping[str, str]) -> list[BucketPolicy]:
    specs = [
        BucketPolicy(
            logical_name="raw_hh",
            bucket_env_key="S3_BUCKET_RAW_HH",
            bucket=env.get("S3_BUCKET_RAW_HH", "").strip(),
            versioning_required=True,
            data_classification="HH raw snapshots, deltas, parquet and source manifests",
            retention_targets=(
                _retention(
                    "runs/",
                    "retain indefinitely until an explicit source-retention ADR changes it",
                    "documented; no expiration rule is applied by Sprint 039 tooling",
                    "run-scoped raw artifacts are immutable lineage and restore inputs",
                ),
                _retention(
                    "snapshots/",
                    "retain indefinitely",
                    "documented; no expiration rule is applied by Sprint 039 tooling",
                    "legacy raw CSV snapshots can be needed for restore and audit",
                ),
                _retention(
                    "snapshots_parquet/",
                    "retain indefinitely",
                    "documented; no expiration rule is applied by Sprint 039 tooling",
                    "bronze parquet is the historical analysis substrate",
                ),
                _retention(
                    "quarantine/",
                    "retain until incident owner writes a risk acceptance and removal plan",
                    "manual-only",
                    "quarantined historical prefixes must not be deleted or published by automation",
                ),
                _retention(
                    "latest.csv, state.json, manifest.jsonl, latest_pointer.json",
                    "retain current object and keep old versions for at least 180 days",
                    "versioning required; noncurrent-version expiration deferred",
                    "mutable compatibility pointers should be recoverable without deleting run artifacts",
                ),
            ),
        ),
        BucketPolicy(
            logical_name="processed",
            bucket_env_key="S3_BUCKET_PROCESSED",
            bucket=env.get("S3_BUCKET_PROCESSED", "").strip(),
            versioning_required=True,
            data_classification="processed dataset runs, manifests, quality reports and active mirrors",
            retention_targets=(
                _retention(
                    "runs/",
                    "retain indefinitely while run can be published, audited or rolled back",
                    "documented; no expiration rule is applied by Sprint 039 tooling",
                    "processed runs are immutable serving candidates and rollback inputs",
                ),
                _retention(
                    "hh/bronze/, hh/silver/, hh/gold/, hh/manifests/",
                    "retain indefinitely until table-format migration is accepted",
                    "documented; no expiration rule is applied by Sprint 039 tooling",
                    "lake mirror layers must stay append-only for lineage",
                ),
                _retention(
                    "latest/, latest_pointer.json, hh/published/",
                    "retain current object and keep old versions for at least 90 days",
                    "versioning required; noncurrent-version expiration deferred",
                    "mutable mirrors are restore/audit aids; Postgres remains runtime authority",
                ),
            ),
        ),
        BucketPolicy(
            logical_name="postgres_backups",
            bucket_env_key="S3_BUCKET_BACKUPS",
            bucket=env.get("S3_BUCKET_BACKUPS", "").strip(),
            versioning_required=False,
            data_classification="PostgreSQL logical backups and restore drill inputs",
            retention_targets=(
                _retention(
                    "postgres/",
                    "minimum 7 daily backups plus long copies for 30-90 days",
                    "enforced by scripts/pg_backup_to_s3.py retention cleanup; S3 versioning/expiration deferred",
                    "avoid defeating backup cleanup with noncurrent versions or deleting the only off-host generation",
                ),
                _retention(
                    "restore-drill/",
                    "retain latest drill evidence according to ops evidence policy",
                    "documented; no expiration rule is applied by Sprint 039 tooling",
                    "drill metrics prove backup usability without touching production DB",
                ),
            ),
        ),
        BucketPolicy(
            logical_name="resumes",
            bucket_env_key="MINIO_BUCKET_RESUMES",
            bucket=env.get("MINIO_BUCKET_RESUMES", "").strip(),
            versioning_required=False,
            data_classification="user-uploaded resume artifacts with PII",
            retention_targets=(
                _retention(
                    "",
                    "privacy-retention decision required before automated deletion",
                    "manual/privacy-runbook controlled",
                    "PII retention needs product/legal acceptance and per-user delete semantics",
                ),
            ),
            pii_bucket=True,
        ),
        BucketPolicy(
            logical_name="reports",
            bucket_env_key="MINIO_BUCKET_REPORTS",
            bucket=env.get("MINIO_BUCKET_REPORTS", "").strip(),
            versioning_required=False,
            data_classification="generated user and business reports",
            retention_targets=(
                _retention(
                    "",
                    "privacy-retention decision required before automated deletion",
                    "manual/privacy-runbook controlled",
                    "reports can include derived personal data and must follow user-data policy",
                ),
            ),
            pii_bucket=True,
        ),
    ]
    return [policy for policy in specs if policy.bucket]


def build_extra_bucket_policies(bucket_names: list[str]) -> list[BucketPolicy]:
    policies: list[BucketPolicy] = []
    for index, bucket in enumerate(bucket_names, start=1):
        normalized = bucket.strip()
        if not normalized:
            continue
        policies.append(
            BucketPolicy(
                logical_name=f"extra_{index}",
                bucket_env_key="--bucket",
                bucket=normalized,
                versioning_required=False,
                data_classification="operator-specified bucket",
                retention_targets=(
                    _retention(
                        "",
                        "operator-defined",
                        "safe versioning and multipart cleanup only",
                        "ad-hoc bucket was provided explicitly on the CLI",
                    ),
                ),
            )
        )
    return policies


def lifecycle_has_destructive_actions(lifecycle: Mapping[str, Any]) -> bool:
    for rule in lifecycle.get("Rules", []):
        if not isinstance(rule, Mapping):
            continue
        if any(key in rule for key in DESTRUCTIVE_LIFECYCLE_KEYS):
            return True
    return False


def required_abort_rule_matches(rule: Mapping[str, Any]) -> bool:
    abort_config = rule.get("AbortIncompleteMultipartUpload")
    prefix_matches = rule.get("Prefix") == "" or rule.get("Filter") == {"Prefix": ""}
    return (
        rule.get("Status") == "Enabled"
        and prefix_matches
        and isinstance(abort_config, Mapping)
        and abort_config.get("DaysAfterInitiation") == ABORT_INCOMPLETE_MULTIPART_DAYS
    )


def lifecycle_has_required_safe_rule(lifecycle: Mapping[str, Any]) -> bool:
    for rule in lifecycle.get("Rules", []):
        if isinstance(rule, Mapping) and required_abort_rule_matches(rule):
            return True
    return False


def merge_safe_lifecycle(existing_lifecycle: Mapping[str, Any], safe_lifecycle: Mapping[str, Any]) -> dict[str, Any]:
    safe_rules = [rule for rule in safe_lifecycle.get("Rules", []) if isinstance(rule, Mapping)]
    safe_rule_ids = {str(rule.get("ID")) for rule in safe_rules}
    preserved_rules = [
        rule
        for rule in existing_lifecycle.get("Rules", [])
        if isinstance(rule, Mapping) and str(rule.get("ID")) not in safe_rule_ids
    ]
    return {"Rules": [*preserved_rules, *safe_rules]}


def retention_target_to_dict(target: RetentionTarget) -> dict[str, str]:
    return {
        "prefix": target.prefix,
        "target": target.target,
        "enforcement": target.enforcement,
        "rationale": target.rationale,
    }


def policy_to_dict(policy: BucketPolicy) -> dict[str, Any]:
    required_status = "Enabled" if policy.versioning_required else "deferred"
    if policy.pii_bucket and not policy.versioning_required:
        required_status = "deferred_until_versioned_delete_acceptance"
    return {
        "logical_name": policy.logical_name,
        "bucket_env_key": policy.bucket_env_key,
        "bucket": policy.bucket,
        "data_classification": policy.data_classification,
        "pii_bucket": policy.pii_bucket,
        "versioning": {
            "required_status": required_status,
            "managed_by_tool": policy.versioning_required,
            "can_enable_with_explicit_pii_confirmation": policy.pii_bucket,
        },
        "safe_lifecycle_configuration": policy.safe_lifecycle_configuration(),
        "retention_targets": [retention_target_to_dict(target) for target in policy.retention_targets],
    }


def build_policy_document(env: Mapping[str, str]) -> dict[str, Any]:
    policies = build_bucket_policies(env)
    return {
        "policy_version": POLICY_VERSION,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "runtime_contract": (
            "MinIO/S3 is archive, restore and artifact storage. API runtime reads local mounted processed "
            "data, Postgres and MeiliSearch unless a future ADR changes the contract."
        ),
        "apply_contract": {
            "default_apply_is_non_destructive": True,
            "applied_controls": [
                "bucket versioning Enabled for raw/processed immutable artifact buckets",
            ],
            "not_applied_by_sprint_039_tooling": [
                (
                    "abort incomplete multipart uploads lifecycle rule "
                    "(current MinIO ILM supports expiration/transition, not this non-destructive S3 rule)"
                ),
                "current object expiration",
                "noncurrent version expiration",
                "delete marker cleanup",
                "replication",
                "Iceberg/table-format conversion",
            ],
            "pii_versioning_guard": (
                "PII-bearing buckets remain deferred by default. Apply may enable them only with "
                "--allow-pii-versioning and --confirm-pii-versioned-delete-tests."
            ),
        },
        "buckets": [policy_to_dict(policy) for policy in policies],
    }


def _client_error_code(exc: ClientError) -> str:
    return str(exc.response.get("Error", {}).get("Code", ""))


def _empty_lifecycle_for_missing(exc: ClientError) -> dict[str, list[Any]]:
    code = _client_error_code(exc)
    if code in {"NoSuchLifecycleConfiguration", "NoSuchBucketLifecycleConfiguration", "404", "NotFound"}:
        return {"Rules": []}
    raise exc


def check_bucket_policy(client: Any, policy: BucketPolicy) -> dict[str, Any]:
    issues: list[str] = []
    exists = True
    try:
        client.head_bucket(Bucket=policy.bucket)
    except ClientError as exc:
        exists = False
        issues.append(f"bucket is not accessible: {_client_error_code(exc)}")

    versioning_status = "unknown"
    lifecycle: dict[str, Any] = {"Rules": []}
    if exists:
        try:
            versioning_status = str(client.get_bucket_versioning(Bucket=policy.bucket).get("Status", "Suspended"))
        except ClientError as exc:
            issues.append(f"cannot read bucket versioning: {_client_error_code(exc)}")

        try:
            lifecycle = dict(client.get_bucket_lifecycle_configuration(Bucket=policy.bucket))
        except ClientError as exc:
            lifecycle = _empty_lifecycle_for_missing(exc)

    if policy.versioning_required and versioning_status != "Enabled":
        issues.append("bucket versioning is not Enabled")
    if lifecycle_has_destructive_actions(lifecycle):
        issues.append("bucket has expiration/delete lifecycle rules; verify explicit retention risk acceptance")

    return {
        "logical_name": policy.logical_name,
        "bucket": policy.bucket,
        "bucket_env_key": policy.bucket_env_key,
        "ok": not issues,
        "versioning_status": versioning_status,
        "safe_lifecycle_rule_present": lifecycle_has_required_safe_rule(lifecycle),
        "destructive_lifecycle_present": lifecycle_has_destructive_actions(lifecycle),
        "issues": issues,
    }


def check_policies(client: Any, policies: list[BucketPolicy]) -> dict[str, Any]:
    buckets = [check_bucket_policy(client, policy) for policy in policies]
    return {
        "policy_version": POLICY_VERSION,
        "checked_at_utc": datetime.now(timezone.utc).isoformat(),
        "ok": all(bucket["ok"] for bucket in buckets),
        "buckets": buckets,
    }


def apply_policies(
    client: Any,
    policies: list[BucketPolicy],
    *,
    confirm_apply: bool,
    allow_destructive_retention: bool,
    allow_pii_versioning: bool = False,
    confirm_pii_versioned_delete_tests: bool = False,
) -> dict[str, Any]:
    if not confirm_apply:
        raise SystemExit("Refusing to apply MinIO lifecycle policy without --confirm-apply.")
    if allow_pii_versioning and not confirm_pii_versioned_delete_tests:
        raise SystemExit("Refusing to enable PII bucket versioning without --confirm-pii-versioned-delete-tests.")

    applied: list[dict[str, str]] = []
    for policy in policies:
        try:
            existing_lifecycle = dict(client.get_bucket_lifecycle_configuration(Bucket=policy.bucket))
        except ClientError as exc:
            existing_lifecycle = _empty_lifecycle_for_missing(exc)

        if lifecycle_has_destructive_actions(existing_lifecycle) and not allow_destructive_retention:
            raise SystemExit(
                f"Refusing to modify lifecycle for s3://{policy.bucket}: existing expiration/delete actions "
                "require --allow-destructive-retention after operator review."
            )

        versioning_action = "not_changed"
        should_enable_versioning = policy.versioning_required or (allow_pii_versioning and policy.pii_bucket)
        if should_enable_versioning:
            client.put_bucket_versioning(
                Bucket=policy.bucket,
                VersioningConfiguration={"Status": "Enabled"},
            )
            versioning_action = "Enabled"
        applied.append(
            {
                "logical_name": policy.logical_name,
                "bucket": policy.bucket,
                "versioning": versioning_action,
                "pii_bucket": str(policy.pii_bucket).lower(),
                "lifecycle": "not_changed",
            }
        )

    return {
        "policy_version": POLICY_VERSION,
        "applied_at_utc": datetime.now(timezone.utc).isoformat(),
        "destructive_retention_applied": False,
        "buckets": applied,
    }


def write_or_print(payload: Mapping[str, Any], output: str | None) -> None:
    serialized = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
    if output:
        path = Path(output)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(serialized + "\n", encoding="utf-8")
        print(f"Wrote {path}")
        return
    print(serialized)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Render, check or safely apply Skillra MinIO/S3 lifecycle governance policy.",
    )
    parser.add_argument("--mode", choices=("render", "check", "apply"), default="render")
    parser.add_argument("--env-file", default=None, help="Load settings from an env file.")
    parser.add_argument("--output", default=None, help="Write JSON report/policy to this path.")
    parser.add_argument("--endpoint-url", default=None, help="Override MINIO_ENDPOINT_URL/S3_ENDPOINT_URL.")
    parser.add_argument("--region", default=None, help="Override S3_REGION.")
    parser.add_argument("--access-key", default=None, help="Override MinIO/S3 admin access key.")
    parser.add_argument("--secret-key", default=None, help="Override MinIO/S3 admin secret key.")
    parser.add_argument("--bucket", action="append", default=[], help="Additional bucket for connectivity checks.")
    parser.add_argument(
        "--confirm-apply",
        action="store_true",
        help="Required for --mode apply. Applies only non-destructive controls by default.",
    )
    parser.add_argument(
        "--allow-destructive-retention",
        action="store_true",
        help="Reserved for future explicit retention expiry rules. No Sprint 039 default rule uses this.",
    )
    parser.add_argument(
        "--allow-pii-versioning",
        action="store_true",
        help="Allow apply mode to enable versioning for PII-bearing resume/report buckets.",
    )
    parser.add_argument(
        "--confirm-pii-versioned-delete-tests",
        action="store_true",
        help="Required with --allow-pii-versioning after versioned-delete tests pass.",
    )
    parser.add_argument(
        "--no-fail-on-drift",
        action="store_true",
        help="For --mode check, write drift report but exit 0.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    env = load_effective_env(args.env_file)
    policies = build_bucket_policies(env) + build_extra_bucket_policies(args.bucket)
    if not policies:
        raise SystemExit("No MinIO/S3 buckets configured in env.")

    if args.mode == "render":
        document = build_policy_document(env)
        if args.bucket:
            document["buckets"].extend(policy_to_dict(policy) for policy in build_extra_bucket_policies(args.bucket))
        write_or_print(document, args.output)
        return

    settings = load_settings(args, env)
    client = create_client(settings)
    register_lifecycle_content_md5(client)

    if args.mode == "check":
        report = check_policies(client, policies)
        write_or_print(report, args.output)
        if not report["ok"] and not args.no_fail_on_drift:
            raise SystemExit(1)
        return

    result = apply_policies(
        client,
        policies,
        confirm_apply=args.confirm_apply,
        allow_destructive_retention=args.allow_destructive_retention,
        allow_pii_versioning=args.allow_pii_versioning,
        confirm_pii_versioned_delete_tests=args.confirm_pii_versioned_delete_tests,
    )
    write_or_print(result, args.output)


if __name__ == "__main__":
    main()
