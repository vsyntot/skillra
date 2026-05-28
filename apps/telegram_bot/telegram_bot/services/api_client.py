"""HTTP client for interacting with Skillra API."""

from __future__ import annotations

import asyncio
import logging
import uuid
from typing import Any

import httpx

from telegram_bot.config import SkillraApiSettings
from telegram_bot.logging_config import log_extra
from telegram_bot.services.errors import SkillraApiError

logger = logging.getLogger(__name__)


def _log_product_event_task_result(task: asyncio.Task[Any]) -> None:
    try:
        task.result()
    except asyncio.CancelledError:
        raise
    except Exception:  # noqa: BLE001
        logger.exception("Failed to record product event")


def track_product_event_safely(
    api_client: Any,
    telegram_user_id: int | None,
    event_name: str,
    *,
    entity_type: str | None = None,
    entity_id: str | None = None,
    session_id: str | None = None,
    correlation_id: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> None:
    tracker = getattr(api_client, "track_product_event", None)
    if telegram_user_id is None or not callable(tracker):
        return
    try:
        tracker(
            telegram_user_id,
            event_name,
            entity_type=entity_type,
            entity_id=entity_id,
            session_id=session_id,
            correlation_id=correlation_id,
            metadata=metadata,
        )
    except Exception:  # noqa: BLE001
        logger.exception("Failed to schedule product event")


class SkillraApiClient:
    """Async HTTP client with lightweight retry logic."""

    def __init__(self, settings: SkillraApiSettings):
        self._settings = settings
        self._client = httpx.AsyncClient(
            base_url=settings.base_url,
            headers=self._default_headers(settings.token),
            timeout=httpx.Timeout(timeout=settings.read_timeout, connect=settings.connect_timeout),
        )

    async def __aenter__(self) -> "SkillraApiClient":
        return self

    async def __aexit__(self, *exc_info: Any) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        await self._client.aclose()

    async def request(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        """Send an HTTP request with retry for transient errors."""

        request_id = str(uuid.uuid4())
        headers = {**dict(self._client.headers), **kwargs.pop("headers", {})}
        headers["X-Request-ID"] = request_id
        kwargs["headers"] = headers

        logger.debug(
            "Sending Skillra API request",
            **log_extra(method=method, url=url, request_id=request_id),
        )

        attempt = 0
        while True:
            try:
                response = await self._client.request(method, url, **kwargs)
                response.raise_for_status()
                response_request_id = response.headers.get("X-Request-ID") or request_id
                logger.debug(
                    "Skillra API response",
                    **log_extra(
                        method=method,
                        url=url,
                        status=response.status_code,
                        request_id=response_request_id,
                    ),
                )
                return response
            except httpx.HTTPStatusError as exc:
                status = exc.response.status_code
                response_request_id = exc.response.headers.get("X-Request-ID") or request_id
                payload: Any | None = None
                try:
                    payload = exc.response.json()
                except Exception:  # noqa: BLE001
                    payload = None

                error_code, error_message = self._extract_error_info(payload)
                request_id = exc.response.headers.get("X-Request-ID")
                if status >= 500 and status != 503 and attempt < self._settings.max_retries:
                    attempt += 1
                    await self._sleep_with_backoff(attempt)
                    continue
                logger.error(
                    "Skillra API error",
                    **log_extra(
                        status=status,
                        url=url,
                        attempt=attempt,
                        request_id=response_request_id,
                        error_code=error_code,
                    ),
                )
                raise SkillraApiError(
                    error_code=error_code,
                    error_message=error_message,
                    status_code=status,
                    request_id=response_request_id,
                    payload=payload,
                ) from exc
            except httpx.RequestError as exc:
                if attempt < self._settings.max_retries:
                    attempt += 1
                    await self._sleep_with_backoff(attempt)
                    continue
                logger.error(
                    "Skillra API request failed",
                    **log_extra(
                        url=url,
                        attempt=attempt,
                        error_type=exc.__class__.__name__,
                        request_id=request_id,
                    ),
                )
                raise

    async def list_roles(self) -> list[str]:
        response = await self.request("GET", "/v1/meta/roles")
        return response.json().get("roles", [])

    async def list_grades(self) -> list[str]:
        response = await self.request("GET", "/v1/meta/grades")
        return response.json().get("grades", [])

    async def list_city_tiers(self) -> list[str]:
        response = await self.request("GET", "/v1/meta/city-tiers")
        return response.json().get("city_tiers", [])

    async def list_work_modes(self) -> list[str]:
        response = await self.request("GET", "/v1/meta/work-modes")
        return response.json().get("work_modes", [])

    async def list_domains(self) -> list[str]:
        response = await self.request("GET", "/v1/meta/domains")
        return response.json().get("domains", [])

    async def list_skills(self) -> list[str]:
        response = await self.request("GET", "/v1/meta/skills")
        return response.json().get("skills", [])

    async def upsert_profile(self, telegram_user_id: int, payload: dict[str, Any]) -> dict[str, Any]:
        response = await self.request(
            "PUT",
            f"/v1/users/{telegram_user_id}/profile",
            json={"source": "bot", **payload},
        )
        return response.json()

    async def get_profile(self, telegram_user_id: int) -> dict[str, Any]:
        response = await self.request("GET", f"/v1/users/{telegram_user_id}/profile")
        return response.json()

    async def get_next_best_action(self, telegram_user_id: int, *, source: str = "bot") -> dict[str, Any]:
        response = await self.request(
            "GET",
            f"/v1/users/{telegram_user_id}/next-best-action",
            params={"source": source},
        )
        return response.json()

    async def get_commercial_state(self, telegram_user_id: int) -> dict[str, Any]:
        response = await self.request("GET", f"/v1/users/{telegram_user_id}/commercial-state")
        return response.json()

    async def delete_profile(self, telegram_user_id: int) -> None:
        await self.request("DELETE", f"/v1/users/{telegram_user_id}/profile")

    async def upsert_career_plan(self, telegram_user_id: int, payload: dict[str, Any]) -> dict[str, Any]:
        response = await self.request(
            "PUT",
            f"/v1/users/{telegram_user_id}/career-plan",
            json={"source": "bot", **payload},
        )
        return response.json()

    async def get_career_plan(self, telegram_user_id: int) -> dict[str, Any]:
        response = await self.request("GET", f"/v1/users/{telegram_user_id}/career-plan")
        return response.json()

    async def generate_career_plan_actions(
        self,
        telegram_user_id: int,
        *,
        limit: int = 5,
        replace_generated: bool = False,
        source: str = "bot",
    ) -> dict[str, Any]:
        response = await self.request(
            "POST",
            f"/v1/users/{telegram_user_id}/career-plan/generate-actions",
            json={"limit": limit, "replace_generated": replace_generated, "source": source},
        )
        return response.json()

    async def patch_career_action(
        self, telegram_user_id: int, action_id: int, payload: dict[str, Any]
    ) -> dict[str, Any]:
        response = await self.request(
            "PATCH",
            f"/v1/users/{telegram_user_id}/career-plan/actions/{action_id}",
            json={"source": "bot", **payload},
        )
        return response.json()

    async def upload_user_resume(self, telegram_user_id: int, file_bytes: bytes, filename: str) -> dict[str, Any]:
        response = await self.request(
            "POST",
            f"/v1/users/{telegram_user_id}/resume",
            content=file_bytes,
            headers={"Content-Type": "application/pdf"},
            params={"filename": filename},
        )
        return response.json()

    async def create_user_api_key(self, telegram_user_id: int) -> dict[str, Any]:
        response = await self.request("POST", f"/v1/users/{telegram_user_id}/api-key")
        return response.json()

    async def get_user_api_key_status(self, telegram_user_id: int) -> dict[str, Any]:
        response = await self.request("GET", f"/v1/users/{telegram_user_id}/api-key")
        return response.json()

    async def revoke_user_api_key(self, telegram_user_id: int) -> dict[str, Any]:
        response = await self.request("DELETE", f"/v1/users/{telegram_user_id}/api-key")
        return response.json()

    async def market_segment_summary(self, filters: dict[str, Any]) -> dict[str, Any]:
        response = await self.request("POST", "/v1/market/segment-summary", json=filters)
        return response.json()

    async def salary_trend(self, role: str, grade: str, weeks: int = 12) -> dict[str, Any]:
        response = await self.request(
            "GET",
            "/v1/market/trends/salary",
            params={"role": role, "grade": grade, "weeks": weeks},
        )
        return response.json()

    async def skill_demand_trend(
        self,
        skill: str,
        *,
        role: str | None = None,
        grade: str | None = None,
        weeks: int = 12,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {"skill": skill, "weeks": weeks}
        if role:
            params["role"] = role
        if grade:
            params["grade"] = grade
        response = await self.request("GET", "/v1/market/trends/skill-demand", params=params)
        return response.json()

    async def vacancy_count_trend(self, role: str, *, grade: str | None = None, weeks: int = 12) -> dict[str, Any]:
        params: dict[str, Any] = {"role": role, "weeks": weeks}
        if grade:
            params["grade"] = grade
        response = await self.request("GET", "/v1/market/trends/vacancy-count", params=params)
        return response.json()

    async def career_graph(self, role: str) -> dict[str, Any]:
        response = await self.request("GET", "/v1/market/career-graph", params={"role": role})
        return response.json()

    async def persona_analyze(self, payload: dict[str, Any]) -> dict[str, Any]:
        response = await self.request("POST", "/v1/persona/analyze", json=payload)
        return response.json()

    async def persona_skill_gap_chart(self, payload: dict[str, Any]) -> bytes:
        response = await self.request("POST", "/v1/persona/skill-gap-chart", json=payload)
        return response.content

    async def upsert_weekly_subscription(self, telegram_user_id: int, payload: dict[str, Any]) -> dict[str, Any]:
        response = await self.request(
            "PUT",
            f"/v1/users/{telegram_user_id}/subscriptions/weekly",
            json={"source": "bot", **payload},
        )
        return response.json()

    async def get_weekly_subscription(self, telegram_user_id: int) -> dict[str, Any]:
        response = await self.request("GET", f"/v1/users/{telegram_user_id}/subscriptions/weekly")
        return response.json()

    async def delete_weekly_subscription(self, telegram_user_id: int) -> None:
        await self.request("DELETE", f"/v1/users/{telegram_user_id}/subscriptions/weekly", params={"source": "bot"})

    async def mark_subscription_sent(self, telegram_user_id: int) -> dict[str, Any]:
        response = await self.request("POST", f"/v1/users/{telegram_user_id}/subscriptions/weekly/mark-sent")
        return response.json()

    async def get_due_subscriptions(self, now_utc: str | None = None) -> list[dict[str, Any]]:
        params = {"now_utc": now_utc} if now_utc else None
        response = await self.request("GET", "/v1/subscriptions/due", params=params)
        return response.json().get("subscriptions", [])

    async def claim_due_subscriptions(
        self, now_utc: str | None = None, stale_lock_seconds: int | None = None
    ) -> list[dict[str, Any]]:
        payload: dict[str, Any] = {}
        if now_utc is not None:
            payload["now_utc"] = now_utc
        if stale_lock_seconds is not None:
            payload["stale_lock_seconds"] = stale_lock_seconds

        response = await self.request("POST", "/v1/subscriptions/weekly/claim", json=payload or None)
        return response.json().get("subscriptions", [])

    async def claim_weekly_digest_subscriptions(
        self, now_utc: str | None = None, stale_lock_seconds: int | None = None
    ) -> list[dict[str, Any]]:
        return await self.claim_due_subscriptions(now_utc=now_utc, stale_lock_seconds=stale_lock_seconds)

    async def ack_subscription_sent(
        self, telegram_user_id: int, lock: str, *, text_preview: str | None = None
    ) -> dict[str, Any]:
        return await self.ack_weekly_digest_subscription(
            telegram_user_id,
            lock,
            sent=True,
            text_preview=text_preview,
        )

    async def ack_subscription_failed(self, telegram_user_id: int, lock: str) -> dict[str, Any]:
        return await self.ack_weekly_digest_subscription(telegram_user_id, lock, sent=False)

    async def ack_weekly_digest_subscription(
        self,
        telegram_user_id: int,
        lock: str,
        *,
        sent: bool,
        now_utc: str | None = None,
        text_preview: str | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {"telegram_user_id": telegram_user_id, "lock": lock}
        if now_utc is not None:
            payload["now_utc"] = now_utc
        if sent and text_preview:
            payload["text_preview"] = text_preview[:500]

        endpoint = "/v1/subscriptions/weekly/ack-sent" if sent else "/v1/subscriptions/weekly/ack-failed"
        response = await self.request("POST", endpoint, json=payload)
        return response.json()

    async def get_digest_preview(self, telegram_user_id: int, *, source: str | None = None) -> dict[str, Any]:
        params = {"source": source} if source else None
        response = await self.request("POST", f"/v1/users/{telegram_user_id}/digest-preview", params=params)
        return response.json()

    async def get_digest_history(self, telegram_user_id: int, *, limit: int = 5, offset: int = 0) -> dict[str, Any]:
        response = await self.request(
            "GET",
            f"/v1/users/{telegram_user_id}/digest/history",
            params={"limit": limit, "offset": offset},
        )
        return response.json()

    async def get_digest_chart(self, telegram_user_id: int) -> bytes:
        response = await self.request("GET", f"/v1/users/{telegram_user_id}/digest-chart")
        return response.content

    async def record_product_event(
        self,
        telegram_user_id: int,
        event_name: str,
        *,
        surface: str = "bot",
        entity_type: str | None = None,
        entity_id: str | None = None,
        session_id: str | None = None,
        correlation_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        response = await self.request(
            "POST",
            f"/v1/users/{telegram_user_id}/product-events",
            json={
                "event_name": event_name,
                "surface": surface,
                "entity_type": entity_type,
                "entity_id": entity_id,
                "session_id": session_id,
                "correlation_id": correlation_id,
                "metadata": metadata or {},
            },
        )
        return response.json()

    def track_product_event(
        self,
        telegram_user_id: int | None,
        event_name: str,
        *,
        entity_type: str | None = None,
        entity_id: str | None = None,
        session_id: str | None = None,
        correlation_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        if telegram_user_id is None:
            return

        task = asyncio.create_task(
            self.record_product_event(
                telegram_user_id,
                event_name,
                entity_type=entity_type,
                entity_id=entity_id,
                session_id=session_id,
                correlation_id=correlation_id,
                metadata=metadata,
            )
        )
        task.add_done_callback(_log_product_event_task_result)

    async def service_health(self) -> dict[str, Any]:
        response = await self.request("GET", "/health")
        return response.json()

    async def data_health(self) -> dict[str, Any]:
        response = await self.request("GET", "/v1/health")
        return response.json()

    async def reload_data(self) -> dict[str, Any]:
        response = await self.request(
            "POST",
            "/v1/admin/reload-data",
            headers={"X-Admin-Token": self._settings.admin_token},
        )
        return response.json()

    async def get_active_subscribers(self) -> list[dict[str, Any]]:
        """Return list of active weekly subscribers (Sprint-009 TASK-07).

        Calls GET /v1/subscriptions/active — expects list of {telegram_user_id: int}.
        Falls back to empty list if endpoint not available.
        """
        try:
            response = await self.request("GET", "/v1/subscriptions/active")
            data = response.json()
            if isinstance(data, list):
                return data
            return data.get("items", []) if isinstance(data, dict) else []
        except Exception:  # noqa: BLE001
            return []

    async def search_skills(self, query: str, limit: int = 5) -> dict[str, Any]:
        """Search skills via MeiliSearch (Sprint-009 TASK-08)."""
        response = await self.request("GET", "/v1/search/skills", params={"q": query, "limit": limit})
        return response.json()

    async def search_vacancies_payload(
        self,
        q: str,
        limit: int = 5,
        *,
        role: str | None = None,
        grade: str | None = None,
        country: str | None = None,
        region: str | None = None,
        city: str | None = None,
        geo_scope: str | None = None,
        skill: str | None = None,
        telegram_user_id: int | None = None,
        source: str | None = None,
    ) -> dict[str, Any]:
        """Search vacancies and return the full response with trust metadata."""
        params: dict[str, Any] = {"q": q, "limit": limit}
        optional_filters = {
            "role": role,
            "grade": grade,
            "country": country,
            "region": region,
            "city": city,
            "geo_scope": geo_scope,
            "skill": skill,
            "telegram_user_id": telegram_user_id,
            "source": source,
        }
        params.update({key: value for key, value in optional_filters.items() if value})
        response = await self.request("GET", "/v1/search/vacancies", params=params)
        payload = response.json()
        return payload if isinstance(payload, dict) else {"results": []}

    async def search_vacancies(self, q: str, limit: int = 5) -> list[dict[str, Any]]:
        """Search vacancies via Skillra API."""
        payload = await self.search_vacancies_payload(q, limit=limit)
        results = payload.get("results", payload.get("hits", []))
        return results if isinstance(results, list) else []

    async def save_career_plan_vacancy(self, telegram_user_id: int, payload: dict[str, Any]) -> dict[str, Any]:
        """Save a vacancy into the user's career plan."""
        response = await self.request(
            "POST",
            f"/v1/users/{telegram_user_id}/career-plan/saved-vacancies",
            json={"source": "bot", **payload},
        )
        return response.json()

    async def update_application_outcome(
        self,
        telegram_user_id: int,
        action_id: int,
        status: str,
        *,
        note: str | None = None,
        source: str = "bot",
    ) -> dict[str, Any]:
        """Record an application outcome transition for a saved vacancy action."""
        payload: dict[str, Any] = {"status": status, "source": source}
        if note:
            payload["note"] = note
        response = await self.request(
            "POST",
            f"/v1/users/{telegram_user_id}/career-plan/actions/{action_id}/outcome",
            json=payload,
        )
        return response.json()

    async def export_persona_pdf(self, payload: dict[str, Any]) -> bytes:
        """Export persona analysis report as PDF bytes."""
        response = await self.request("POST", "/v1/persona/export-pdf", json=payload)
        return response.content

    async def export_persona_csv(self, payload: dict[str, Any]) -> bytes:
        """Export persona analysis report as CSV bytes."""
        response = await self.request("POST", "/v1/persona/export-csv", json=payload)
        return response.content

    async def create_persona_share(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Create a public share token for persona analysis."""
        response = await self.request("POST", "/v1/persona/share", json=payload)
        return response.json()

    async def _sleep_with_backoff(self, attempt: int) -> None:
        delay = self._settings.retry_backoff_seconds * attempt
        await asyncio.sleep(delay)

    @staticmethod
    def _default_headers(token: str) -> dict[str, str]:
        # Only X-Skillra-Token is used for authentication; Authorization: Bearer is
        # intentionally omitted — it was previously sent but never validated by the API
        # (GAP-07, cleaned up 2026-05-18).
        return {
            "X-Skillra-Token": token,
        }

    @staticmethod
    def _extract_error_info(payload: Any) -> tuple[str | None, str | None]:
        if not isinstance(payload, dict):
            return None, None

        error_code = payload.get("error_code")
        error_message = payload.get("message")

        detail = payload.get("detail")
        if isinstance(detail, dict):
            error_code = error_code or detail.get("error_code")
            error_message = error_message or detail.get("message") or detail.get("detail")
        elif isinstance(detail, str):
            error_message = error_message or detail

        return error_code, error_message
