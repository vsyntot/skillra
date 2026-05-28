from __future__ import annotations

import asyncio
import uuid

import httpx
import pytest
from telegram_bot.config import SkillraApiSettings
from telegram_bot.services.api_client import SkillraApiClient
from telegram_bot.services.errors import SkillraApiError


class DummyResponse:
    def __init__(self, payload: dict[str, object], content: bytes = b""):
        self._payload = payload
        self.content = content

    def json(self) -> dict[str, object]:
        return self._payload


class StubResponse:
    def __init__(self, headers: dict[str, str] | None = None):
        self.headers = headers or {}
        self.status_code = 200

    def raise_for_status(self) -> None:
        return None


class StubClient:
    def __init__(self, headers: dict[str, str], response_headers: dict[str, str] | None = None):
        self.headers = headers
        self.sent_headers: dict[str, str] | None = None
        self.response_headers = response_headers or {}

    async def request(self, method: str, url: str, **kwargs):  # type: ignore[override]
        self.sent_headers = kwargs.get("headers")
        return StubResponse(headers=self.response_headers)


def test_list_skills_parses_response(monkeypatch) -> None:
    client = SkillraApiClient.__new__(SkillraApiClient)  # type: ignore[misc]

    async def fake_request(method: str, url: str, **kwargs):  # type: ignore[override]
        assert method == "GET"
        assert url == "/v1/meta/skills"
        return DummyResponse({"skills": ["python", "sql"]})

    monkeypatch.setattr(client, "request", fake_request)

    async def run_request() -> list[str]:
        return await client.list_skills()

    skills = asyncio.run(run_request())

    assert skills == ["python", "sql"]


def test_request_adds_request_id_header(monkeypatch) -> None:
    settings = SkillraApiSettings(base_url="http://api", token="token123", admin_token="admin123")
    client = SkillraApiClient.__new__(SkillraApiClient)  # type: ignore[misc]
    client._settings = settings
    stub_client = StubClient({"Authorization": "Bearer token123", "X-Skillra-Token": "token123"})
    client._client = stub_client

    monkeypatch.setattr(
        "telegram_bot.services.api_client.uuid.uuid4",
        lambda: uuid.UUID("12345678-1234-5678-1234-567812345678"),
    )

    async def run_request() -> None:
        await client.request("GET", "/health")

    asyncio.run(run_request())

    assert stub_client.sent_headers
    assert stub_client.sent_headers.get("X-Request-ID") == "12345678-1234-5678-1234-567812345678"
    assert stub_client.sent_headers.get("Authorization") == "Bearer token123"


def test_request_logs_response_request_id(monkeypatch, caplog) -> None:
    settings = SkillraApiSettings(base_url="http://api", token="token123", admin_token="admin123")
    client = SkillraApiClient.__new__(SkillraApiClient)  # type: ignore[misc]
    client._settings = settings
    stub_client = StubClient(
        {"Authorization": "Bearer token123", "X-Skillra-Token": "token123"},
        response_headers={"X-Request-ID": "response-id"},
    )
    client._client = stub_client

    monkeypatch.setattr(
        "telegram_bot.services.api_client.uuid.uuid4",
        lambda: uuid.UUID("12345678-1234-5678-1234-567812345678"),
    )

    caplog.set_level("DEBUG", logger="telegram_bot.services.api_client")

    async def run_request() -> None:
        await client.request("GET", "/health")

    asyncio.run(run_request())

    response_logs = [record for record in caplog.records if record.message == "Skillra API response"]
    assert response_logs
    assert response_logs[0].context["request_id"] == "response-id"


