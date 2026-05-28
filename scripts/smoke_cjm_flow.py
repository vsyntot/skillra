#!/usr/bin/env python3
"""Product-level CJM smoke for Skillra local/prod contours."""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests
from requests import Response, Session

SERVICE_TOKEN_HEADER = "X-Skillra-Token"
ADMIN_TOKEN_HEADER = "X-Admin-Token"
DEFAULT_BASE_URL = (
    os.environ.get("SKILLRA_SMOKE_API_BASE_URL") or os.environ.get("SKILLRA_API_BASE_URL") or "http://localhost:8000"
).rstrip("/")
DEFAULT_SERVICE_TOKEN = os.environ.get("SKILLRA_API_TOKEN")
DEFAULT_ADMIN_TOKEN = os.environ.get("SKILLRA_ADMIN_TOKEN")
DEFAULT_BASIC_AUTH_USER = os.environ.get("SKILLRA_SMOKE_BASIC_AUTH_USER") or os.environ.get(
    "CADDY_ADMIN_BASIC_AUTH_USER"
)
DEFAULT_BASIC_AUTH_PASSWORD = os.environ.get("SKILLRA_SMOKE_BASIC_AUTH_PASSWORD") or os.environ.get(
    "CADDY_ADMIN_BASIC_AUTH_PASSWORD"
)
DEFAULT_SMOKE_TELEGRAM_USER_ID = int(os.environ.get("SKILLRA_SMOKE_TELEGRAM_USER_ID", "900000001"))
DEFAULT_SEARCH_QUERY = os.environ.get("SKILLRA_SMOKE_SEARCH_QUERY", "data")
DEFAULT_REPORT_PATH = Path("reports/smoke/cjm_smoke_report.json")


class CjmSmokeFailure(RuntimeError):
    """Raised when CJM smoke fails."""


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run Skillra CJM smoke checks")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--token", default=DEFAULT_SERVICE_TOKEN)
    parser.add_argument("--admin-token", default=DEFAULT_ADMIN_TOKEN)
    parser.add_argument("--basic-auth-user", default=DEFAULT_BASIC_AUTH_USER)
    parser.add_argument("--basic-auth-password", default=DEFAULT_BASIC_AUTH_PASSWORD)
    parser.add_argument("--telegram-user-id", type=int, default=DEFAULT_SMOKE_TELEGRAM_USER_ID)
    parser.add_argument("--search-query", default=DEFAULT_SEARCH_QUERY)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT_PATH)
    parser.add_argument("--strict", action="store_true")
    parser.add_argument(
        "--resume-checks",
        choices=("strict", "warn", "skip"),
        default=os.environ.get("SKILLRA_SMOKE_RESUME_CHECKS", "strict"),
        help="How to handle resume storage checks. Default: strict.",
    )
    parser.add_argument(
        "--prod-safe",
        action="store_true",
        help="Use cleanup-only checks and do not send notifications.",
    )
    return parser.parse_args()


def _check(response: Response, context: str) -> Any:
    if not response.ok:
        detail = response.text[:300].strip()
        raise CjmSmokeFailure(f"{context} failed: HTTP {response.status_code} {response.reason} {detail}")
    content_type = response.headers.get("content-type", "")
    if "application/json" in content_type:
        return response.json()
    return response.content


def _optional(session: Session, method: str, url: str, context: str, *, strict: bool, **kwargs: Any) -> Any | None:
    response = session.request(method, url, **kwargs)
    try:
        return _check(response, context)
    except CjmSmokeFailure:
        if strict:
            raise
        return None


def _first(values: list[Any] | None, fallback: str | None = None) -> str | None:
    if values:
        return str(values[0])
    return fallback


def _meta(session: Session, base_url: str) -> dict[str, list[str]]:
    result: dict[str, list[str]] = {}
    for endpoint, key in [
        ("roles", "roles"),
        ("grades", "grades"),
        ("city-tiers", "city_tiers"),
        ("work-modes", "work_modes"),
        ("domains", "domains"),
        ("skills", "skills"),
    ]:
        payload = _check(session.get(f"{base_url}/v1/meta/{endpoint}"), f"meta {endpoint}")
        values = payload.get(key) if isinstance(payload, dict) else []
        result[endpoint] = [str(value) for value in values] if isinstance(values, list) else []
    return result


