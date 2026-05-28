#!/usr/bin/env python3
"""Check local tooling required for the SOPS + age secret lifecycle."""

from __future__ import annotations

import argparse
import os
import shutil


REQUIRED_TOOLS = ("sops", "age", "age-keygen")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Check SOPS + age tooling without reading secrets.")
    parser.add_argument(
        "--require-recipient",
        action="store_true",
        help="Also require AGE_RECIPIENT to be set to an age public recipient.",
    )
    return parser.parse_args()


def validate_age_recipient(value: str | None) -> bool:
    if not value:
        return False
    recipients = [item.strip() for item in value.split(",") if item.strip()]
    return bool(recipients) and all(item.startswith("age1") for item in recipients)


def main() -> None:
    args = parse_args()
    missing = [tool for tool in REQUIRED_TOOLS if shutil.which(tool) is None]

    for tool in REQUIRED_TOOLS:
        path = shutil.which(tool)
        if path:
            print(f"[secrets-tools] OK: {tool} -> {path}")

    if args.require_recipient:
        recipient = os.environ.get("AGE_RECIPIENT")
        if validate_age_recipient(recipient):
            print("[secrets-tools] OK: AGE_RECIPIENT is set")
        else:
            missing.append("AGE_RECIPIENT")

    if missing:
        print("[secrets-tools] Missing: " + ", ".join(missing))
        print("[secrets-tools] macOS install: brew install sops age")
        print("[secrets-tools] Linux: install age and sops from trusted OS/GitHub release packages")
        raise SystemExit(1)


if __name__ == "__main__":
    main()
