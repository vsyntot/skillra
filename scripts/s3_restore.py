from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
from pathlib import Path

from skillra_pda.storage.s3_client import create_s3_client, download_bytes, get_file


class RestoreError(RuntimeError):
    pass


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Restore raw/processed artifacts from S3 into local volumes.",
    )
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument(
        "--raw-hh-latest",
        action="store_true",
        help="Restore latest raw HH artifacts (state/manifest/latest + last snapshot/delta/parquet).",
    )
    modes.add_argument(
        "--raw-hh-full",
        action="store_true",
        help="Restore all raw HH artifacts from the bucket (full mirror).",
    )
    modes.add_argument(
        "--processed-latest",
        action="store_true",
        help="Restore latest processed artifacts (latest/ + runs/<run_id>).",
    )
    modes.add_argument(
        "--processed-full",
        action="store_true",
        help="Restore all processed artifacts from the bucket (full mirror).",
    )
    parser.add_argument(
        "--raw-storage-dir",
        default=str(Path("data") / "raw" / "hh"),
        help="Local raw HH directory (default: data/raw/hh).",
    )
    parser.add_argument(
        "--processed-storage-dir",
        default=str(Path("data") / "processed"),
        help="Local processed directory (default: data/processed).",
    )
    parser.add_argument(
        "--raw-bucket",
        default=None,
        help="Override raw HH S3 bucket (default: S3_BUCKET_RAW_HH env).",
    )
    parser.add_argument(
        "--processed-bucket",
        default=None,
        help="Override processed S3 bucket (default: S3_BUCKET_PROCESSED env).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show planned downloads without writing to disk.",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Overwrite existing local files.",
    )
    parser.add_argument(
        "--purge",
        action="store_true",
        help="Delete local target directory before restore (destructive).",
    )
    parser.add_argument(
        "--confirm",
        action="store_true",
        help="Confirm destructive operations like --purge.",
    )
    return parser.parse_args()


def ensure_bucket(value: str | None, env_key: str) -> str:
    bucket = value or os.environ.get(env_key)
    if not bucket:
        raise SystemExit(f"S3 bucket not provided. Set {env_key} or pass --{env_key.lower()}.")
    return bucket


def load_json_bytes(payload: bytes, *, label: str) -> dict:
    data = json.loads(payload.decode("utf-8"))
    if not isinstance(data, dict):
        raise RestoreError(f"{label} must contain a JSON object")
    return data


def calculate_raw_latest_keys(state: dict) -> list[str]:
    required_keys = ["last_run_id", "run_date", "snapshot_path", "delta_path"]
    missing = [key for key in required_keys if not state.get(key)]
    if missing:
        raise RestoreError("state.json missing required keys: " + ", ".join(missing))

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

    return [
        "state.json",
        "manifest.jsonl",
        latest_rel.as_posix(),
        snapshot_rel.as_posix(),
        delta_rel.as_posix(),
        parquet_rel.as_posix(),
    ]


def pointer_artifacts(pointer: dict, *, require_run_scoped: bool = False) -> list[dict]:
    artifacts = pointer.get("artifacts")
    if not isinstance(artifacts, list) or not artifacts:
        raise RestoreError("latest_pointer.json artifacts must be a non-empty list")
    run_id = str(pointer.get("run_id") or "")
    parsed: list[dict] = []
    for index, artifact in enumerate(artifacts):
        if not isinstance(artifact, dict):
            raise RestoreError(f"latest_pointer.json artifact[{index}] must be an object")
        key = str(artifact.get("key") or "")
        sha256 = str(artifact.get("sha256") or "")
        size_bytes = artifact.get("size_bytes")
        if not key:
            raise RestoreError(f"latest_pointer.json artifact[{index}] missing key")
        if require_run_scoped and run_id and not key.startswith(f"runs/{run_id}/"):
            raise RestoreError(f"latest_pointer.json artifact[{index}] is not run-scoped: {key}")
        if not sha256:
            raise RestoreError(f"latest_pointer.json artifact[{index}] missing sha256: {key}")
        if not isinstance(size_bytes, int) or size_bytes < 0:
            raise RestoreError(f"latest_pointer.json artifact[{index}] invalid size_bytes: {key}")
        parsed.append({"key": key, "sha256": sha256, "size_bytes": size_bytes})
    return parsed