def _profile_payload(meta: dict[str, list[str]]) -> dict[str, Any]:
    skills = meta.get("skills") or []
    return {
        "username": "skillra_smoke",
        "target_role": _first(meta.get("roles")),
        "target_grade": _first(meta.get("grades")),
        "target_city_tier": _first(meta.get("city-tiers")),
        "target_work_mode": _first(meta.get("work-modes")),
        "target_domain": _first(meta.get("domains")),
        "current_skills": skills[:1],
    }


def _persona_payload(meta: dict[str, list[str]], profile: dict[str, Any]) -> dict[str, Any]:
    return {
        "name": "CJM Smoke Persona",
        "description": "Automated CJM smoke user",
        "current_skills": profile.get("current_skills") or [],
        "target_role": profile.get("target_role") or _first(meta.get("roles"), "data"),
        "target_grade": profile.get("target_grade"),
        "target_city_tier": profile.get("target_city_tier"),
        "target_work_mode": profile.get("target_work_mode"),
        "constraints": {"domain": profile.get("target_domain")},
        "goals": ["cjm-smoke"],
        "limitations": [],
    }


def _recommended_skill(analysis: Any, fallback: str) -> str:
    if not isinstance(analysis, dict):
        return fallback

    recommended = analysis.get("recommended_skills")
    if isinstance(recommended, list) and recommended:
        return str(recommended[0])

    skill_gap = analysis.get("skill_gap")
    if isinstance(skill_gap, list):
        for entry in skill_gap:
            if isinstance(entry, dict) and entry.get("gap") and entry.get("skill_name"):
                return str(entry["skill_name"])
    return fallback


def _saved_vacancy_payload(results: Any) -> dict[str, str] | None:
    if not isinstance(results, list):
        return None

    vacancy = next((item for item in results if isinstance(item, dict)), None)
    if vacancy is None:
        return None

    hh_vacancy_id = vacancy.get("hh_vacancy_id") or vacancy.get("id")
    title = vacancy.get("title") or vacancy.get("name")
    if not hh_vacancy_id or not title:
        return None

    payload = {
        "hh_vacancy_id": str(hh_vacancy_id)[:50],
        "title": str(title)[:500],
        "note": "Saved by CJM smoke.",
    }
    vacancy_url = vacancy.get("url") or vacancy.get("hh_url")
    if vacancy_url:
        payload["url"] = str(vacancy_url)[:512]
    return payload


def _cleanup(session: Session, base_url: str, telegram_user_id: int) -> None:
    for url in [
        f"{base_url}/v1/users/{telegram_user_id}/resume",
        f"{base_url}/v1/users/{telegram_user_id}/subscriptions/weekly",
        f"{base_url}/v1/users/{telegram_user_id}/career-plan",
        f"{base_url}/v1/users/{telegram_user_id}/profile",
    ]:
        try:
            session.delete(url)
        except requests.RequestException:
            pass


