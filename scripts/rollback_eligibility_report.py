from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

from requests import Response, Session

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from skillra_pda.rollback_readiness import (  # noqa: E402
    DEFAULT_MIN_METADATA_COMPLETE_PUBLISHED_RUNS,
    build_rollback_readiness_report,
)

ADMIN_TOKEN_HEADER = "X-Admin-Token"
SERVICE_TOKEN_HEADER = "X-Skillra-Token"
DEFAULT_BASE_URL = os.environ.get("SKILLRA_API_BASE_URL", "http://localhost:8000").rstrip("/")
DEFAULT_ADMIN_TOKEN = os.environ.get("SKILLRA_ADMIN_TOKEN")
DEFAULT_SERVICE_TOKEN = os.environ.get("SKILLRA_API_TOKEN")
DEFAULT_BASIC_AUTH_USER = os.environ.get("SKILLRA_SMOKE_BASIC_AUTH_USER") or os.environ.get(
    "CADDY_ADMIN_BASIC_AUTH_USER"
)
DEFAULT_BASIC_AUTH_PASSWORD = os.environ.get("SKILLRA_SMOKE_BASIC_AUTH_PASSWORD") or os.environ.get(
    "CADDY_ADMIN_BASIC_AUTH_PASSWORD"
)
DEFAULT_TIMEOUT_SECONDS = float(os.environ.get("SKILLRA_SMOKE_REQUEST_TIMEOUT_SECONDS", "120"))


class TimeoutSession(Session):
    def request(self, method: str, url: str, **kwargs: Any) -> Response:
        kwargs.setdefault("timeout", DEFAULT_TIMEOUT_SECONDS)
        return super().request(method, url, **kwargs)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build a read-only rollback eligibility report from Skillra data-run registry endpoints.",
    )
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--admin-token", default=DEFAULT_ADMIN_TOKEN)
    parser.add_argument("--token", default=DEFAULT_SERVICE_TOKEN)
    parser.add_argument("--basic-auth-user", default=DEFAULT_BASIC_AUTH_USER)
    parser.add_argument("--basic-auth-password", default=DEFAULT_BASIC_AUTH_PASSWORD)
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument(
        "--min-metadata-complete-published-runs",
        type=int,
        default=DEFAULT_MIN_METADATA_COMPLETE_PUBLISHED_RUNS,
    )
    parser.add_argument("--output", type=Path, help="Write JSON report to this path.")
    parser.add_argument(
        "--require-active-unchanged",
        action="store_true",
        help="Fail if the active dataset pointer changes during this read-only check.",
    )
    return parser.parse_args()


def _headers(args: argparse.Namespace) -> dict[str, str]:
    headers: dict[str, str] = {}
    if args.admin_token:
        headers[ADMIN_TOKEN_HEADER] = str(args.admin_token)
    if args.token:
        headers[SERVICE_TOKEN_HEADER] = str(args.token)
    return headers


def _auth(args: argparse.Namespace) -> tuple[str, str] | None:
    if args.basic_auth_user and args.basic_auth_password:
        return (str(args.basic_auth_user), str(args.basic_auth_password))
    return None


def _json_response(response: Response, context: str) -> Any:
    if not response.ok:
        detail = response.text.strip()
        suffix = f" - {detail}" if detail else ""
        raise SystemExit(f"{context} failed: HTTP {response.status_code} {response.reason}{suffix}")
    content_type = response.headers.get("content-type", "")
    if "application/json" not in content_type:
        raise SystemExit(f"{context} did not return JSON")
    return response.json()


def _get_json(session: Session, args: argparse.Namespace, path: str) -> Any:
    response = session.get(
        f"{args.base_url.rstrip('/')}{path}",
        headers=_headers(args),
        auth=_auth(args),
    )
    return _json_response(response, path)


def _write_or_print(payload: dict[str, Any], output: Path | None) -> None:
    serialized = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
    if output is None:
        print(serialized)
        return
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(serialized + "\n", encoding="utf-8")
    print(f"Wrote {output}")


def main() -> None:
    args = parse_args()
    session = TimeoutSession()
    active_before = _get_json(session, args, "/v1/admin/data-runs/active")
    data_runs = _get_json(session, args, f"/v1/admin/data-runs?limit={int(args.limit)}")
    if not isinstance(data_runs, list):
        raise SystemExit("/v1/admin/data-runs did not return a JSON list")
    active_after = _get_json(session, args, "/v1/admin/data-runs/active")

    report = build_rollback_readiness_report(
        data_runs=data_runs,
        active_status=active_after,
        min_metadata_complete_published_runs=args.min_metadata_complete_published_runs,
    )
    before_run_id = _active_run_id(active_before)
    after_run_id = _active_run_id(active_after)
    report["active_unchanged_during_check"] = before_run_id == after_run_id
    report["active_run_id_before_check"] = before_run_id
    report["active_run_id_after_check"] = after_run_id
    _write_or_print(report, args.output)
    if args.require_active_unchanged and before_run_id != after_run_id:
        raise SystemExit(f"Active dataset changed during read-only check: {before_run_id} -> {after_run_id}")


def _active_run_id(payload: Any) -> str | None:
    if not isinstance(payload, dict):
        return None
    active = payload.get("active")
    if not isinstance(active, dict):
        return None
    run_id = active.get("run_id")
    return str(run_id) if run_id else None


if __name__ == "__main__":
    main()
