#!/usr/bin/env python3
"""Migrate env files to separate MinIO API, pipeline and backup role credentials."""

from __future__ import annotations

import argparse
import secrets
from pathlib import Path

try:
    from env_contract import is_placeholder, parse_env_file
except ModuleNotFoundError:  # pragma: no cover
    from scripts.env_contract import is_placeholder, parse_env_file


ROLE_ACCESS_KEYS = {
    "MINIO_ACCESS_KEY": "skillra-api",
    "S3_ACCESS_KEY_ID": "skillra-pipeline",
    "S3_BACKUP_ACCESS_KEY_ID": "skillra-backup",
}
ROLE_SECRET_KEYS = (
    "MINIO_SECRET_KEY",
    "S3_SECRET_ACCESS_KEY",
    "S3_BACKUP_SECRET_ACCESS_KEY",
)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Prepare distinct MinIO role credentials in an env file")
    parser.add_argument("--env-file", type=Path, default=Path(".env.prod"))
    parser.add_argument("--write", action="store_true", help="Write changes. Default is dry-run.")
    return parser.parse_args()


def _generated_secret() -> str:
    return secrets.token_urlsafe(36)


def _duplicate_role_values(values: dict[str, str]) -> set[str]:
    counts: dict[str, int] = {}
    for key in ROLE_ACCESS_KEYS:
        value = values.get(key)
        if value:
            counts[value] = counts.get(value, 0) + 1
    return {value for value, count in counts.items() if count > 1}


def plan_minio_role_updates(values: dict[str, str]) -> dict[str, str]:
    """Return env key updates needed to make MinIO role credentials production-ready."""

    updates: dict[str, str] = {}
    duplicate_values = _duplicate_role_values(values)

    for key, canonical_value in ROLE_ACCESS_KEYS.items():
        current = values.get(key)
        if not current or is_placeholder(current) or current in duplicate_values:
            updates[key] = canonical_value

    projected = {**values, **updates}
    projected_values = [projected.get(key) for key in ROLE_ACCESS_KEYS if projected.get(key)]
    if len(projected_values) != len(set(projected_values)):
        updates.update(ROLE_ACCESS_KEYS)
        projected = {**values, **updates}

    for key in ROLE_SECRET_KEYS:
        current = projected.get(key)
        if not current or is_placeholder(current):
            updates[key] = _generated_secret()

    return updates


def apply_updates(env_file: Path, updates: dict[str, str]) -> None:
    lines = env_file.read_text(encoding="utf-8").splitlines() if env_file.exists() else []
    seen: set[str] = set()
    updated_lines: list[str] = []

    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in line:
            updated_lines.append(line)
            continue
        key, _value = line.split("=", 1)
        key = key.strip()
        if key in updates:
            updated_lines.append(f"{key}={updates[key]}")
            seen.add(key)
        else:
            updated_lines.append(line)

    missing = [key for key in updates if key not in seen]
    if missing:
        if updated_lines and updated_lines[-1] != "":
            updated_lines.append("")
        updated_lines.append("# MinIO least-privilege role credentials")
        for key in missing:
            updated_lines.append(f"{key}={updates[key]}")

    env_file.write_text("\n".join(updated_lines) + "\n", encoding="utf-8")


def main() -> None:
    args = _parse_args()
    values, duplicates = parse_env_file(args.env_file)
    if duplicates:
        duplicate_list = ", ".join(sorted(set(duplicates)))
        raise SystemExit(f"{args.env_file} has duplicate keys: {duplicate_list}")

    updates = plan_minio_role_updates(values)
    changed_keys = ", ".join(sorted(updates)) or "none"
    if not args.write:
        print(f"[env-minio-roles] DRY-RUN: would update keys: {changed_keys}")
        return

    if updates:
        apply_updates(args.env_file, updates)
    print(f"[env-minio-roles] updated keys: {changed_keys}")


if __name__ == "__main__":
    main()