def test_request_raises_skillra_api_error_from_top_level(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = SkillraApiSettings(base_url="http://api", token="token", admin_token="admin")
    client = SkillraApiClient.__new__(SkillraApiClient)  # type: ignore[misc]
    client._settings = settings

    request = httpx.Request("GET", "http://api/test")
    response = httpx.Response(
        400,
        request=request,
        json={"error_code": "DATA_UNAVAILABLE", "message": "No data"},
        headers={"X-Request-ID": "req-123"},
    )
    http_error = httpx.HTTPStatusError("bad request", request=request, response=response)

    class FailingClient:
        def __init__(self) -> None:
            self.headers = {}

        async def request(self, *_: object, **__: object) -> httpx.Response:
            raise http_error

    client._client = FailingClient()

    with pytest.raises(SkillraApiError) as captured:
        asyncio.run(client.request("GET", "/test"))

    error = captured.value
    assert error.error_code == "DATA_UNAVAILABLE"
    assert error.error_message == "No data"
    assert error.status_code == 400
    assert error.request_id == "req-123"
    assert error.payload == {"error_code": "DATA_UNAVAILABLE", "message": "No data"}


def test_request_extracts_error_from_detail(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = SkillraApiSettings(base_url="http://api", token="token", admin_token="admin")
    client = SkillraApiClient.__new__(SkillraApiClient)  # type: ignore[misc]
    client._settings = settings

    request = httpx.Request("GET", "http://api/test")
    response = httpx.Response(
        503,
        request=request,
        json={"detail": {"error_code": "SERVICE_TOKEN_NOT_CONFIGURED", "message": "No token"}},
    )
    http_error = httpx.HTTPStatusError("server error", request=request, response=response)

    class FailingClient:
        def __init__(self) -> None:
            self.headers = {}

        async def request(self, *_: object, **__: object) -> httpx.Response:
            raise http_error

    client._client = FailingClient()

    with pytest.raises(SkillraApiError) as captured:
        asyncio.run(client.request("GET", "/test"))

    error = captured.value
    assert error.error_code == "SERVICE_TOKEN_NOT_CONFIGURED"
    assert error.error_message == "No token"
    assert error.status_code == 503
    assert error.payload == {"detail": {"error_code": "SERVICE_TOKEN_NOT_CONFIGURED", "message": "No token"}}


def test_ack_weekly_digest_subscription_sends_preview(monkeypatch) -> None:
    client = SkillraApiClient.__new__(SkillraApiClient)  # type: ignore[misc]
    captured: dict[str, object] = {}

    async def fake_request(method: str, url: str, **kwargs):  # type: ignore[override]
        captured["method"] = method
        captured["url"] = url
        captured["json"] = kwargs["json"]
        return DummyResponse({"ok": ["true"]})

    monkeypatch.setattr(client, "request", fake_request)

    async def run_request() -> dict[str, object]:
        return await client.ack_weekly_digest_subscription(42, "lock", sent=True, text_preview="x" * 600)

    asyncio.run(run_request())

    assert captured["method"] == "POST"
    assert captured["url"] == "/v1/subscriptions/weekly/ack-sent"
    assert captured["json"] == {"telegram_user_id": 42, "lock": "lock", "text_preview": "x" * 500}


def test_user_api_key_methods_call_expected_endpoints(monkeypatch) -> None:
    client = SkillraApiClient.__new__(SkillraApiClient)  # type: ignore[misc]
    calls: list[tuple[str, str]] = []

    async def fake_request(method: str, url: str, **kwargs):  # type: ignore[override]
        calls.append((method, url))
        return DummyResponse({"ok": ["true"]})

    monkeypatch.setattr(client, "request", fake_request)

    async def run_request() -> None:
        await client.create_user_api_key(42)
        await client.get_user_api_key_status(42)
        await client.revoke_user_api_key(42)

    asyncio.run(run_request())

    assert calls == [
        ("POST", "/v1/users/42/api-key"),
        ("GET", "/v1/users/42/api-key"),
        ("DELETE", "/v1/users/42/api-key"),
    ]


def test_get_next_best_action_calls_expected_endpoint(monkeypatch) -> None:
    client = SkillraApiClient.__new__(SkillraApiClient)  # type: ignore[misc]
    captured: dict[str, object] = {}

    async def fake_request(method: str, url: str, **kwargs):  # type: ignore[override]
        captured["method"] = method
        captured["url"] = url
        captured["params"] = kwargs["params"]
        return DummyResponse({"state": "create_plan"})

    monkeypatch.setattr(client, "request", fake_request)

    async def run_request() -> dict[str, object]:
        return await client.get_next_best_action(42, source="bot")

    result = asyncio.run(run_request())

    assert result == {"state": "create_plan"}
    assert captured == {
        "method": "GET",
        "url": "/v1/users/42/next-best-action",
        "params": {"source": "bot"},
    }


def test_record_product_event_calls_expected_endpoint(monkeypatch) -> None:
    client = SkillraApiClient.__new__(SkillraApiClient)  # type: ignore[misc]
    captured: dict[str, object] = {}

    async def fake_request(method: str, url: str, **kwargs):  # type: ignore[override]
        captured["method"] = method
        captured["url"] = url
        captured["json"] = kwargs["json"]
        return DummyResponse({"id": 1})

    monkeypatch.setattr(client, "request", fake_request)

    async def run_request() -> dict[str, object]:
        return await client.record_product_event(
            42,
            "market_fit_viewed",
            entity_type="market_segment",
            metadata={"dataset_run_id": "run-1"},
        )

    result = asyncio.run(run_request())

    assert result == {"id": 1}
    assert captured == {
        "method": "POST",
        "url": "/v1/users/42/product-events",
        "json": {
            "event_name": "market_fit_viewed",
            "surface": "bot",
            "entity_type": "market_segment",
            "entity_id": None,
            "session_id": None,
            "correlation_id": None,
            "metadata": {"dataset_run_id": "run-1"},
        },
    }


def test_get_commercial_state_calls_expected_endpoint(monkeypatch) -> None:
    client = SkillraApiClient.__new__(SkillraApiClient)  # type: ignore[misc]
    captured: dict[str, object] = {}

    async def fake_request(method: str, url: str, **kwargs):  # type: ignore[override]
        captured["method"] = method
        captured["url"] = url
        captured["kwargs"] = kwargs
        return DummyResponse({"plan": "free", "subscription_state": "none"})

    monkeypatch.setattr(client, "request", fake_request)

    result = asyncio.run(client.get_commercial_state(42))

    assert result == {"plan": "free", "subscription_state": "none"}
    assert captured == {"method": "GET", "url": "/v1/users/42/commercial-state", "kwargs": {}}


def test_upload_user_resume_sends_raw_pdf(monkeypatch) -> None:
    client = SkillraApiClient.__new__(SkillraApiClient)  # type: ignore[misc]
    captured: dict[str, object] = {}

    async def fake_request(method: str, url: str, **kwargs):  # type: ignore[override]
        captured["method"] = method
        captured["url"] = url
        captured["content"] = kwargs["content"]
        captured["headers"] = kwargs["headers"]
        captured["params"] = kwargs["params"]
        return DummyResponse({"extracted_skills": ["Python"]})

    monkeypatch.setattr(client, "request", fake_request)

    async def run_request() -> dict[str, object]:
        return await client.upload_user_resume(42, b"%PDF", "resume.pdf")

    result = asyncio.run(run_request())

    assert result == {"extracted_skills": ["Python"]}
    assert captured == {
        "method": "POST",
        "url": "/v1/users/42/resume",
        "content": b"%PDF",
        "headers": {"Content-Type": "application/pdf"},
        "params": {"filename": "resume.pdf"},
    }


def test_generate_career_plan_actions_calls_expected_endpoint(monkeypatch) -> None:
    client = SkillraApiClient.__new__(SkillraApiClient)  # type: ignore[misc]
    captured: dict[str, object] = {}

    async def fake_request(method: str, url: str, **kwargs):  # type: ignore[override]
        captured["method"] = method
        captured["url"] = url
        captured["json"] = kwargs["json"]
        return DummyResponse({"actions": []})

    monkeypatch.setattr(client, "request", fake_request)

    async def run_request() -> dict[str, object]:
        return await client.generate_career_plan_actions(42, limit=3, replace_generated=True)

    result = asyncio.run(run_request())

    assert result == {"actions": []}
    assert captured == {
        "method": "POST",
        "url": "/v1/users/42/career-plan/generate-actions",
        "json": {"limit": 3, "replace_generated": True, "source": "bot"},
    }


def test_market_trend_methods_call_expected_endpoints(monkeypatch) -> None:
    client = SkillraApiClient.__new__(SkillraApiClient)  # type: ignore[misc]
    calls: list[tuple[str, str, dict[str, object]]] = []

    async def fake_request(method: str, url: str, **kwargs):  # type: ignore[override]
        calls.append((method, url, kwargs.get("params", {})))
        return DummyResponse({"data": []})

    monkeypatch.setattr(client, "request", fake_request)

    async def run_request() -> None:
        await client.salary_trend("Data Analyst", "Middle", weeks=8)
        await client.vacancy_count_trend("Data Analyst", grade="Middle", weeks=8)
        await client.skill_demand_trend("Python", role="Data Analyst", grade="Middle", weeks=8)
        await client.career_graph("Data Analyst")

    asyncio.run(run_request())

    assert calls == [
        ("GET", "/v1/market/trends/salary", {"role": "Data Analyst", "grade": "Middle", "weeks": 8}),
        ("GET", "/v1/market/trends/vacancy-count", {"role": "Data Analyst", "weeks": 8, "grade": "Middle"}),
        (
            "GET",
            "/v1/market/trends/skill-demand",
            {"skill": "Python", "weeks": 8, "role": "Data Analyst", "grade": "Middle"},
        ),
        ("GET", "/v1/market/career-graph", {"role": "Data Analyst"}),
    ]


def test_search_vacancies_returns_results(monkeypatch) -> None:
    client = SkillraApiClient.__new__(SkillraApiClient)  # type: ignore[misc]
    captured: dict[str, object] = {}

    async def fake_request(method: str, url: str, **kwargs):  # type: ignore[override]
        captured["method"] = method
        captured["url"] = url
        captured["params"] = kwargs["params"]
        return DummyResponse({"results": [{"title": "Python Developer"}]})

    monkeypatch.setattr(client, "request", fake_request)

    async def run_request() -> list[dict[str, object]]:
        return await client.search_vacancies("Python", limit=5)

    results = asyncio.run(run_request())

    assert captured == {
        "method": "GET",
        "url": "/v1/search/vacancies",
        "params": {"q": "Python", "limit": 5},
    }
    assert results == [{"title": "Python Developer"}]


def test_search_vacancies_payload_sends_profile_filters(monkeypatch) -> None:
    client = SkillraApiClient.__new__(SkillraApiClient)  # type: ignore[misc]
    captured: dict[str, object] = {}

    async def fake_request(method: str, url: str, **kwargs):  # type: ignore[override]
        captured["method"] = method
        captured["url"] = url
        captured["params"] = kwargs["params"]
        return DummyResponse({"results": [], "index_status": "success"})

    monkeypatch.setattr(client, "request", fake_request)

    async def run_request() -> dict[str, object]:
        return await client.search_vacancies_payload(
            "Python",
            limit=5,
            role="analyst",
            grade="middle",
            country="Россия",
            city="Москва",
        )

    payload = asyncio.run(run_request())

    assert captured == {
        "method": "GET",
        "url": "/v1/search/vacancies",
        "params": {
            "q": "Python",
            "limit": 5,
            "role": "analyst",
            "grade": "middle",
            "country": "Россия",
            "city": "Москва",
        },
    }
    assert payload == {"results": [], "index_status": "success"}


def test_vacancy_outcome_methods_call_expected_endpoints(monkeypatch) -> None:
    client = SkillraApiClient.__new__(SkillraApiClient)  # type: ignore[misc]
    calls: list[tuple[str, str, dict[str, object]]] = []

    async def fake_request(method: str, url: str, **kwargs):  # type: ignore[override]
        calls.append((method, url, kwargs["json"]))
        return DummyResponse({"id": 7, "application_status": "saved"})

    monkeypatch.setattr(client, "request", fake_request)

    async def run_request() -> None:
        await client.save_career_plan_vacancy(
            42,
            {
                "hh_vacancy_id": "101",
                "title": "Data Analyst",
                "url": "https://hh.ru/vacancy/101",
            },
        )
        await client.update_application_outcome(42, 7, "interview", source="bot")

    asyncio.run(run_request())

    assert calls == [
        (
            "POST",
            "/v1/users/42/career-plan/saved-vacancies",
            {
                "hh_vacancy_id": "101",
                "title": "Data Analyst",
                "url": "https://hh.ru/vacancy/101",
                "source": "bot",
            },
        ),
        (
            "POST",
            "/v1/users/42/career-plan/actions/7/outcome",
            {"status": "interview", "source": "bot"},
        ),
    ]


def test_export_persona_pdf_returns_content(monkeypatch) -> None:
    client = SkillraApiClient.__new__(SkillraApiClient)  # type: ignore[misc]
    captured: dict[str, object] = {}
    payload = {"target_role": "Data Analyst", "current_skills": ["Python"]}

    async def fake_request(method: str, url: str, **kwargs):  # type: ignore[override]
        captured["method"] = method
        captured["url"] = url
        captured["json"] = kwargs["json"]
        return DummyResponse({}, content=b"%PDF")

    monkeypatch.setattr(client, "request", fake_request)

    async def run_request() -> bytes:
        return await client.export_persona_pdf(payload)

    content = asyncio.run(run_request())

    assert captured == {
        "method": "POST",
        "url": "/v1/persona/export-pdf",
        "json": payload,
    }
    assert content == b"%PDF"


def test_export_csv_and_share_methods(monkeypatch) -> None:
    client = SkillraApiClient.__new__(SkillraApiClient)  # type: ignore[misc]
    calls: list[tuple[str, str, dict[str, object]]] = []
    payload = {"target_role": "Data Analyst", "current_skills": ["Python"]}

    async def fake_request(method: str, url: str, **kwargs):  # type: ignore[override]
        calls.append((method, url, kwargs["json"]))
        if url.endswith("export-csv"):
            return DummyResponse({}, content=b"skill,share\nPython,0.8\n")
        return DummyResponse({"token": "share-token"})

    monkeypatch.setattr(client, "request", fake_request)

    async def run_request() -> tuple[bytes, dict[str, object]]:
        return await client.export_persona_csv(payload), await client.create_persona_share(payload)

    csv_bytes, share = asyncio.run(run_request())

    assert csv_bytes.startswith(b"skill,share")
    assert share == {"token": "share-token"}
    assert calls == [
        ("POST", "/v1/persona/export-csv", payload),
        ("POST", "/v1/persona/share", payload),
    ]


def test_digest_history_method_calls_expected_endpoint(monkeypatch) -> None:
    client = SkillraApiClient.__new__(SkillraApiClient)  # type: ignore[misc]
    captured: dict[str, object] = {}

    async def fake_request(method: str, url: str, **kwargs):  # type: ignore[override]
        captured["method"] = method
        captured["url"] = url
        captured["params"] = kwargs["params"]
        return DummyResponse({"items": [], "total": 0})

    monkeypatch.setattr(client, "request", fake_request)

    async def run_request() -> dict[str, object]:
        return await client.get_digest_history(42, limit=7, offset=14)

    result = asyncio.run(run_request())

    assert result == {"items": [], "total": 0}
    assert captured == {
        "method": "GET",
        "url": "/v1/users/42/digest/history",
        "params": {"limit": 7, "offset": 14},
    }
