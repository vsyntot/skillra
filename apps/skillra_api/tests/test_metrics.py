from __future__ import annotations

from collections.abc import Generator
from contextlib import contextmanager

from fastapi.testclient import TestClient
from skillra_api.config import Settings  # noqa: E402
from skillra_api.constants import ADMIN_TOKEN_HEADER  # noqa: E402
from skillra_api.main import create_app  # noqa: E402
from skillra_api.metrics import APPLICATION_OUTCOMES_TOTAL, CAREER_ACTIONS_TOTAL, PRODUCT_EVENTS_TOTAL  # noqa: E402
from skillra_api.routers import admin  # noqa: E402


@contextmanager
def _create_client(admin_token: str) -> Generator[TestClient, None, None]:
    settings = Settings(
        log_level="CRITICAL",
        admin_token=admin_token,
        database_url="",
        redis_url="",
        meilisearch_url="",
        data_watch_interval=0,
    )
    app = create_app(settings)
    with TestClient(app) as client:
        yield client


def test_metrics_requires_admin_token(admin_token: str) -> None:
    with _create_client(admin_token) as client:
        response = client.get("/metrics")

        assert response.status_code == 403
        assert response.json() == {
            "error_code": "ADMIN_TOKEN_REQUIRED",
            "message": "Admin token is required for admin endpoints.",
            "details": {},
        }


def test_metrics_returns_prometheus_payload(admin_token: str) -> None:
    with _create_client(admin_token) as client:
        response = client.get("/metrics", headers={ADMIN_TOKEN_HEADER: admin_token})

        assert response.status_code == 200
        assert response.headers["content-type"] == "text/plain; version=0.0.4; charset=utf-8"
        assert "# HELP" in response.text
        assert "python_info" in response.text


def test_metrics_expose_request_latency(admin_token: str) -> None:
    with _create_client(admin_token) as client:
        client.get("/health")

        response = client.get("/metrics", headers={ADMIN_TOKEN_HEADER: admin_token})

        assert 'skillra_api_request_latency_seconds_count{method="GET",path="/health",status="200"}' in response.text


def test_metrics_increment_error_counter(admin_token: str) -> None:
    with _create_client(admin_token) as client:
        client.get("/metrics")

        response = client.get("/metrics", headers={ADMIN_TOKEN_HEADER: admin_token})

        assert 'skillra_api_request_errors_total{method="GET",path="/metrics",status="403"}' in response.text


def test_metrics_expose_vacancy_indexer_state(admin_token: str) -> None:
    admin._set_indexer_success({"inserted": 3, "indexed": 2}, "test")
    admin._set_indexer_failure(RuntimeError("boom"), "test")

    with _create_client(admin_token) as client:
        response = client.get("/metrics", headers={ADMIN_TOKEN_HEADER: admin_token})

    assert "skillra_vacancy_indexer_last_success_timestamp_seconds" in response.text
    assert "skillra_vacancy_indexer_last_failure_timestamp_seconds" in response.text
    assert "skillra_vacancy_indexer_last_indexed_total 2.0" in response.text
    assert "skillra_vacancy_indexer_failures_total" in response.text


def test_metrics_expose_datastore_reload_state(admin_token: str) -> None:
    admin._set_datastore_reload_success()
    admin._set_datastore_reload_failure("indexer", RuntimeError("boom"))

    with _create_client(admin_token) as client:
        response = client.get("/metrics", headers={ADMIN_TOKEN_HEADER: admin_token})

    assert 'skillra_datastore_reloads_total{status="success"}' in response.text
    assert 'skillra_datastore_reloads_total{status="failed"}' in response.text
    assert 'skillra_datastore_reload_failures_total{stage="indexer"}' in response.text
    assert "skillra_datastore_reload_last_success_timestamp_seconds" in response.text
    assert "skillra_datastore_reload_last_failure_timestamp_seconds" in response.text


def test_metrics_expose_product_loop_counters_without_pii_labels(admin_token: str) -> None:
    PRODUCT_EVENTS_TOTAL.labels(event_type="vacancy_saved", source="api").inc()
    CAREER_ACTIONS_TOTAL.labels(action_type="learning", recommendation_source="skill_gap").inc()
    APPLICATION_OUTCOMES_TOTAL.labels(status="interview", source="user").inc()

    with _create_client(admin_token) as client:
        response = client.get("/metrics", headers={ADMIN_TOKEN_HEADER: admin_token})

    assert 'skillra_product_events_total{event_type="vacancy_saved",source="api"}' in response.text
    assert 'skillra_career_actions_total{action_type="learning",recommendation_source="skill_gap"}' in response.text
    assert 'skillra_application_outcomes_total{source="user",status="interview"}' in response.text
    product_metric_lines = "\n".join(
        line
        for line in response.text.splitlines()
        if line.startswith(
            (
                "skillra_product_events_total",
                "skillra_career_actions_total",
                "skillra_application_outcomes_total",
            )
        )
    )
    assert "telegram_user_id" not in product_metric_lines
