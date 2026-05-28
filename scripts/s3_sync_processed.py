from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from botocore.exceptions import ClientError

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
for path in (ROOT, SRC):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from skillra_pda.storage.s3_client import create_s3_client, download_bytes, put_file, upload_bytes


@dataclass(frozen=True)
class ProcessedArtifact:
    local_path: Path
    key: str
    overwrite_existing: bool = False


@dataclass(frozen=True)
class ProcessedArtifactPointer:
    key: str
    sha256: str
    size_bytes: int


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Sync processed pipeline artifacts (runs + latest) to S3.",
    )
    parser.add_argument(
        "--storage-dir",
        default=str(Path("data") / "processed"),
        help="Base processed storage directory (default: data/processed)",
    )
    parser.add_argument(
        "--dataset-meta-path",
        default=None,
        help="Override path to latest dataset_meta.json (default: <storage-dir>/latest/dataset_meta.json)",
    )
    parser.add_argument(
        "--bucket",
        default=None,
        help="Override S3 bucket (default: S3_BUCKET_PROCESSED env)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show planned uploads without sending data to S3.",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Upload even if the S3 object already exists.",
    )
    parser.add_argument(
        "--verify",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Verify latest pointer and uploaded artifact hashes after sync.",
    )
    parser.add_argument(
        "--publish-active-pointer",
        action="store_true",
        help="Also mirror this run as hh/published/active_dataset.json for restore/audit.",
    )
    return parser.parse_args()


def load_dataset_meta(path: Path) -> dict:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("dataset_meta.json must contain a JSON object")
    return payload


def resolve_run_id(dataset_meta: dict) -> str:
    run_id = dataset_meta.get("run_id")
    if not run_id:
        raise ValueError("dataset_meta.json missing required key: run_id")
    return str(run_id)


def build_processed_run_artifacts(processed_dir: Path, run_id: str) -> list[ProcessedArtifact]:
    run_dir = processed_dir / "runs" / run_id
    if not run_dir.exists():
        raise FileNotFoundError(f"Missing run directory: {run_dir}")

    artifacts: list[ProcessedArtifact] = []
    for path in sorted(p for p in run_dir.rglob("*") if p.is_file()):
        rel = path.relative_to(run_dir)
        key = (Path("runs") / run_id / rel).as_posix()
        artifacts.append(ProcessedArtifact(path, key))
    return artifacts


def build_latest_artifacts(processed_dir: Path) -> list[ProcessedArtifact]:
    latest_dir = processed_dir / "latest"
    if not latest_dir.exists():
        raise FileNotFoundError(f"Missing latest directory: {latest_dir}")

    base_dir = latest_dir.resolve() if latest_dir.is_symlink() else latest_dir

    artifacts: list[ProcessedArtifact] = []
    for path in sorted(p for p in base_dir.rglob("*") if p.is_file()):
        rel = path.relative_to(base_dir)
        key = (Path("latest") / rel).as_posix()
        artifacts.append(ProcessedArtifact(path, key, overwrite_existing=True))
    return artifacts


def build_lake_artifacts(processed_dir: Path, run_id: str) -> list[ProcessedArtifact]:
    run_dir = processed_dir / "runs" / run_id
    mapping = {
        "hh_clean.parquet": f"hh/bronze/run={run_id}/hh_clean.parquet",
        "hh_features.parquet": f"hh/silver/run={run_id}/hh_features.parquet",
        "market_view.parquet": f"hh/gold/run={run_id}/market_view.parquet",
        "dataset_meta.json": f"hh/manifests/run={run_id}/dataset_meta.json",
        "quality_report.json": f"hh/manifests/run={run_id}/quality_report.json",
        "run_manifest.json": f"hh/manifests/run={run_id}/manifest.json",
    }
    artifacts: list[ProcessedArtifact] = []
    for filename, key in mapping.items():
        path = run_dir / filename
        if path.exists():
            artifacts.append(ProcessedArtifact(path, key))
    return artifacts


def compute_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_latest_pointer(dataset_meta: dict, artifacts: list[ProcessedArtifact] | None = None) -> dict:
    pointer = {
        "run_id": resolve_run_id(dataset_meta),
        "updated_at_utc": datetime.now(timezone.utc).isoformat(),
        "processed_bucket_layout": "runs/<run_id>/... + latest/...",
    }
    generated_at = dataset_meta.get("generated_at_utc")
    if generated_at:
        pointer["generated_at_utc"] = generated_at
    if artifacts is not None:
        pointer["artifacts"] = [
            ProcessedArtifactPointer(
                key=artifact.key,
                sha256=compute_sha256(artifact.local_path),
                size_bytes=artifact.local_path.stat().st_size,
            ).__dict__
            for artifact in artifacts
        ]
    return pointer


def build_active_dataset_pointer(dataset_meta: dict, pointer: dict) -> dict:
    run_id = resolve_run_id(dataset_meta)
    return {
        "run_id": run_id,
        "published_at_utc": datetime.now(timezone.utc).isoformat(),
        "manifest_key": f"hh/manifests/run={run_id}/manifest.json",
        "quality_report_key": f"hh/manifests/run={run_id}/quality_report.json",
        "dataset_meta_key": f"hh/manifests/run={run_id}/dataset_meta.json",
        "latest_pointer": pointer,
        "product_eligibility": dataset_meta.get("product_eligibility"),
    }


def s3_object_exists(client, bucket: str, key: str) -> bool:
    try:
        client.head_object(Bucket=bucket, Key=key)
    except ClientError as exc:
        code = str(exc.response.get("Error", {}).get("Code", ""))
        if code in {"404", "NoSuchKey", "NotFound"}:
            return False
        raise
    return True


