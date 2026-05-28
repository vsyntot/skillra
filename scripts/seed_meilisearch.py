#!/usr/bin/env python
"""Seed vacancy snapshots and MeiliSearch through the Skillra API admin endpoint."""

from __future__ import annotations

import json
import os
import sys
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


def main() -> int:
    base_url = os.getenv("SKILLRA_API_BASE_URL", "http://localhost:8000").rstrip("/")
    api_token = os.getenv("SKILLRA_API_TOKEN")
    admin_token = os.getenv("SKILLRA_ADMIN_TOKEN")

    if not api_token:
        print("SKILLRA_API_TOKEN is required", file=sys.stderr)
        return 2
    if not admin_token:
        print("SKILLRA_ADMIN_TOKEN is required", file=sys.stderr)
        return 2

    request = Request(
        f"{base_url}/v1/admin/index-meilisearch",
        data=b"{}",
        headers={
            "Content-Type": "application/json",
            "X-Skillra-Token": api_token,
            "X-Admin-Token": admin_token,
        },
        method="POST",
    )

    try:
        with urlopen(request, timeout=120) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        print(f"seed failed: HTTP {exc.code} {exc.read().decode('utf-8', errors='replace')}", file=sys.stderr)
        return 1
    except (TimeoutError, URLError) as exc:
        print(f"seed failed: {exc}", file=sys.stderr)
        return 1

    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