def run_cjm_smoke(
    *,
    base_url: str,
    token: str,
    admin_token: str | None,
    basic_auth_user: str | None,
    basic_auth_password: str | None,
    telegram_user_id: int,
    search_query: str,
    strict: bool,
    resume_checks: str,
    report_path: Path,
) -> dict[str, Any]:
    base_url = base_url.rstrip("/")
    report: dict[str, Any] = {
        "base_url": base_url,
        "telegram_user_id": telegram_user_id,
        "started_at_utc": datetime.now(timezone.utc).isoformat(),
        "checks": {},
    }

    with requests.Session() as session:
        session.headers.update({SERVICE_TOKEN_HEADER: token})
        if basic_auth_user and basic_auth_password:
            session.auth = (basic_auth_user, basic_auth_password)
        try:
            report["checks"]["liveness"] = _check(session.get(f"{base_url}/health"), "/health")
            readiness = _check(session.get(f"{base_url}/v1/health"), "/v1/health")
            report["checks"]["readiness_status"] = readiness.get("status") if isinstance(readiness, dict) else None
            report["dataset_meta"] = (
                (readiness.get("datastore") or {}).get("dataset_meta") if isinstance(readiness, dict) else {}
            )

            meta = _meta(session, base_url)
            report["checks"]["meta_counts"] = {key: len(value) for key, value in meta.items()}

            profile_payload = _profile_payload(meta)
            profile = _check(
                session.put(f"{base_url}/v1/users/{telegram_user_id}/profile", json=profile_payload),
                "profile upsert",
            )
            report["checks"]["profile"] = {
                "target_role": profile.get("target_role") if isinstance(profile, dict) else None,
                "skills_count": len(profile.get("current_skills") or []) if isinstance(profile, dict) else 0,
            }

            filters = {
                "role": profile_payload.get("target_role"),
                "grade": profile_payload.get("target_grade"),
                "city_tier": profile_payload.get("target_city_tier"),
                "work_mode": profile_payload.get("target_work_mode"),
                "domain": profile_payload.get("target_domain"),
            }
            market = _check(session.post(f"{base_url}/v1/market/segment-summary", json=filters), "market segment")
            report["checks"]["market"] = {"ok": isinstance(market, dict)}

            persona = _persona_payload(meta, profile_payload)
            analysis = _check(session.post(f"{base_url}/v1/persona/analyze", json=persona), "persona analyze")
            report["checks"]["persona"] = {"ok": isinstance(analysis, dict)}

            search = _check(
                session.get(f"{base_url}/v1/search/vacancies", params={"q": search_query, "limit": 5}),
                "vacancy search",
            )
            results = search.get("results") if isinstance(search, dict) else []
            report["checks"]["search_results"] = len(results or [])
            if strict and not results:
                raise CjmSmokeFailure("vacancy search returned no results")

            plan = _check(
                session.put(
                    f"{base_url}/v1/users/{telegram_user_id}/career-plan",
                    json={"notes": "CJM smoke career plan."},
                ),
                "career plan upsert",
            )
            if not isinstance(plan, dict) or plan.get("status") != "active":
                raise CjmSmokeFailure("career plan upsert returned invalid payload")
            expected_role = profile_payload.get("target_role")
            if expected_role and plan.get("target_role") != expected_role:
                raise CjmSmokeFailure("career plan did not inherit profile target_role")

            skill_to_close = _recommended_skill(analysis, search_query)
            action = _check(
                session.post(
                    f"{base_url}/v1/users/{telegram_user_id}/career-plan/actions",
                    json={
                        "title": f"Close skill gap: {skill_to_close}",
                        "action_type": "learning",
                        "skill_name": skill_to_close,
                        "priority": 10,
                    },
                ),
                "career action create",
            )
            if not isinstance(action, dict) or action.get("status") != "planned":
                raise CjmSmokeFailure("career action create returned invalid payload")

            completed_action = _check(
                session.patch(
                    f"{base_url}/v1/users/{telegram_user_id}/career-plan/actions/{action['id']}",
                    json={"status": "done"},
                ),
                "career action complete",
            )
            if not isinstance(completed_action, dict) or not completed_action.get("completed_at"):
                raise CjmSmokeFailure("career action completion was not persisted")

            vacancy_payload = _saved_vacancy_payload(results)
            saved_vacancy = None
            if vacancy_payload is not None:
                saved_vacancy = _check(
                    session.post(
                        f"{base_url}/v1/users/{telegram_user_id}/career-plan/saved-vacancies",
                        json=vacancy_payload,
                    ),
                    "career plan save vacancy",
                )
                if not isinstance(saved_vacancy, dict) or saved_vacancy.get("action_type") != "saved_vacancy":
                    raise CjmSmokeFailure("saved vacancy was not persisted as a career action")
            elif strict:
                raise CjmSmokeFailure("vacancy search returned no saveable vacancy")

            fetched_plan = _check(
                session.get(f"{base_url}/v1/users/{telegram_user_id}/career-plan"),
                "career plan fetch",
            )
            actions = fetched_plan.get("actions") if isinstance(fetched_plan, dict) else []
            if not isinstance(actions, list) or not any(
                isinstance(item, dict) and item.get("status") == "done" for item in actions
            ):
                raise CjmSmokeFailure("career plan fetch did not include completed action")
            report["checks"]["career_plan"] = {
                "status": fetched_plan.get("status") if isinstance(fetched_plan, dict) else None,
                "actions_count": len(actions),
                "completed_actions": sum(
                    1 for item in actions if isinstance(item, dict) and item.get("status") == "done"
                ),
                "saved_vacancy": bool(saved_vacancy),
            }

            resume_url = f"{base_url}/v1/users/{telegram_user_id}/resume"
            if resume_checks == "skip":
                report["checks"]["resume"] = {"skipped": True}
            else:
                try:
                    resume = _check(
                        session.post(
                            resume_url,
                            params={"filename": "cjm_smoke_cv.pdf"},
                            data=b"Python SQL smoke resume",
                            headers={"Content-Type": "application/pdf"},
                        ),
                        "resume upload",
                    )
                    status = _check(session.get(resume_url), "resume status")
                    report["checks"]["resume"] = {
                        "uploaded": bool(status.get("uploaded")) if isinstance(status, dict) else False,
                        "s3_key_present": bool(resume.get("s3_key")) if isinstance(resume, dict) else False,
                    }
                except CjmSmokeFailure as exc:
                    if resume_checks == "strict":
                        raise
                    report["checks"]["resume"] = {"ok": False, "warning": str(exc)}

            subscription_payload = {
                "active": True,
                "weekday": 0,
                "time_local": "10:00",
                "timezone": "Europe/Moscow",
            }
            subscription = _check(
                session.put(f"{base_url}/v1/users/{telegram_user_id}/subscriptions/weekly", json=subscription_payload),
                "subscription upsert",
            )
            report["checks"]["subscription"] = {
                "active": subscription.get("active") if isinstance(subscription, dict) else None
            }

            digest_preview = _optional(
                session,
                "POST",
                f"{base_url}/v1/users/{telegram_user_id}/digest-preview",
                "digest preview",
                strict=strict,
            )
            report["checks"]["digest_preview"] = {"ok": isinstance(digest_preview, dict)}

            if admin_token:
                admin_headers = {ADMIN_TOKEN_HEADER: admin_token}
                indexer = _optional(
                    session,
                    "GET",
                    f"{base_url}/v1/admin/indexer-status",
                    "indexer status",
                    strict=strict,
                    headers=admin_headers,
                )
                report["checks"]["indexer_status"] = indexer.get("status") if isinstance(indexer, dict) else None
        finally:
            _cleanup(session, base_url, telegram_user_id)

    report["finished_at_utc"] = datetime.now(timezone.utc).isoformat()
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def main() -> None:
    args = _parse_args()
    if not args.token:
        raise SystemExit("SKILLRA_API_TOKEN or --token is required")
    try:
        report = run_cjm_smoke(
            base_url=args.base_url,
            token=args.token,
            admin_token=args.admin_token,
            basic_auth_user=args.basic_auth_user,
            basic_auth_password=args.basic_auth_password,
            telegram_user_id=args.telegram_user_id,
            search_query=args.search_query,
            strict=args.strict,
            resume_checks=args.resume_checks,
            report_path=args.report,
        )
    except CjmSmokeFailure as exc:
        sys.stderr.write(f"[cjm-smoke] FAILED: {exc}\n")
        raise SystemExit(1) from exc
    print(f"[cjm-smoke] SUCCESS: report saved to {args.report}")
    print(f"[cjm-smoke] checks={json.dumps(report.get('checks', {}), ensure_ascii=False)}")


if __name__ == "__main__":
    main()