def sync_processed_artifacts(
    client,
    bucket: str,
    artifacts: list[ProcessedArtifact],
    *,
    dry_run: bool,
    overwrite: bool,
) -> None:
    for artifact in artifacts:
        if not artifact.local_path.exists():
            raise FileNotFoundError(f"Missing local file: {artifact.local_path}")

        effective_overwrite = overwrite or artifact.overwrite_existing
        if dry_run:
            print(f"[dry-run] upload s3://{bucket}/{artifact.key} from {artifact.local_path}")
            continue

        exists = False
        if not effective_overwrite:
            exists = s3_object_exists(client, bucket, artifact.key)

        if exists and not effective_overwrite:
            print(f"Skipping s3://{bucket}/{artifact.key} (already exists)")
            continue

        put_file(client, bucket, artifact.key, artifact.local_path)
        print(f"Uploaded s3://{bucket}/{artifact.key}")


def sync_latest_pointer(
    client,
    bucket: str,
    pointer: dict,
    *,
    dry_run: bool,
) -> None:
    payload = json.dumps(pointer, ensure_ascii=False, indent=2).encode("utf-8")
    key = "latest_pointer.json"

    if dry_run:
        print(f"[dry-run] upload s3://{bucket}/{key} ({len(payload)} bytes)")
        return

    upload_bytes(client, bucket, key, payload, content_type="application/json")
    print(f"Uploaded s3://{bucket}/{key}")


def sync_active_dataset_pointer(client, bucket: str, pointer: dict, *, dry_run: bool) -> None:
    payload = json.dumps(pointer, ensure_ascii=False, indent=2).encode("utf-8")
    key = "hh/published/active_dataset.json"
    if dry_run:
        print(f"[dry-run] upload s3://{bucket}/{key} ({len(payload)} bytes)")
        return
    upload_bytes(client, bucket, key, payload, content_type="application/json")
    print(f"Uploaded s3://{bucket}/{key}")


def validate_processed_pointer(client, bucket: str, pointer: dict) -> list[str]:
    failures: list[str] = []
    run_id = str(pointer.get("run_id") or "")
    if not run_id:
        failures.append("latest_pointer.json missing run_id")
    artifacts = pointer.get("artifacts")
    if not isinstance(artifacts, list) or not artifacts:
        failures.append("latest_pointer.json artifacts must be a non-empty list")
        return failures

    for index, artifact in enumerate(artifacts):
        if not isinstance(artifact, dict):
            failures.append(f"artifact[{index}] must be an object")
            continue
        key = str(artifact.get("key") or "")
        expected_sha = str(artifact.get("sha256") or "")
        expected_size = artifact.get("size_bytes")
        if not key:
            failures.append(f"artifact[{index}] missing key")
            continue
        if not expected_sha:
            failures.append(f"artifact[{index}] missing sha256: {key}")
        if not isinstance(expected_size, int) or expected_size < 0:
            failures.append(f"artifact[{index}] invalid size_bytes: {key}")
        try:
            payload = download_bytes(client, bucket, key)
        except Exception as exc:  # noqa: BLE001
            failures.append(f"artifact[{index}] download failed: {key}: {exc}")
            continue
        if isinstance(expected_size, int) and len(payload) != expected_size:
            failures.append(f"artifact[{index}] size mismatch for {key}: {len(payload)} != {expected_size}")
        actual_sha = hashlib.sha256(payload).hexdigest()
        if expected_sha and actual_sha != expected_sha:
            failures.append(f"artifact[{index}] sha256 mismatch for {key}: {actual_sha} != {expected_sha}")
    return failures


def verify_latest_pointer(client, bucket: str, expected_pointer: dict) -> None:
    payload = download_bytes(client, bucket, "latest_pointer.json")
    actual_pointer = json.loads(payload.decode("utf-8"))
    if not isinstance(actual_pointer, dict):
        raise ValueError("latest_pointer.json must contain a JSON object")
    if actual_pointer.get("run_id") != expected_pointer.get("run_id"):
        raise ValueError(
            f"latest_pointer.json run_id {actual_pointer.get('run_id')} != expected {expected_pointer.get('run_id')}"
        )
    failures = validate_processed_pointer(client, bucket, actual_pointer)
    if failures:
        raise ValueError("Processed S3 verification failed: " + "; ".join(failures))


def main() -> None:
    args = parse_args()
    processed_dir = Path(args.storage_dir)
    dataset_meta_path = (
        Path(args.dataset_meta_path) if args.dataset_meta_path else processed_dir / "latest" / "dataset_meta.json"
    )
    bucket = args.bucket or os.environ.get("S3_BUCKET_PROCESSED")

    if not bucket:
        raise SystemExit("S3 bucket not provided. Set S3_BUCKET_PROCESSED or pass --bucket.")

    dataset_meta = load_dataset_meta(dataset_meta_path)
    run_id = resolve_run_id(dataset_meta)

    artifacts = (
        build_processed_run_artifacts(processed_dir, run_id)
        + build_latest_artifacts(processed_dir)
        + build_lake_artifacts(processed_dir, run_id)
    )

    client = create_s3_client(os.environ)
    sync_processed_artifacts(
        client,
        bucket,
        artifacts,
        dry_run=args.dry_run,
        overwrite=args.overwrite,
    )
    pointer = build_latest_pointer(dataset_meta, artifacts)
    sync_latest_pointer(client, bucket, pointer, dry_run=args.dry_run)
    if args.verify and not args.dry_run:
        verify_latest_pointer(client, bucket, pointer)
        print(f"Verified s3://{bucket}/latest_pointer.json and processed artifact hashes")
    if args.publish_active_pointer:
        sync_active_dataset_pointer(
            client, bucket, build_active_dataset_pointer(dataset_meta, pointer), dry_run=args.dry_run
        )


if __name__ == "__main__":
    main()
