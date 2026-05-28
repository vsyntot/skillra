#!/usr/bin/env python3
"""Check that requirements and lock files are in sync."""

from __future__ import annotations

import sys
from pathlib import Path

SEPARATORS = ("<", ">", "=", ";", "[", " ")


def parse_requirements(path: Path) -> set[str]:
    packages: set[str] = set()
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        cutoff = None
        for sep in SEPARATORS:
            index = line.find(sep)
            if index != -1:
                cutoff = index if cutoff is None else min(cutoff, index)
        name = line if cutoff is None else line[:cutoff]
        name = name.strip()
        if name:
            packages.add(name.lower())
    return packages


def parse_lock(path: Path) -> set[str]:
    packages: set[str] = set()
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "==" not in line:
            continue
        name, _, _version = line.partition("==")
        name = name.strip()
        if name:
            packages.add(name.lower())
    return packages


def check_pair(requirements_path: Path, lock_path: Path) -> list[str]:
    reqs = parse_requirements(requirements_path)
    locked = parse_lock(lock_path)
    return sorted(reqs - locked)


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    checks = [
        (
            root / "requirements" / "base.txt",
            root / "requirements" / "lock" / "base.lock.txt",
        ),
        (
            root / "requirements" / "dev.txt",
            root / "requirements" / "lock" / "dev.lock.txt",
        ),
    ]

    missing_any = False
    for requirements_path, lock_path in checks:
        missing = check_pair(requirements_path, lock_path)
        if missing:
            missing_any = True
            missing_list = ", ".join(missing)
            print(
                "Missing packages in lock file:",
                f"{requirements_path} -> {lock_path}",
                f"[{missing_list}]",
                sep="\n",
                file=sys.stderr,
            )

    if missing_any:
        return 1

    print("OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
