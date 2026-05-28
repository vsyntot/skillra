#!/usr/bin/env python3
"""Publish the currently mounted processed dataset into the API registry."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


SERVICE_TOKEN_HEADER = "X-Skillra-Token"
ADMIN_TOKEN_HEADER = "X-Admin-Token"


class BootstrapFailure(RuntimeError):
    """Raised when staging dataset bootstrap fails."""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise BootstrapFailure(f"{path} must contain a JSON object")
    return payload


def _request_json(method: str, url: str, *, token: str, admin_token: str | None, payload: dict | None = None) -> dict:
    body = None
    headers = {SERVICE_TOKEN_HEADER: token, "Accept": "application/json"}
    if admin_token:
        headers[ADMIN_TOKEN_HEADER] = admin_token
    if payload is not None:
        body = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = Request(url, data=body, headers=headers, method=method)
    try:
        with urlopen(request, timeout=60) as response:
            raw = response.read().decode("utf-8")
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise BootstrapFailure(f"{method} {url} failed with HTTP {exc.code}: {detail}") from exc
    except URLError as exc:
        raise BootstrapFailure(f"{method} {url} failed: {exc}") from exc
    parsed = json.loads(raw) if raw else {}
    if not isinstance(parsed, dict):
        raise BootstrapFailure(f"{method} {url} returned non-object JSON")
    return parsed


def _artifact(path: Path) -> dict[str, Any]:
    return {
        "path": path.as_posix(),
        "sha256": _sha256(path),
        "size_bytes": path.stat().st_size,
    }


def _required_artifacts(data_dir: Path, run_id: str) -> tuple[Path, list[dict[str, Any]]]:
    run_dir = data_dir / "runs" / run_id
    dataset_meta_path = run_dir / "dataset_meta.json"
    paths = [
        dataset_meta_path,
        run_dir / "hh_features.parquet",
        run_dir / "market_view.parquet",
    ]
    missing = [path.as_posix() for path in paths if not path.exists()]
    if missing:
        raise BootstrapFailure("Missing required processed artifacts: " + ", ".join(missing))
    return dataset_meta_path, [_artifact(path) for path in paths]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Bootstrap a mounted processed dataset into API data_runs.")
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--token", required=True)
    parser.add_argument("--admin-token", required=True)
    parser.add_argument("--data-dir", type=Path, default=Path("/workspace/data/processed"))
    parser.add_argument("--source", default="staging_bootstrap")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    data_dir = args.data_dir
    latest_meta = data_dir / "latest" / "dataset_meta.json"
    dataset_meta = _load_json(latest_meta)
    run_id = str(dataset_meta.get("run_id") or "")
    if not run_id:
        raise SystemExit("dataset_meta.json missing run_id")

    dataset_meta_path, artifacts = _required_artifacts(data_dir, run_id)
    rows = dataset_meta.get("features_rows") or dataset_meta.get("vacancy_count")
    payload = {
        "state": "published",
        "source": args.source,
        "processed_rows": int(rows or 0) or None,
        "dataset_meta_path": dataset_meta_path.as_posix(),
        "artifact_uris": {"artifacts": artifacts},
        "product_eligibility": dataset_meta.get("product_eligibility"),
        "source_capability_ref": dataset_meta.get("source_capability_ref"),
    }
    base_url = args.base_url.rstrip("/")
    state = _request_json(
        "POST",
        f"{base_url}/v1/admin/data-runs/{run_id}/state",
        token=args.token,
        admin_token=args.admin_token,
        payload=payload,
    )
    reload_result = _request_json(
        "POST",
        f"{base_url}/v1/admin/reload-data",
        token=args.token,
        admin_token=args.admin_token,
    )
    print(
        json.dumps(
            {
                "status": "ok",
                "run_id": run_id,
                "state": state.get("state"),
                "reload_status": reload_result.get("status"),
                "indexer": reload_result.get("indexer"),
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
