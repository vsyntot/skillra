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
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from skillra_pda.storage.s3_client import create_s3_client, put_file, upload_bytes


@dataclass(frozen=True)
class RawHHArtifact:
    local_path: Path
    key: str
    overwrite_existing: bool = False


@dataclass(frozen=True)
class RawHHArtifactPointer:
    key: str
    sha256: str
    size_bytes: int


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Sync raw HH artifacts (latest, snapshots, deltas, parquet) to S3.",
    )
    parser.add_argument(
        "--storage-dir",
        default=str(Path("data") / "raw" / "hh"),
        help="Base raw HH storage directory (default: data/raw/hh)",
    )
    parser.add_argument(
        "--state-path",
        default=None,
        help="Override path to state.json (default: <storage-dir>/state.json)",
    )
    parser.add_argument(
        "--bucket",
        default=None,
        help="Override S3 bucket (default: S3_BUCKET_RAW_HH env)",
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
        "--legacy-root-keys",
        action=argparse.BooleanOptionalAction,
        default=True,
        help=("Also upload backwards-compatible root keys such as latest.csv and state.json " "(default: enabled)."),
    )
    parser.add_argument(
        "--verify",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Verify uploaded raw objects and latest_pointer.json exist after sync (default: enabled).",
    )
    return parser.parse_args()


def load_state_json(path: Path) -> dict:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("state.json must contain a JSON object")
    return payload


def raw_hh_artifact_relatives(state: dict) -> list[Path]:
    required_keys = ["last_run_id", "run_date", "snapshot_path", "delta_path"]
    missing = [key for key in required_keys if not state.get(key)]
    if missing:
        raise ValueError("state.json missing required keys: " + ", ".join(missing))

    run_id = state["last_run_id"]
    run_date = state["run_date"]
    latest_rel = Path(state.get("latest_path", "latest.csv"))
    snapshot_rel = Path(state["snapshot_path"])
    delta_rel = Path(state["delta_path"])
    parquet_rel_value = state.get("parquet_snapshot_path")
    if parquet_rel_value:
        parquet_rel = Path(parquet_rel_value)
    else:
        parquet_rel = Path("snapshots_parquet") / f"date={run_date}" / f"snapshot_{run_id}.parquet"

    relatives = [
        latest_rel,
        Path("state.json"),
        Path("manifest.jsonl"),
        snapshot_rel,
        delta_rel,
        parquet_rel,
    ]
    collection_report_path = state.get("collection_report_path")
    if collection_report_path:
        relatives.append(Path(str(collection_report_path)))
    return relatives


def build_raw_hh_artifacts(
    storage_dir: Path,
    state: dict,
    *,
    legacy_root_keys: bool = True,
) -> list[RawHHArtifact]:
    """Build MinIO/S3 artifact list for one raw HH run.

    The run-scoped layout is the industrial data-lake contract. Root keys remain
    enabled by default for existing restore/runbook compatibility.
    """

    relatives = raw_hh_artifact_relatives(state)
    run_id = str(state["last_run_id"])
    artifacts: list[RawHHArtifact] = []
    for rel in relatives:
        artifacts.append(RawHHArtifact(storage_dir / rel, (Path("runs") / run_id / rel).as_posix()))
    if legacy_root_keys:
        for rel in relatives:
            artifacts.append(RawHHArtifact(storage_dir / rel, rel.as_posix(), overwrite_existing=True))
    return artifacts


def build_pointer_artifacts(artifacts: list[RawHHArtifact]) -> list[RawHHArtifact]:
    return [artifact for artifact in artifacts if artifact.key.startswith("runs/")]


