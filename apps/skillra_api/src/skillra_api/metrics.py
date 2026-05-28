"""Prometheus metrics for Skillra API."""

from __future__ import annotations

from prometheus_client import Counter, Gauge, Histogram

REQUEST_LATENCY_SECONDS = Histogram(
    "skillra_api_request_latency_seconds",
    "Request latency in seconds",
    ["method", "path", "status"],
)

REQUEST_ERRORS_TOTAL = Counter(
    "skillra_api_request_errors_total",
    "Total number of error responses",
    ["method", "path", "status"],
)

DATASTORE_ROWS = Gauge(
    "skillra_datastore_rows_total",
    "Number of rows in each loaded dataset",
    ["dataset"],
)

DATASTORE_RELOADS_TOTAL = Counter(
    "skillra_datastore_reloads_total",
    "Total admin datastore reload attempts by bounded status.",
    ["status"],
)

DATASTORE_RELOAD_LAST_SUCCESS_TIMESTAMP_SECONDS = Gauge(
    "skillra_datastore_reload_last_success_timestamp_seconds",
    "Unix timestamp of the last successful admin datastore reload.",
)

DATASTORE_RELOAD_LAST_FAILURE_TIMESTAMP_SECONDS = Gauge(
    "skillra_datastore_reload_last_failure_timestamp_seconds",
    "Unix timestamp of the last failed admin datastore reload.",
)

DATASTORE_RELOAD_FAILURES_TOTAL = Counter(
    "skillra_datastore_reload_failures_total",
    "Total failed admin datastore reloads by bounded failure stage.",
    ["stage"],
)

DATASTORE_RELOAD_REDIS_PUBLISH_FAILURES_TOTAL = Counter(
    "skillra_datastore_reload_redis_publish_failures_total",
    "Total Redis datastore_reload publish failures after successful reload.",
)

# --- Business metrics (Sprint-008 TASK-10) ---

PROFILES_TOTAL = Counter(
    "skillra_profiles_total",
    "Total user profiles created or updated",
)

DIGESTS_SENT_TOTAL = Counter(
    "skillra_digests_sent_total",
    "Total weekly digests sent successfully",
)

PERSONA_ANALYSES_TOTAL = Counter(
    "skillra_persona_analyses_total",
    "Total persona analyses performed",
)

PRODUCT_EVENTS_TOTAL = Counter(
    "skillra_product_events_total",
    "Total product-loop events recorded by bounded event type and source.",
    ["event_type", "source"],
)

EVIDENCE_EXPLAINER_REQUESTS_TOTAL = Counter(
    "skillra_evidence_explainer_requests_total",
    "Total bounded evidence explainer requests by runtime, task, surface and bounded status.",
    ["runtime_env", "task", "surface", "status"],
)

EVIDENCE_EXPLAINER_BLOCKED_CLAIMS_TOTAL = Counter(
    "skillra_evidence_explainer_blocked_claims_total",
    "Total evidence explainer blocked-claim guardrail hits.",
    ["runtime_env", "task", "claim"],
)

EVIDENCE_EXPLAINER_LATENCY_SECONDS = Histogram(
    "skillra_evidence_explainer_latency_seconds",
    "Evidence explainer request latency in seconds.",
    ["runtime_env", "task", "surface", "status"],
)

CAREER_ACTIONS_TOTAL = Counter(
    "skillra_career_actions_total",
    "Total career-plan actions created by bounded action type and recommendation source.",
    ["action_type", "recommendation_source"],
)

APPLICATION_OUTCOMES_TOTAL = Counter(
    "skillra_application_outcomes_total",
    "Total application outcome transitions recorded by bounded status and source.",
    ["status", "source"],
)

ACTIVE_SUBSCRIPTIONS = Gauge(
    "skillra_active_subscriptions",
    "Number of active weekly subscriptions",
)

VACANCY_INDEXER_LAST_SUCCESS_TIMESTAMP_SECONDS = Gauge(
    "skillra_vacancy_indexer_last_success_timestamp_seconds",
    "Unix timestamp of the last successful vacancy indexer run",
)

VACANCY_INDEXER_LAST_FAILURE_TIMESTAMP_SECONDS = Gauge(
    "skillra_vacancy_indexer_last_failure_timestamp_seconds",
    "Unix timestamp of the last failed vacancy indexer run",
)

VACANCY_INDEXER_LAST_INDEXED_TOTAL = Gauge(
    "skillra_vacancy_indexer_last_indexed_total",
    "Number of vacancies indexed during the last successful vacancy indexer run",
)

VACANCY_INDEXER_FAILURES_TOTAL = Counter(
    "skillra_vacancy_indexer_failures_total",
    "Total number of failed vacancy indexer runs",
)

DATA_RUN_STATE = Gauge(
    "skillra_data_run_state",
    "Latest data pipeline run state. Current state is 1, other known states are 0.",
    ["state", "source"],
)

DATA_RUN_RAW_ROWS = Gauge(
    "skillra_data_run_raw_rows_total",
    "Raw rows reported by the latest data pipeline run.",
    ["source"],
)

DATA_RUN_PROCESSED_ROWS = Gauge(
    "skillra_data_run_processed_rows_total",
    "Processed rows reported by the latest data pipeline run.",
    ["source"],
)

DATA_RUN_LAST_SUCCESS_TIMESTAMP_SECONDS = Gauge(
    "skillra_data_run_last_success_timestamp_seconds",
    "Unix timestamp of the latest published data pipeline run.",
    ["source"],
)

DATA_RUN_LAST_FAILURE_TIMESTAMP_SECONDS = Gauge(
    "skillra_data_run_last_failure_timestamp_seconds",
    "Unix timestamp of the latest failed data pipeline run.",
    ["source"],
)