def raw_pointer_destination(storage_dir: Path, key: str, run_id: str) -> Path:
    prefix = f"runs/{run_id}/"
    if key.startswith(prefix):
        return storage_dir / key.removeprefix(prefix)
    return storage_dir / key


def download_key_verified(
    client,
    bucket: str,
    key: str,
    destination: Path,
    *,
    expected_sha256: str,
    expected_size_bytes: int,
    overwrite: bool,
    dry_run: bool,
) -> None:
    if destination.exists() and not overwrite:
        print(f"Skipping {destination} (already exists)")
        return

    if dry_run:
        print(f"[dry-run] download s3://{bucket}/{key} -> {destination}")
        return

    payload = download_bytes(client, bucket, key)
    actual_size = len(payload)
    if actual_size != expected_size_bytes:
        raise RestoreError(f"s3://{bucket}/{key} size mismatch: {actual_size} != {expected_size_bytes}")
    actual_sha = hashlib.sha256(payload).hexdigest()
    if actual_sha != expected_sha256:
        raise RestoreError(f"s3://{bucket}/{key} sha256 mismatch: {actual_sha} != {expected_sha256}")
    write_bytes(destination, payload, overwrite=overwrite, dry_run=False)


def list_s3_keys(client, bucket: str, prefix: str = "") -> list[str]:
    paginator = client.get_paginator("list_objects_v2")
    keys: list[str] = []
    for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
        for item in page.get("Contents", []):
            key = item.get("Key")
            if not key or key.endswith("/"):
                continue
            keys.append(key)
    return keys


def purge_directory(target_dir: Path, *, dry_run: bool, confirm: bool) -> None:
    if not confirm:
        raise SystemExit("Refusing to purge without --confirm.")

    resolved = target_dir.resolve()
    if resolved == Path("/"):
        raise SystemExit("Refusing to purge root directory.")

    if dry_run:
        print(f"[dry-run] purge {resolved}")
        return

    if resolved.exists():
        shutil.rmtree(resolved)
    resolved.mkdir(parents=True, exist_ok=True)
    print(f"Purged {resolved}")


def write_bytes(destination: Path, payload: bytes, *, overwrite: bool, dry_run: bool) -> None:
    if destination.exists() and not overwrite:
        print(f"Skipping {destination} (already exists)")
        return

    if dry_run:
        print(f"[dry-run] write {destination} ({len(payload)} bytes)")
        return

    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(payload)
    print(f"Downloaded {destination}")


def download_key(
    client,
    bucket: str,
    key: str,
    destination: Path,
    *,
    overwrite: bool,
    dry_run: bool,
) -> None:
    if destination.exists() and not overwrite:
        print(f"Skipping {destination} (already exists)")
        return

    if dry_run:
        print(f"[dry-run] download s3://{bucket}/{key} -> {destination}")
        return

    get_file(client, bucket, key, destination)
    print(f"Downloaded s3://{bucket}/{key}")


def restore_raw_latest(
    client,
    bucket: str,
    storage_dir: Path,
    *,
    overwrite: bool,
    dry_run: bool,
) -> None:
    pointer_payload = download_bytes(client, bucket, "latest_pointer.json")
    pointer = load_json_bytes(pointer_payload, label="latest_pointer.json")
    run_id = str(pointer.get("run_id") or "")
    if not run_id:
        raise RestoreError("latest_pointer.json missing required key: run_id")

    write_bytes(storage_dir / "latest_pointer.json", pointer_payload, overwrite=overwrite, dry_run=dry_run)
    for artifact in pointer_artifacts(pointer, require_run_scoped=True):
        key = artifact["key"]
        destination = raw_pointer_destination(storage_dir, key, run_id)
        download_key_verified(
            client,
            bucket,
            key,
            destination,
            expected_sha256=artifact["sha256"],
            expected_size_bytes=artifact["size_bytes"],
            overwrite=overwrite,
            dry_run=dry_run,
        )


