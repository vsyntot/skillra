"""E2E smoke test for Skillra Platform API.

This script performs a quick "red/green" run against a live Skillra API instance.
It validates health endpoints, meta catalog endpoints, market segment summary,
persona analysis, search/indexing, resume storage, and downloads a skill-gap
chart PNG.

Usage:
    python scripts/smoke_skillra_platform.py \
        --base-url http://localhost:8000 \
        --token $SKILLRA_API_TOKEN \
        [--output reports/smoke/persona_skill_gap.png]

The base URL defaults to ``$SKILLRA_API_BASE_URL`` or ``http://localhost:8000``.
The service token is required and is read from ``$SKILLRA_API_TOKEN`` when the
``--token`` flag is not provided.
Sprint-012 admin checks use ``$SKILLRA_ADMIN_TOKEN`` or ``--admin-token`` when
available. They default to warning mode so existing smoke runs stay compatible.
If ``--output`` is omitted, the skill-gap chart is written to
``reports/smoke/persona_skill_gap.png`` inside the repository.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from requests import Response, Session

SERVICE_TOKEN_HEADER = "X-Skillra-Token"
ADMIN_TOKEN_HEADER = "X-Admin-Token"
DEFAULT_BASE_URL = os.environ.get("SKILLRA_API_BASE_URL", "http://localhost:8000").rstrip("/")
DEFAULT_SERVICE_TOKEN = os.environ.get("SKILLRA_API_TOKEN")
DEFAULT_ADMIN_TOKEN = os.environ.get("SKILLRA_ADMIN_TOKEN")
DEFAULT_BASIC_AUTH_USER = os.environ.get("SKILLRA_SMOKE_BASIC_AUTH_USER") or os.environ.get(
    "CADDY_ADMIN_BASIC_AUTH_USER"
)
DEFAULT_BASIC_AUTH_PASSWORD = os.environ.get("SKILLRA_SMOKE_BASIC_AUTH_PASSWORD") or os.environ.get(
    "CADDY_ADMIN_BASIC_AUTH_PASSWORD"
)
DEFAULT_OUTPUT_PATH = Path(__file__).resolve().parent.parent / "reports" / "smoke" / "persona_skill_gap.png"
DEFAULT_SMOKE_TELEGRAM_USER_ID = int(os.environ.get("SKILLRA_SMOKE_TELEGRAM_USER_ID", "900000001"))
DEFAULT_SEARCH_QUERY = os.environ.get("SKILLRA_SMOKE_SEARCH_QUERY", "data")
DEFAULT_REQUEST_TIMEOUT_SECONDS = float(os.environ.get("SKILLRA_SMOKE_REQUEST_TIMEOUT_SECONDS", "240"))
DEFAULT_EXPECTED_RUNTIME_ENV = os.environ.get("SKILLRA_EXPECTED_RUNTIME_ENV")
DEFAULT_EXPECTED_PUBLIC_BASE_URL = os.environ.get("SKILLRA_EXPECTED_PUBLIC_BASE_URL")

META_ENDPOINTS = [
    "roles",
    "grades",
    "city-tiers",
    "work-modes",
    "domains",
    "skills",
]


class SmokeFailure(RuntimeError):
    """Error raised when a smoke check fails."""


class TimeoutSession(Session):
    """Requests session with bounded calls so deploy smoke cannot hang forever."""

    def request(self, method: str, url: str, **kwargs: Any) -> Response:
        kwargs.setdefault("timeout", DEFAULT_REQUEST_TIMEOUT_SECONDS)
        return super().request(method, url, **kwargs)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run Skillra Platform smoke checks")
    parser.add_argument(
        "--base-url",
        dest="base_url",
        default=DEFAULT_BASE_URL,
        help="Base URL of the Skillra API (default: env SKILLRA_API_BASE_URL or http://localhost:8000)",
    )
    parser.add_argument(
        "--token",
        dest="token",
        default=DEFAULT_SERVICE_TOKEN,
        help="Service token for protected API endpoints (default: env SKILLRA_API_TOKEN)",
    )
    parser.add_argument(
        "--output",
        dest="output",
        type=Path,
        default=None,
        help=(
            "Optional path to save the skill-gap chart PNG. "
            "Defaults to reports/smoke/persona_skill_gap.png inside the repository."
        ),
    )
    parser.add_argument(
        "--admin-token",
        dest="admin_token",
        default=DEFAULT_ADMIN_TOKEN,
        help="Admin token for Sprint-012 admin checks (default: env SKILLRA_ADMIN_TOKEN)",
    )
    parser.add_argument(
        "--basic-auth-user",
        dest="basic_auth_user",
        default=DEFAULT_BASIC_AUTH_USER,
        help="Optional HTTP Basic Auth user for Caddy-protected prod endpoints",
    )
    parser.add_argument(
        "--basic-auth-password",
        dest="basic_auth_password",
        default=DEFAULT_BASIC_AUTH_PASSWORD,
        help="Optional HTTP Basic Auth password for Caddy-protected prod endpoints",
    )
    parser.add_argument(
        "--sprint12-checks",
        choices=("warn", "strict", "skip"),
        default=os.environ.get("SKILLRA_SMOKE_SPRINT12_CHECKS", "warn"),
        help="How to handle Sprint-012 optional checks: warn, strict, or skip (default: warn)",
    )
    parser.add_argument(
        "--storage-checks",
        choices=("warn", "strict", "skip"),
        default=os.environ.get("SKILLRA_SMOKE_STORAGE_CHECKS", "warn"),
        help="How to handle resume storage checks: warn, strict, or skip (default: warn)",
    )
    parser.add_argument(
        "--search-index-checks",
        choices=("warn", "strict", "skip"),
        default=os.environ.get("SKILLRA_SMOKE_SEARCH_INDEX_CHECKS", "warn"),
        help="How to handle admin search index checks: warn, strict, or skip (default: warn)",
    )
    parser.add_argument(
        "--smoke-telegram-user-id",
        type=int,
        default=DEFAULT_SMOKE_TELEGRAM_USER_ID,
        help="Telegram user id used for resume storage smoke checks",
    )
    parser.add_argument(
        "--search-query",
        default=DEFAULT_SEARCH_QUERY,
        help="Query used for vacancy search smoke checks",
    )
    parser.add_argument(
        "--expected-runtime-env",
        default=DEFAULT_EXPECTED_RUNTIME_ENV,
        help="Expected /v1/health runtime_env marker for contour-safe smoke runs.",
    )
    parser.add_argument(
        "--expected-public-base-url",
        default=DEFAULT_EXPECTED_PUBLIC_BASE_URL,
        help="Expected /v1/health public_base_url marker for contour-safe smoke runs.",
    )
    return parser.parse_args()


def _check_response(response: Response, context: str) -> Any:
    if not response.ok:
        error_detail = _format_error_detail(response)
        raise SmokeFailure(f"{context} failed: HTTP {response.status_code} {response.reason}{error_detail}".strip())

    content_type = response.headers.get("content-type", "")
    if "application/json" in content_type:
        return response.json()
    return response.content


def _print_step(message: str) -> None:
    print(f"[smoke] {message}", flush=True)


def _warn_or_fail(message: str, mode: str) -> None:
    if mode == "strict":
        raise SmokeFailure(message)
    _print_step(f"WARN: {message}")


def _validate_requested_contour(base_url: str, expected_runtime_env: str | None) -> None:
    expected = (expected_runtime_env or "").strip().lower()
    if expected != "staging":
        return
    normalized = base_url.rstrip("/")
    host = (urlparse(normalized).hostname or "").lower()
    if host in {"skillra.ru", "www.skillra.ru"}:
        raise SmokeFailure("staging smoke must not target the production public base URL")


def _validate_health_contour(
    health_payload: Any,
    *,
    expected_runtime_env: str | None,
    expected_public_base_url: str | None,
) -> None:
    if not expected_runtime_env and not expected_public_base_url:
        return
    if not isinstance(health_payload, dict):
        raise SmokeFailure("/v1/health did not return a JSON object for contour validation")
    if expected_runtime_env and health_payload.get("status") != "ok":
        raise SmokeFailure(f"/v1/health status {health_payload.get('status')} != expected ok")

    if expected_runtime_env:
        actual_runtime_env = _string_or_none(health_payload.get("runtime_env"))
        expected = expected_runtime_env.strip().lower()
        if actual_runtime_env != expected:
            raise SmokeFailure(f"/v1/health runtime_env {actual_runtime_env} != expected {expected}")

    if expected_public_base_url:
        actual_public_base_url = _string_or_none(health_payload.get("public_base_url"))
        expected_url = expected_public_base_url.strip().rstrip("/")
        if actual_public_base_url != expected_url:
            raise SmokeFailure(f"/v1/health public_base_url {actual_public_base_url} != expected {expected_url}")


def _build_segment_filters(meta: dict[str, list[str]]) -> dict[str, str | None]:
    return {
        "role": (meta.get("roles") or [None])[0],
        "grade": (meta.get("grades") or [None])[0],
        "city_tier": (meta.get("city-tiers") or [None])[0],
        "work_mode": (meta.get("work-modes") or [None])[0],
        "domain": (meta.get("domains") or [None])[0],
    }


def _build_persona_payload(meta: dict[str, list[str]], filters: dict[str, str | None]) -> dict[str, Any]:
    skills = _canonicalize_skills(meta.get("skills") or [])
    if len(skills) >= 2:
        current_skills = skills[:1]
    elif len(skills) == 1:
        current_skills = []
    else:
        current_skills = []
    return {
        "name": "Smoke Persona",
        "description": "Automated smoke test persona",
        "current_skills": current_skills,
        "location": filters.get("city_tier"),
        "experience": filters.get("grade"),
        "work_format": filters.get("work_mode"),
        "target_role": filters.get("role") or meta.get("roles", ["Unknown role"])[0],
        "target_grade": filters.get("grade"),
        "target_city_tier": filters.get("city_tier"),
        "target_work_mode": filters.get("work_mode"),
        "skill_whitelist": None,
        "constraints": {"domain": filters.get("domain")},
        "goals": ["quick-check"],
        "limitations": [],
    }


def _call_meta_endpoints(session: Session, base_url: str) -> dict[str, list[str]]:
    collected: dict[str, list[str]] = {}
    for name in META_ENDPOINTS:
        _print_step(f"Calling /v1/meta/{name}")
        response = session.get(f"{base_url}/v1/meta/{name}")
        payload = _check_response(response, f"meta {name}")
        values = payload.get(name.replace("-", "_")) if isinstance(payload, dict) else None
        if isinstance(values, list):
            collected[name] = values
        else:
            collected[name] = []
    return collected


def _canonicalize_skills(skills: list[str]) -> list[str]:
    normalized: list[str] = []
    for skill in skills:
        cleaned = skill.strip().lower()
        for prefix in ("skill_", "has_"):
            if cleaned.startswith(prefix):
                cleaned = cleaned.removeprefix(prefix)
                break
        normalized.append(cleaned)
    return normalized


def _extract_error_payload(response: Response) -> dict[str, Any] | None:
    content_type = response.headers.get("content-type", "")
    if "application/json" not in content_type:
        return None
    try:
        payload = response.json()
    except ValueError:
        return None
    if isinstance(payload, dict):
        return payload
    return None


def _format_error_detail(response: Response) -> str:
    payload = _extract_error_payload(response)
    if payload:
        error_code = payload.get("error_code")
        message = payload.get("message")
        details = []
        if error_code:
            details.append(str(error_code))
        if message:
            details.append(str(message))
        if details:
            return f" — {'; '.join(details)}"
    text = response.text.strip()
    return f" — {text}" if text else ""


def _save_chart(bytes_content: bytes, output_path: Path) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(bytes_content)
    return output_path


def _optional_check_response(response: Response, context: str, mode: str) -> Any | None:
    try:
        return _check_response(response, context)
    except SmokeFailure as exc:
        _warn_or_fail(str(exc), mode)
        return None


def _run_sprint12_checks(
    session: Session,
    base_url: str,
    *,
    admin_token: str | None,
    persona_payload: dict[str, Any],
    mode: str,
) -> None:
    if mode == "skip":
        _print_step("Skipping Sprint-012 optional checks")
        return

    _print_step("Sprint-012: checking search skills")
    skills_payload = _optional_check_response(
        session.get(f"{base_url}/v1/search/skills", params={"q": "Python"}),
        "search skills",
        mode,
    )
    if isinstance(skills_payload, dict):
        skills = skills_payload.get("skills")
        if not isinstance(skills, list):
            _warn_or_fail("search skills response missing skills list", mode)
        elif mode == "strict" and not skills:
            raise SmokeFailure("search skills returned an empty skills list in strict mode")

    _print_step("Sprint-012: checking persona share token")
    share_payload = _optional_check_response(
        session.post(f"{base_url}/v1/persona/share", json=persona_payload),
        "persona share",
        mode,
    )
    if isinstance(share_payload, dict) and not share_payload.get("token"):
        _warn_or_fail("persona share response missing token", mode)

    if not admin_token:
        _warn_or_fail("admin token not provided; skipping admin Sprint-012 checks", mode)
        return

    admin_headers = {ADMIN_TOKEN_HEADER: admin_token}

    _print_step("Sprint-012: checking admin indexer status")
    status_payload = _optional_check_response(
        session.get(f"{base_url}/v1/admin/indexer-status", headers=admin_headers),
        "admin indexer-status",
        mode,
    )
    if isinstance(status_payload, dict) and "status" not in status_payload:
        _warn_or_fail("admin indexer-status response missing status", mode)

    _print_step("Sprint-012: checking admin users list")
    users_payload = _optional_check_response(
        session.get(f"{base_url}/v1/admin/users", headers=admin_headers),
        "admin users",
        mode,
    )
    if isinstance(users_payload, dict):
        users = users_payload.get("users") or users_payload.get("items")
        if users is not None and not isinstance(users, list):
            _warn_or_fail("admin users response has non-list users/items field", mode)


def _run_storage_checks(
    session: Session,
    base_url: str,
    *,
    telegram_user_id: int,
    mode: str,
) -> None:
    if mode == "skip":
        _print_step("Skipping resume storage checks")
        return

    resume_url = f"{base_url}/v1/users/{telegram_user_id}/resume"
    _print_step("Storage: uploading smoke resume")
    upload_payload = _optional_check_response(
        session.post(
            resume_url,
            params={"filename": "smoke_cv.pdf"},
            data=b"Python SQL smoke resume",
            headers={"Content-Type": "application/pdf"},
        ),
        "resume upload",
        mode,
    )
    if not isinstance(upload_payload, dict):
        return
    if not upload_payload.get("s3_key"):
        _warn_or_fail("resume upload response missing s3_key", mode)

    try:
        _print_step("Storage: checking resume status")
        status_payload = _optional_check_response(session.get(resume_url), "resume status", mode)
        if isinstance(status_payload, dict):
            if not status_payload.get("uploaded"):
                _warn_or_fail("resume status did not report uploaded=true", mode)
            if not status_payload.get("presigned_url"):
                _warn_or_fail("resume status response missing presigned_url", mode)

        _print_step("Storage: checking explicit presigned URL")
        presigned_payload = _optional_check_response(
            session.get(f"{resume_url}/presigned-url", params={"ttl": 3600}),
            "resume presigned-url",
            mode,
        )
        if isinstance(presigned_payload, dict) and not presigned_payload.get("url"):
            _warn_or_fail("resume presigned-url response missing url", mode)
    finally:
        _print_step("Storage: deleting smoke resume")
        delete_response = session.delete(resume_url)
        if delete_response.status_code != 204:
            _warn_or_fail(
                f"resume delete failed: HTTP {delete_response.status_code} {delete_response.reason}",
                mode,
            )


def _run_search_index_checks(
    session: Session,
    base_url: str,
    *,
    admin_token: str | None,
    query: str,
    mode: str,
) -> None:
    if mode == "skip":
        _print_step("Skipping search index checks")
        return
    if not admin_token:
        _warn_or_fail("admin token not provided; skipping search index checks", mode)
        return

    admin_headers = {ADMIN_TOKEN_HEADER: admin_token}
    _print_step("Search: running admin index-meilisearch")
    index_payload = _optional_check_response(
        session.post(f"{base_url}/v1/admin/index-meilisearch", headers=admin_headers),
        "admin index-meilisearch",
        mode,
    )
    indexed_count = 0
    if isinstance(index_payload, dict):
        if index_payload.get("status") != "ok":
            _warn_or_fail("admin index-meilisearch response status is not ok", mode)
        indexed_count = int(index_payload.get("indexed") or 0)

    _print_step("Search: checking admin indexer-status")
    status_payload = _optional_check_response(
        session.get(f"{base_url}/v1/admin/indexer-status", headers=admin_headers),
        "admin indexer-status",
        mode,
    )
    if isinstance(status_payload, dict) and status_payload.get("status") not in {"ok", "success", "never_run"}:
        _warn_or_fail(f"unexpected indexer status: {status_payload.get('status')}", mode)

    _print_step("Search: querying vacancies")
    search_payload = _optional_check_response(
        session.get(f"{base_url}/v1/search/vacancies", params={"q": query, "limit": 5}),
        "search vacancies",
        mode,
    )
    if isinstance(search_payload, dict):
        results = search_payload.get("results")
        if not isinstance(results, list):
            _warn_or_fail("search vacancies response missing results list", mode)
        elif mode == "strict" and indexed_count > 0 and not results:
            raise SmokeFailure(f"search vacancies returned no results for query={query!r} after indexing")
        _validate_search_dataset_contract(search_payload, status_payload, mode)


def _validate_search_dataset_contract(search_payload: dict[str, object], status_payload: object, mode: str) -> None:
    dataset_run_id = _string_or_none(search_payload.get("dataset_run_id"))
    index_dataset_run_id = _string_or_none(search_payload.get("index_dataset_run_id"))
    status_dataset_run_id = (
        _string_or_none(status_payload.get("dataset_run_id")) if isinstance(status_payload, dict) else None
    )

    if mode == "strict" and not dataset_run_id:
        raise SmokeFailure("search vacancies response missing dataset_run_id")
    if dataset_run_id and index_dataset_run_id and dataset_run_id != index_dataset_run_id:
        raise SmokeFailure(
            "search vacancies index_dataset_run_id does not match dataset_run_id: "
            f"{index_dataset_run_id} != {dataset_run_id}"
        )
    if dataset_run_id and status_dataset_run_id and dataset_run_id != status_dataset_run_id:
        raise SmokeFailure(
            "admin indexer-status dataset_run_id does not match search dataset_run_id: "
            f"{status_dataset_run_id} != {dataset_run_id}"
        )

    warnings = search_payload.get("warnings")
    if isinstance(warnings, list) and any("differs from API dataset run" in str(warning) for warning in warnings):
        _warn_or_fail("search response reports stale index dataset run", mode)


def _string_or_none(value: object) -> str | None:
    if value in (None, ""):
        return None
    return str(value)


def run_smoke(
    base_url: str,
    token: str,
    output_path: Path | None = None,
    *,
    admin_token: str | None = None,
    basic_auth_user: str | None = None,
    basic_auth_password: str | None = None,
    sprint12_checks: str = "warn",
    storage_checks: str = "warn",
    search_index_checks: str = "warn",
    smoke_telegram_user_id: int = DEFAULT_SMOKE_TELEGRAM_USER_ID,
    search_query: str = DEFAULT_SEARCH_QUERY,
    expected_runtime_env: str | None = None,
    expected_public_base_url: str | None = None,
) -> Path:
    _validate_requested_contour(base_url, expected_runtime_env)
    _print_step(f"Target API base: {base_url}")

    resolved_output = output_path or DEFAULT_OUTPUT_PATH
    resolved_output = resolved_output.resolve()

    with TimeoutSession() as session:
        session.headers.update({SERVICE_TOKEN_HEADER: token})
        if basic_auth_user and basic_auth_password:
            session.auth = (basic_auth_user, basic_auth_password)

        _print_step("Checking /health")
        _check_response(session.get(f"{base_url}/health"), "/health")

        _print_step("Checking /v1/health")
        health_payload = _check_response(session.get(f"{base_url}/v1/health"), "/v1/health")
        _validate_health_contour(
            health_payload,
            expected_runtime_env=expected_runtime_env,
            expected_public_base_url=expected_public_base_url,
        )

        datastore_ready = isinstance(health_payload, dict) and health_payload.get("datastore", {}).get("ready")
        if datastore_ready:
            _print_step("Checking /v1/meta/dataset")
            dataset_meta_payload = _check_response(session.get(f"{base_url}/v1/meta/dataset"), "/v1/meta/dataset")
            if not isinstance(dataset_meta_payload, dict) or "generated_at_utc" not in dataset_meta_payload:
                raise SmokeFailure("/v1/meta/dataset missing generated_at_utc in response")

        meta = _call_meta_endpoints(session, base_url)
        filters = _build_segment_filters(meta)

        _print_step("Calling /v1/market/segment-summary")
        segment_response = session.post(f"{base_url}/v1/market/segment-summary", json=filters)
        _check_response(segment_response, "segment-summary")

        persona_payload = _build_persona_payload(meta, filters)

        _print_step("Calling /v1/persona/analyze")
        analysis_payload = _check_response(
            session.post(f"{base_url}/v1/persona/analyze", json=persona_payload),
            "persona analyze",
        )
        persona_id = None
        if isinstance(analysis_payload, dict):
            persona_id = analysis_payload.get("persona_id") or analysis_payload.get("id")

        _run_sprint12_checks(
            session,
            base_url,
            admin_token=admin_token,
            persona_payload=persona_payload,
            mode=sprint12_checks,
        )
        _run_search_index_checks(
            session,
            base_url,
            admin_token=admin_token,
            query=search_query,
            mode=search_index_checks,
        )
        _run_storage_checks(
            session,
            base_url,
            telegram_user_id=smoke_telegram_user_id,
            mode=storage_checks,
        )

        _print_step("Downloading /v1/persona/skill-gap-chart")
        chart_response = session.post(f"{base_url}/v1/persona/skill-gap-chart", json=persona_payload)
        chart_payload = _extract_error_payload(chart_response)
        if (
            chart_response.status_code == 400
            and chart_payload
            and chart_payload.get("error_code") == "PERSONA_SKILL_GAP_UNAVAILABLE"
        ):
            if persona_id is None:
                raise SmokeFailure("persona skill-gap chart failed: persona id missing for retry")
            _print_step("Skill-gap unavailable, retrying with empty current_skills")
            fallback_payload = {**persona_payload, "current_skills": []}
            _check_response(
                session.put(f"{base_url}/v1/persona/{persona_id}", json=fallback_payload),
                "persona update",
            )
            chart_response = session.post(f"{base_url}/v1/persona/skill-gap-chart", json=fallback_payload)
            if (
                chart_response.status_code == 400
                and (_extract_error_payload(chart_response) or {}).get("error_code") == "PERSONA_SKILL_GAP_UNAVAILABLE"
            ):
                error_detail = _format_error_detail(chart_response)
                raise SmokeFailure(
                    "persona skill-gap chart failed after retry: "
                    f"HTTP {chart_response.status_code} {chart_response.reason}{error_detail}"
                )
        chart_bytes = _check_response(chart_response, "persona skill-gap chart")
        if not isinstance(chart_bytes, (bytes, bytearray)):
            raise SmokeFailure("Skill-gap chart response is empty or invalid")

        chart_path = _save_chart(chart_bytes, resolved_output)
        _print_step(f"Skill-gap chart saved to {chart_path}")
        return chart_path


def main() -> None:
    args = _parse_args()

    if not args.token:
        raise SmokeFailure("Service token is required. Provide --token or set SKILLRA_API_TOKEN.")

    try:
        chart_path = run_smoke(
            args.base_url.rstrip("/"),
            args.token,
            args.output,
            admin_token=args.admin_token,
            basic_auth_user=args.basic_auth_user,
            basic_auth_password=args.basic_auth_password,
            sprint12_checks=args.sprint12_checks,
            storage_checks=args.storage_checks,
            search_index_checks=args.search_index_checks,
            smoke_telegram_user_id=args.smoke_telegram_user_id,
            search_query=args.search_query,
            expected_runtime_env=args.expected_runtime_env,
            expected_public_base_url=args.expected_public_base_url,
        )
    except SmokeFailure as exc:
        sys.stderr.write(f"[smoke] FAILED: {exc}\n")
        sys.exit(1)

    _print_step(f"SUCCESS: smoke checks passed, chart at {chart_path}")


if __name__ == "__main__":
    main()
