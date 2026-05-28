"""Smoke-test strict readiness across multiple Skillra API replicas."""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass
from typing import Any, Iterable
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

DEFAULT_TIMEOUT_SECONDS = 5.0


class ReadinessSmokeFailure(RuntimeError):
    """Raised when a readiness smoke check fails."""


@dataclass(frozen=True)
class ReadyResult:
    """Normalized response from one `/v1/ready` endpoint."""

    url: str
    status_code: int
    payload: dict[str, Any]
    dataset_run_id: str | None
    status: str | None
    data_consistency: str | None


def normalize_ready_url(raw_url: str) -> str:
    """Normalize either an API base URL or a full readiness URL."""

    url = raw_url.strip().rstrip("/")
    if not url:
        raise ReadinessSmokeFailure("Readiness URL must not be empty.")
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ReadinessSmokeFailure(f"Readiness URL must be absolute HTTP(S): {raw_url!r}")
    if url.endswith("/v1/ready"):
        return url
    return f"{url}/v1/ready"


def parse_ready_urls(values: Iterable[str]) -> list[str]:
    """Parse repeated and comma-separated readiness URL values."""

    urls: list[str] = []
    seen: set[str] = set()
    for value in values:
        for chunk in value.split(","):
            if not chunk.strip():
                continue
            url = normalize_ready_url(chunk)
            if url not in seen:
                seen.add(url)
                urls.append(url)
    return urls


def extract_dataset_run_id(payload: dict[str, Any]) -> str | None:
    """Extract the confirmed dataset run id from a readiness payload."""

    run_id = payload.get("dataset_run_id")
    if run_id:
        return str(run_id)
    datastore = payload.get("datastore")
    if isinstance(datastore, dict):
        nested_run_id = datastore.get("dataset_run_id") or datastore.get("run_id")
        if nested_run_id:
            return str(nested_run_id)
    return None


def probe_ready_url(url: str, timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS) -> ReadyResult:
    """Fetch and normalize a single readiness response."""

    request = Request(url, headers={"Accept": "application/json"})
    try:
        with urlopen(request, timeout=timeout_seconds) as response:  # noqa: S310
            status_code = int(response.status)
            raw_body = response.read().decode("utf-8")
    except HTTPError as exc:
        status_code = int(exc.code)
        raw_body = exc.read().decode("utf-8")
    except URLError as exc:
        raise ReadinessSmokeFailure(f"{url} is unreachable: {exc.reason}") from exc
    except TimeoutError as exc:
        raise ReadinessSmokeFailure(f"{url} timed out after {timeout_seconds:g}s") from exc

    try:
        payload = json.loads(raw_body)
    except json.JSONDecodeError as exc:
        raise ReadinessSmokeFailure(f"{url} returned non-JSON readiness payload") from exc
    if not isinstance(payload, dict):
        raise ReadinessSmokeFailure(f"{url} returned non-object readiness payload")

    return ReadyResult(
        url=url,
        status_code=status_code,
        payload=payload,
        dataset_run_id=extract_dataset_run_id(payload),
        status=str(payload.get("status")) if payload.get("status") is not None else None,
        data_consistency=str(payload.get("data_consistency")) if payload.get("data_consistency") is not None else None,
    )


def validate_ready_results(
    results: Iterable[ReadyResult],
    *,
    expected_run_id: str | None = None,
    allow_single: bool = False,
    require_data_consistency: bool = True,
) -> str:
    """Validate that all replicas are routable and serve the same dataset run."""

    collected = list(results)
    if not collected:
        raise ReadinessSmokeFailure("No readiness results were collected.")
    if len(collected) < 2 and not allow_single:
        raise ReadinessSmokeFailure("At least two replica readiness URLs are required.")

    failures: list[str] = []
    dataset_by_url: dict[str, str] = {}
    for result in collected:
        if result.status_code != 200:
            failures.append(f"{result.url}: HTTP {result.status_code}")
        if result.status != "ok":
            failures.append(f"{result.url}: status={result.status!r}")
        if not result.dataset_run_id:
            failures.append(f"{result.url}: dataset_run_id is missing")
        else:
            dataset_by_url[result.url] = result.dataset_run_id
            if expected_run_id and result.dataset_run_id != expected_run_id:
                failures.append(f"{result.url}: dataset_run_id={result.dataset_run_id!r} expected={expected_run_id!r}")
        if require_data_consistency and result.data_consistency != "ok":
            failures.append(f"{result.url}: data_consistency={result.data_consistency!r}")

    dataset_run_ids = set(dataset_by_url.values())
    if len(dataset_run_ids) > 1:
        mismatch = ", ".join(f"{url}={run_id}" for url, run_id in sorted(dataset_by_url.items()))
        failures.append(f"replicas report different dataset_run_id values: {mismatch}")

    if failures:
        raise ReadinessSmokeFailure("; ".join(failures))
    return next(iter(dataset_run_ids), "")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Smoke-test `/v1/ready` across API replicas.")
    parser.add_argument(
        "--url",
        action="append",
        default=[],
        help="Replica API base URL or full /v1/ready URL. Can be repeated.",
    )
    parser.add_argument(
        "--urls",
        default=os.environ.get("SKILLRA_READY_URLS", ""),
        help="Comma-separated replica URLs. Defaults to env SKILLRA_READY_URLS.",
    )
    parser.add_argument(
        "--timeout-seconds",
        type=float,
        default=float(os.environ.get("SKILLRA_READY_TIMEOUT_SECONDS", DEFAULT_TIMEOUT_SECONDS)),
        help="HTTP timeout per readiness request.",
    )
    parser.add_argument(
        "--allow-single",
        action="store_true",
        help="Allow one URL for local smoke debugging. Multi-replica acceptance should not use this.",
    )
    parser.add_argument(
        "--expected-run-id",
        default=os.environ.get("SKILLRA_EXPECTED_DATASET_RUN_ID"),
        help="Require every replica to serve this dataset run id.",
    )
    parser.add_argument(
        "--allow-unknown-consistency",
        action="store_true",
        help="Do not require data_consistency=ok. Intended only for degraded-environment debugging.",
    )
    return parser.parse_args()


def _collect_urls(args: argparse.Namespace) -> list[str]:
    values = [*args.url]
    if args.urls:
        values.append(args.urls)
    urls = parse_ready_urls(values)
    if not urls:
        raise ReadinessSmokeFailure("Provide --url/--urls or set SKILLRA_READY_URLS.")
    return urls


def main() -> int:
    args = _parse_args()
    try:
        urls = _collect_urls(args)
        results = [probe_ready_url(url, timeout_seconds=args.timeout_seconds) for url in urls]
        dataset_run_id = validate_ready_results(
            results,
            expected_run_id=args.expected_run_id,
            allow_single=args.allow_single,
            require_data_consistency=not args.allow_unknown_consistency,
        )
    except ReadinessSmokeFailure as exc:
        print(f"[readiness-smoke] FAILED: {exc}", file=sys.stderr)
        return 1

    print(f"[readiness-smoke] OK: replicas={len(results)} dataset_run_id={dataset_run_id}")
    for result in results:
        print(f"[readiness-smoke] {result.url} status={result.status} data_consistency={result.data_consistency}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