def restore_raw_full(
    client,
    bucket: str,
    storage_dir: Path,
    *,
    overwrite: bool,
    dry_run: bool,
) -> None:
    keys = list_s3_keys(client, bucket)
    for key in keys:
        destination = storage_dir / key
        download_key(client, bucket, key, destination, overwrite=overwrite, dry_run=dry_run)


def restore_processed_latest(
    client,
    bucket: str,
    storage_dir: Path,
    *,
    overwrite: bool,
    dry_run: bool,
) -> None:
    pointer_payload = download_bytes(client, bucket, "latest_pointer.json")
    pointer = load_json_bytes(pointer_payload, label="latest_pointer.json")
    run_id = pointer.get("run_id")
    if not run_id:
        raise RestoreError("latest_pointer.json missing required key: run_id")

    write_bytes(storage_dir / "latest_pointer.json", pointer_payload, overwrite=overwrite, dry_run=dry_run)

    artifacts = pointer.get("artifacts")
    if isinstance(artifacts, list) and artifacts:
        for artifact in pointer_artifacts(pointer):
            key = artifact["key"]
            destination = storage_dir / key
            download_key_verified(
                client,
                bucket,
                key,
                destination,
                expected_sha256=artifact["sha256"],
                expected_size_bytes=artifact["size_bytes"],
                overwrite=overwrite,
                dry_run=dry_run,
            )
        return

    latest_keys = list_s3_keys(client, bucket, prefix="latest/")
    run_keys = list_s3_keys(client, bucket, prefix=f"runs/{run_id}/")
    for key in latest_keys + run_keys:
        destination = storage_dir / key
        download_key(client, bucket, key, destination, overwrite=overwrite, dry_run=dry_run)


def restore_processed_full(
    client,
    bucket: str,
    storage_dir: Path,
    *,
    overwrite: bool,
    dry_run: bool,
) -> None:
    keys = list_s3_keys(client, bucket)
    for key in keys:
        destination = storage_dir / key
        download_key(client, bucket, key, destination, overwrite=overwrite, dry_run=dry_run)


def main() -> None:
    args = parse_args()

    raw_storage_dir = Path(args.raw_storage_dir)
    processed_storage_dir = Path(args.processed_storage_dir)

    if args.purge:
        target_dir = raw_storage_dir if args.raw_hh_latest or args.raw_hh_full else processed_storage_dir
        purge_directory(target_dir, dry_run=args.dry_run, confirm=args.confirm)

    client = create_s3_client(os.environ)

    if args.raw_hh_latest:
        bucket = ensure_bucket(args.raw_bucket, "S3_BUCKET_RAW_HH")
        restore_raw_latest(client, bucket, raw_storage_dir, overwrite=args.overwrite, dry_run=args.dry_run)
        return

    if args.raw_hh_full:
        bucket = ensure_bucket(args.raw_bucket, "S3_BUCKET_RAW_HH")
        restore_raw_full(client, bucket, raw_storage_dir, overwrite=args.overwrite, dry_run=args.dry_run)
        return

    if args.processed_latest:
        bucket = ensure_bucket(args.processed_bucket, "S3_BUCKET_PROCESSED")
        restore_processed_latest(
            client,
            bucket,
            processed_storage_dir,
            overwrite=args.overwrite,
            dry_run=args.dry_run,
        )
        return

    if args.processed_full:
        bucket = ensure_bucket(args.processed_bucket, "S3_BUCKET_PROCESSED")
        restore_processed_full(client, bucket, processed_storage_dir, overwrite=args.overwrite, dry_run=args.dry_run)
        return


if __name__ == "__main__":
    main()
