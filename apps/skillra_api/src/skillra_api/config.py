"""Application configuration for Skillra API."""

from functools import lru_cache
from typing import Any, Optional

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Environment-driven configuration for the API service."""

    app_name: str = Field("Skillra API", description="Human-friendly application name")
    api_host: str = Field("0.0.0.0", alias="SKILLRA_API_HOST", description="Host for uvicorn server")
    api_port: int = Field(8000, alias="SKILLRA_API_PORT", description="Port for uvicorn server")
    runtime_env: str = Field(
        "local",
        alias="SKILLRA_RUNTIME_ENV",
        description="Runtime contour marker exposed by health checks: local, staging or prod.",
    )
    public_base_url: Optional[str] = Field(
        None,
        alias="SKILLRA_PUBLIC_BASE_URL",
        description="Public base URL for the current runtime contour.",
    )

    api_token: Optional[str] = Field(None, alias="SKILLRA_API_TOKEN", description="Service token for API clients")
    admin_token: Optional[str] = Field(
        None,
        alias="SKILLRA_ADMIN_TOKEN",
        description="Admin token for privileged endpoints",
    )

    data_dir: str = Field(
        "data/processed/latest", alias="SKILLRA_DATA_DIR", description="Directory containing processed parquet datasets"
    )
    features_path: str = Field(
        "data/processed/latest/hh_features.parquet",
        alias="SKILLRA_FEATURES_PATH",
        description="Path to features parquet file",
    )
    market_view_path: str = Field(
        "data/processed/latest/market_view.parquet",
        alias="SKILLRA_MARKET_VIEW_PATH",
        description="Path to market view parquet file",
    )
    dataset_meta_path: str = Field(
        "data/processed/latest/dataset_meta.json",
        alias="SKILLRA_DATASET_META_PATH",
        description="Path to dataset metadata file",
    )
    market_snapshots_path: str = Field(
        "data/processed/market_snapshots",
        alias="SKILLRA_MARKET_SNAPSHOTS_PATH",
        description="Directory containing weekly market snapshot parquet files",
    )

    database_url: Optional[str] = Field(None, alias="DATABASE_URL", description="Postgres connection URL")
    redis_url: Optional[str] = Field(None, alias="REDIS_URL", description="Redis URL for caching or rate limiting")

    log_level: str = Field("INFO", alias="LOG_LEVEL", description="Logging level for the service")
    log_format: str = Field("kv", alias="LOG_FORMAT", description="Logging format: 'json' or 'kv'")
    sentry_dsn: Optional[str] = Field(None, alias="SENTRY_DSN", description="Sentry DSN for error reporting")
    cors_origins: str = Field(
        "http://localhost:5173,http://127.0.0.1:5173",
        alias="SKILLRA_CORS_ORIGINS",
        description="Comma-separated list of allowed browser origins",
    )

    # Sprint-006 TASK-04: Subscription backoff settings
    subscription_max_attempt: int = Field(
        5, alias="SUBSCRIPTION_MAX_ATTEMPT", description="Max delivery attempts before giving up"
    )
    subscription_backoff_seconds: int = Field(
        3600,
        alias="SUBSCRIPTION_BACKOFF_SECONDS",
        description="Seconds to wait before retrying after repeated failures",
    )

    # Sprint-007 TASK-09: DataStore file watch interval
    data_watch_interval: float = Field(
        30.0,
        alias="SKILLRA_DATA_WATCH_INTERVAL",
        description="Seconds between file mtime checks; 0 = disabled",
    )

    # Sprint-007 TASK-08: Rate limiting
    rate_limit_persona: str = Field(
        "30/minute", alias="RATE_LIMIT_PERSONA", description="Rate limit for persona analyze endpoint"
    )
    rate_limit_market: str = Field(
        "60/minute", alias="RATE_LIMIT_MARKET", description="Rate limit for market segment endpoint"
    )
    rate_limit_default: str = Field("200/minute", alias="RATE_LIMIT_DEFAULT", description="Default rate limit")
    rate_limit_user_api_key: str = Field(
        "100/minute",
        alias="RATE_LIMIT_USER_API_KEY",
        description="Recommended per-user API key rate limit",
    )
    rate_limit_ip: str = Field("30/minute", alias="RATE_LIMIT_IP", description="Recommended anonymous/IP rate limit")

    # Sprint-008 TASK-04: MeiliSearch settings
    meilisearch_url: str = Field(
        "http://meilisearch:7700", alias="MEILISEARCH_URL", description="MeiliSearch service URL"
    )
    meilisearch_api_key: str = Field("masterKey", alias="MEILISEARCH_API_KEY", description="MeiliSearch master API key")

    min_market_n: int = Field(
        80,
        ge=1,
        alias="SKILLRA_MIN_MARKET_N",
        description="Min vacancy count for market segment to be shown",
    )

    minio_endpoint_url: Optional[str] = Field(None, alias="MINIO_ENDPOINT_URL", description="S3/MinIO endpoint URL")
    minio_access_key: Optional[str] = Field(None, alias="MINIO_ACCESS_KEY", description="S3/MinIO access key")
    minio_secret_key: Optional[str] = Field(None, alias="MINIO_SECRET_KEY", description="S3/MinIO secret key")
    minio_bucket_resumes: str = Field(
        "skillra-resumes", alias="MINIO_BUCKET_RESUMES", description="Bucket for uploaded resumes"
    )
    minio_bucket_reports: str = Field(
        "skillra-reports", alias="MINIO_BUCKET_REPORTS", description="Bucket for generated reports"
    )
    max_resume_bytes: int = Field(
        10_485_760, alias="SKILLRA_MAX_RESUME_BYTES", description="Maximum uploaded resume size in bytes"
    )
    storage_s3_timeout_seconds: float = Field(
        10.0,
        gt=0,
        alias="SKILLRA_STORAGE_S3_TIMEOUT_SECONDS",
        description="Per-attempt timeout for API S3/MinIO operations",
    )
    storage_s3_max_attempts: int = Field(
        2,
        ge=1,
        alias="SKILLRA_STORAGE_S3_MAX_ATTEMPTS",
        description="Maximum API S3/MinIO attempts for idempotent or key-stable operations",
    )
    storage_s3_max_concurrency: int = Field(
        8,
        ge=1,
        alias="SKILLRA_STORAGE_S3_MAX_CONCURRENCY",
        description="Maximum concurrent API S3/MinIO operations per process",
    )
    billing_fake_webhook_secret: str = Field(
        "skillra-local-fake-billing-secret",
        alias="SKILLRA_BILLING_FAKE_WEBHOOK_SECRET",
        description="HMAC secret for fake billing provider webhook tests and dry runs",
    )
    billing_fake_webhook_enabled: bool = Field(
        False,
        alias="SKILLRA_BILLING_FAKE_WEBHOOK_ENABLED",
        description="Enable the fake billing webhook adapter for local/CI tests. Keep disabled in production.",
    )
    billing_sandbox_webhook_enabled: bool = Field(
        False,
        alias="SKILLRA_BILLING_SANDBOX_WEBHOOK_ENABLED",
        description="Enable the signed sandbox/manual-invoice billing adapter for staging dry-runs.",
    )
    billing_sandbox_webhook_secret: str = Field(
        "skillra-local-sandbox-billing-secret",
        alias="SKILLRA_BILLING_SANDBOX_WEBHOOK_SECRET",
        description="HMAC secret for the sandbox/manual-invoice billing provider webhook.",
    )
    billing_sandbox_provider_name: str = Field(
        "manual_invoice",
        alias="SKILLRA_BILLING_SANDBOX_PROVIDER_NAME",
        description="Provider id for the staging sandbox/manual-invoice billing adapter.",
    )
    billing_real_provider_launch_enabled: bool = Field(
        False,
        alias="SKILLRA_BILLING_REAL_PROVIDER_LAUNCH_ENABLED",
        description="Production kill-switch for non-fake billing providers. Must remain disabled until approval.",
    )
    b2b_min_cohort_n: int = Field(
        10,
        ge=1,
        alias="SKILLRA_B2B_MIN_COHORT_N",
        description="Minimum active cohort members before B2B aggregate analytics are shown.",
    )
    b2b_min_cell_n: int = Field(
        5,
        ge=1,
        alias="SKILLRA_B2B_MIN_CELL_N",
        description="Minimum distinct users before B2B heatmap or metric cells are shown.",
    )
    evidence_explainer_enabled: bool = Field(
        False,
        alias="SKILLRA_EVIDENCE_EXPLAINER_ENABLED",
        description="Enable the bounded evidence explainer runtime. Keep disabled until offline eval passes.",
    )
    evidence_explainer_allowed_telegram_user_ids: str = Field(
        "",
        alias="SKILLRA_EVIDENCE_EXPLAINER_ALLOWED_TELEGRAM_USER_IDS",
        description="Comma-separated Telegram user ids allowed to use controlled evidence explainer enablement.",
    )
    evidence_explainer_prod_enable_approved: bool = Field(
        False,
        alias="SKILLRA_EVIDENCE_EXPLAINER_PROD_ENABLE_APPROVED",
        description=(
            "Explicit production approval gate for evidence explainer. "
            "Requires allowlist and remains false by default."
        ),
    )

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore", populate_by_name=True)

    def __init__(self, **values: Any) -> None:
        """Accept field-name kwargs even when environment aliases are configured."""

        normalized_values = dict(values)
        for field_name, field_info in self.__class__.model_fields.items():
            alias = field_info.alias
            if alias and field_name in normalized_values and alias not in normalized_values:
                normalized_values[alias] = normalized_values.pop(field_name)
        super().__init__(**normalized_values)

    @field_validator("log_format")
    @classmethod
    def validate_log_format(cls, value: str) -> str:
        normalized = value.lower()
        if normalized not in {"json", "kv"}:
            raise ValueError("LOG_FORMAT must be either 'json' or 'kv'")
        return normalized

    @field_validator("runtime_env")
    @classmethod
    def validate_runtime_env(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized not in {"local", "staging", "prod"}:
            raise ValueError("SKILLRA_RUNTIME_ENV must be one of: local, staging, prod")
        return normalized

    @field_validator("public_base_url")
    @classmethod
    def normalize_public_base_url(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        normalized = value.strip().rstrip("/")
        return normalized or None


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return cached settings instance built from environment variables."""

    return Settings()