def compute_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_latest_pointer(state: dict, artifacts: list[RawHHArtifact]) -> dict:
    pointer_artifacts: list[RawHHArtifactPointer] = []
    for artifact in build_pointer_artifacts(artifacts):
        if not artifact.local_path.exists():
            raise FileNotFoundError(f"Missing local file: {artifact.local_path}")
        pointer_artifacts.append(
            RawHHArtifactPointer(
                key=artifact.key,
                sha256=compute_sha256(artifact.local_path),
                size_bytes=artifact.local_path.stat().st_size,
            )
        )

    return {
        "run_id": str(state["last_run_id"]),
        "run_date": str(state["run_date"]),
        "updated_at_utc": datetime.now(timezone.utc).isoformat(),
        "raw_bucket_layout": "runs/<run_id>/...",
        "artifacts": [artifact.__dict__ for artifact in pointer_artifacts],
        "state": {
            "row_count": state.get("row_count"),
            "new_count": state.get("new_count"),
            "removed_count": state.get("removed_count"),
            "sha256": state.get("sha256"),
            "schema_version": state.get("schema_version"),
            "dataset_scope": state.get("dataset_scope"),
            "salary_only": state.get("salary_only"),
        },
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


def sync_raw_hh_artifacts(
    client,
    bucket: str,
    artifacts: list[RawHHArtifact],
    *,
    dry_run: bool,
    overwrite: bool,
) -> None:
    for artifact in artifacts:
        if not artifact.local_path.exists():
            raise FileNotFoundError(f"Missing local file: {artifact.local_path}")

        exists = False
        effective_overwrite = overwrite or artifact.overwrite_existing
        if not effective_overwrite:
            exists = s3_object_exists(client, bucket, artifact.key)

        if exists and not effective_overwrite:
            print(f"Skipping s3://{bucket}/{artifact.key} (already exists)")
            continue

        if dry_run:
            print(f"[dry-run] upload s3://{bucket}/{artifact.key} from {artifact.local_path}")
            continue

        put_file(client, bucket, artifact.key, artifact.local_path)
        print(f"Uploaded s3://{bucket}/{artifact.key}")


def sync_latest_pointer(client, bucket: str, pointer: dict, *, dry_run: bool) -> None:
    payload = json.dumps(pointer, ensure_ascii=False, indent=2).encode("utf-8")
    key = "latest_pointer.json"
    if dry_run:
        print(f"[dry-run] upload s3://{bucket}/{key} ({len(payload)} bytes)")
        return
    upload_bytes(client, bucket, key, payload, content_type="application/json")
    print(f"Uploaded s3://{bucket}/{key}")


def verify_raw_hh_commit(client, bucket: str, artifacts: list[RawHHArtifact]) -> None:
    missing = [artifact.key for artifact in artifacts if not s3_object_exists(client, bucket, artifact.key)]
    if not s3_object_exists(client, bucket, "latest_pointer.json"):
        missing.append("latest_pointer.json")
    if missing:
        raise RuntimeError("Raw HH S3 commit verification failed, missing objects: " + ", ".join(missing))


def main() -> None:
    args = parse_args()
    storage_dir = Path(args.storage_dir)
    state_path = Path(args.state_path) if args.state_path else storage_dir / "state.json"
    bucket = args.bucket or os.environ.get("S3_BUCKET_RAW_HH")

    if not bucket:
        raise SystemExit("S3 bucket not provided. Set S3_BUCKET_RAW_HH or pass --bucket.")

    state = load_state_json(state_path)
    artifacts = build_raw_hh_artifacts(storage_dir, state, legacy_root_keys=args.legacy_root_keys)
    pointer = build_latest_pointer(state, artifacts)

    client = create_s3_client(os.environ)
    sync_raw_hh_artifacts(
        client,
        bucket,
        artifacts,
        dry_run=args.dry_run,
        overwrite=args.overwrite,
    )
    sync_latest_pointer(client, bucket, pointer, dry_run=args.dry_run)
    if args.verify and not args.dry_run:
        verify_raw_hh_commit(client, bucket, artifacts)
        print(f"Verified raw HH commit in s3://{bucket}")


if __name__ == "__main__":
    main()
