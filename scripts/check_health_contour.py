#!/usr/bin/env python3
"""Validate Skillra health runtime contour markers."""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class HealthContourError(RuntimeError):
    """Raised when a health contour marker does not match expectations."""


def fetch_json(url: str, *, timeout: float) -> dict[str, Any]:
    request = Request(url, headers={"Accept": "application/json"}, method="GET")
    try:
        with urlopen(request, timeout=timeout) as response:
            raw = response.read()
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise HealthContourError(f"GET {url} failed with HTTP {exc.code}: {detail}") from exc
    except URLError as exc:
        raise HealthContourError(f"GET {url} failed: {exc}") from exc

    try:
        payload = json.loads(raw.decode("utf-8"))
    except json.JSONDecodeError as exc:
        raise HealthContourError(f"GET {url} returned non-JSON response") from exc
    if not isinstance(payload, dict):
        raise HealthContourError(f"GET {url} returned non-object JSON")
    return payload


def validate_health_contour(
    payload: dict[str, Any],
    *,
    expected_runtime_env: str | None,
    expected_public_base_url: str | None,
) -> None:
    if payload.get("status") != "ok":
        raise HealthContourError(f"status {payload.get('status')!r} != expected 'ok'")

    if expected_runtime_env:
        expected = expected_runtime_env.strip().lower()
        actual = payload.get("runtime_env")
        if actual != expected:
            raise HealthContourError(f"runtime_env {actual!r} != expected {expected!r}")

    if expected_public_base_url:
        expected_url = expected_public_base_url.strip().rstrip("/")
        actual_url = payload.get("public_base_url")
        if actual_url != expected_url:
            raise HealthContourError(f"public_base_url {actual_url!r} != expected {expected_url!r}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate Skillra /v1/health contour markers.")
    parser.add_argument("--url", required=True)
    parser.add_argument("--expected-runtime-env")
    parser.add_argument("--expected-public-base-url")
    parser.add_argument("--timeout", type=float, default=8.0)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    try:
        payload = fetch_json(args.url, timeout=args.timeout)
        validate_health_contour(
            payload,
            expected_runtime_env=args.expected_runtime_env,
            expected_public_base_url=args.expected_public_base_url,
        )
    except HealthContourError as exc:
        sys.stderr.write(f"[health-contour] FAILED: {exc}\n")
        raise SystemExit(1) from exc
    print(
        json.dumps(
            {
                "status": "ok",
                "runtime_env": payload.get("runtime_env"),
                "public_base_url": payload.get("public_base_url"),
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
