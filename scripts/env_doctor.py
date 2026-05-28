#!/usr/bin/env python3
"""Validate local or production env files against the Skillra env schema."""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from urllib.parse import urlparse

try:
    from env_contract import (
        SUPPORTED_PROFILES,
        default_value,
        is_placeholder,
        is_required,
        iter_env_vars,
        load_schema,
        parse_env_file,
        profile_value,
        schema_key_set,
    )
except ModuleNotFoundError:  # pragma: no cover - used when imported as scripts.env_doctor
    from scripts.env_contract import (
        SUPPORTED_PROFILES,
        default_value,
        is_placeholder,
        is_required,
        iter_env_vars,
        load_schema,
        parse_env_file,
        profile_value,
        schema_key_set,
    )


DEFAULT_SCHEMA = Path("infra/env/schema.yml")
PROTECTED_PROFILES = {"prod", "staging"}


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate a Skillra env file")
    parser.add_argument("--schema", type=Path, default=DEFAULT_SCHEMA)
    parser.add_argument("--profile", choices=sorted(SUPPORTED_PROFILES), required=True)
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument("--strict-unknown", action="store_true", help="Treat unknown env keys as errors.")
    parser.add_argument("--warn-only", action="store_true", help="Print errors but exit 0.")
    return parser.parse_args()


def _is_url(value: str) -> bool:
    parsed = urlparse(value)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def _normalize_bot_username(value: str | None) -> str:
    return (value or "").strip().removeprefix("@").lower()


def _is_local_url(value: str | None) -> bool:
    if not value:
        return False
    parsed = urlparse(value)
    host = (parsed.hostname or "").lower()
    return host in {"localhost", "127.0.0.1", "0.0.0.0", "::1", "host.docker.internal"}


def _validate_type(name: str, value: str, expected_type: str) -> str | None:
    if value == "":
        return None
    if expected_type == "int":
        try:
            int(value)
        except ValueError:
            return f"{name} must be an integer"
    elif expected_type == "float":
        try:
            float(value)
        except ValueError:
            return f"{name} must be a float"
    elif expected_type == "bool":
        if value.lower() not in {"0", "1", "true", "false", "yes", "no"}:
            return f"{name} must be a boolean-like value"
    elif expected_type == "url":
        if not _is_url(value):
            return f"{name} must be an http(s) URL"
    elif expected_type == "postgres_url":
        if not value.startswith(("postgresql://", "postgresql+asyncpg://")):
            return f"{name} must be a PostgreSQL URL"
    elif expected_type == "redis_url":
        if not value.startswith("redis://"):
            return f"{name} must be a Redis URL"
    elif expected_type == "bcrypt_hash":
        normalized = value.replace("$$", "$")
        if normalized and not re.match(r"^\$2[aby]\$", normalized):
            return f"{name} must look like a bcrypt hash"
    return None


def _find_duplicate_minio_role_keys(values: dict[str, str]) -> list[str]:
    role_keys = ["MINIO_ACCESS_KEY", "S3_ACCESS_KEY_ID", "S3_BACKUP_ACCESS_KEY_ID"]
    seen: dict[str, str] = {}
    duplicates: list[str] = []
    for key in role_keys:
        value = values.get(key)
        if not value:
            continue
        previous_key = seen.get(value)
        if previous_key:
            duplicates.append(f"{previous_key} and {key}")
        else:
            seen[value] = key
    return duplicates


def validate_env(
    schema: dict,
    profile: str,
    env_file: Path,
    *,
    strict_unknown: bool = False,
) -> tuple[list[str], list[str]]:
    values, duplicates = parse_env_file(env_file)
    errors: list[str] = []
    warnings: list[str] = []

    if not env_file.exists():
        errors.append(f"{env_file} does not exist")
        return errors, warnings

    for duplicate in duplicates:
        errors.append(f"{duplicate} is defined more than once")

    known_keys = schema_key_set(schema)
    unknown_keys = sorted(set(values) - known_keys)
    for key in unknown_keys:
        message = f"{key} is not declared in infra/env/schema.yml"
        if strict_unknown:
            errors.append(message)
        else:
            warnings.append(message)

    for env_var in iter_env_vars(schema):
        name = env_var.name
        spec = env_var.spec
        value = values.get(name)
        required = is_required(spec, profile, values)
        if required and value is None:
            errors.append(f"{name} is required for {profile}")
            continue
        if value is None:
            continue

        expected_type = str(spec.get("type") or "string")
        type_error = _validate_type(name, value, expected_type)
        if type_error:
            errors.append(type_error)

        allowed = spec.get("allowed")
        if allowed and value and value not in {str(item) for item in allowed}:
            errors.append(f"{name} must be one of: {', '.join(str(item) for item in allowed)}")

        if profile in PROTECTED_PROFILES:
            if spec.get("secret") and is_placeholder(value):
                errors.append(f"{name} is a {profile} secret and still contains a placeholder")
            elif required and is_placeholder(value):
                errors.append(f"{name} is required for {profile} and still contains a placeholder")
        elif spec.get("secret") and is_placeholder(value):
            warnings.append(f"{name} uses a placeholder value in local env")

    if profile == "prod":
        public_base = values.get("SKILLRA_PUBLIC_BASE_URL", "")
        webhook_url = values.get("TELEGRAM_WEBHOOK_URL", "")
        if "example.com" in webhook_url and values.get("BOT_MODE") == "webhook":
            errors.append("TELEGRAM_WEBHOOK_URL cannot be example.com when BOT_MODE=webhook")
        if public_base and not public_base.startswith("https://"):
            errors.append("SKILLRA_PUBLIC_BASE_URL must use https in prod")
        if public_base and public_base.rstrip("/") != "https://skillra.ru":
            errors.append("SKILLRA_PUBLIC_BASE_URL must be https://skillra.ru in prod")
        if values.get("BOT_MODE") == "webhook" and webhook_url.rstrip("/") != "https://tg.skillra.ru/webhook":
            errors.append("TELEGRAM_WEBHOOK_URL must be https://tg.skillra.ru/webhook in prod webhook mode")
    elif profile == "staging":
        public_base = values.get("SKILLRA_PUBLIC_BASE_URL", "")
        webhook_url = values.get("TELEGRAM_WEBHOOK_URL", "")
        if public_base and not public_base.startswith("https://"):
            errors.append("SKILLRA_PUBLIC_BASE_URL must use https in staging")
        if public_base and public_base.rstrip("/") == "https://skillra.ru":
            errors.append("SKILLRA_PUBLIC_BASE_URL must not point to production in staging")
        if public_base and public_base.rstrip("/") != "https://staging.skillra.ru":
            errors.append("SKILLRA_PUBLIC_BASE_URL must be https://staging.skillra.ru in staging")
        if values.get("BOT_MODE") == "webhook":
            if webhook_url.rstrip("/") == "https://tg.skillra.ru/webhook":
                errors.append("TELEGRAM_WEBHOOK_URL must not point to production in staging")
            if webhook_url.rstrip("/") != "https://tg.staging.skillra.ru/webhook":
                errors.append(
                    "TELEGRAM_WEBHOOK_URL must be https://tg.staging.skillra.ru/webhook in staging webhook mode"
                )
        staging_prod_values = {
            "SKILLRA_DATA_VOLUME_BASE": "/var/lib/skillra",
            "POSTGRES_DB": "skillra",
            "MINIO_BUCKET_RESUMES": "skillra-resumes",
            "MINIO_BUCKET_REPORTS": "skillra-reports",
            "S3_BUCKET_RAW_HH": "skillra-raw-hh",
            "S3_BUCKET_PROCESSED": "skillra-processed",
            "S3_BUCKET_BACKUPS": "skillra-backups",
        }
        for key, prod_value in staging_prod_values.items():
            if values.get(key, "").rstrip("/") == prod_value:
                errors.append(f"{key} must not use the production value in staging")
        database_url = values.get("DATABASE_URL", "")
        if database_url:
            database_name = urlparse(database_url).path.lstrip("/")
            if database_name == "skillra":
                errors.append("DATABASE_URL must not point to the production database name in staging")

    official_bot = _normalize_bot_username(values.get("TELEGRAM_PROD_BOT_USERNAME") or "skillra_bot")
    bot_username = _normalize_bot_username(values.get("TELEGRAM_BOT_USERNAME"))
    runtime_env = (values.get("SKILLRA_RUNTIME_ENV") or values.get("SKILLRA_ENV") or profile).strip().lower()
    if profile == "prod" and values.get("SKILLRA_BILLING_REAL_PROVIDER_LAUNCH_ENABLED", "").lower() in {
        "1",
        "true",
        "yes",
    }:
        errors.append("SKILLRA_BILLING_REAL_PROVIDER_LAUNCH_ENABLED must remain disabled until launch approval")
    if profile == "prod" and values.get("SKILLRA_BILLING_SANDBOX_WEBHOOK_ENABLED", "").lower() in {
        "1",
        "true",
        "yes",
    }:
        errors.append("SKILLRA_BILLING_SANDBOX_WEBHOOK_ENABLED must not be enabled in prod")
    if bot_username == official_bot:
        if profile != "prod" or runtime_env not in {"prod", "production"}:
            errors.append(f"@{official_bot} cannot be used outside prod runtime")
        if _is_local_url(values.get("SKILLRA_API_BASE_URL")):
            errors.append(f"@{official_bot} cannot use local SKILLRA_API_BASE_URL")
    elif profile == "prod" and bot_username:
        errors.append(f"TELEGRAM_BOT_USERNAME must be {official_bot} in prod")
    elif profile == "staging" and bot_username == official_bot:
        errors.append(f"TELEGRAM_BOT_USERNAME must not be {official_bot} in staging")

    duplicate_minio_roles = _find_duplicate_minio_role_keys(values)
    for duplicate in duplicate_minio_roles:
        message = f"{duplicate} must be distinct for least-privilege MinIO access"
        if profile in PROTECTED_PROFILES:
            errors.append(message)
        else:
            warnings.append(message)

    defaults: dict[str, str] = {}
    for env_var in iter_env_vars(schema):
        spec = env_var.spec
        required_profiles = spec.get("required") or []
        has_profile_default = profile_value(spec, "default", profile) is not None
        has_required_when = bool(spec.get("required_when"))
        if not has_profile_default and profile not in required_profiles and not has_required_when:
            continue
        value = default_value(spec, profile)
        if value is not None:
            defaults[env_var.name] = value
    missing_optional_defaults = sorted(set(defaults) - set(values))
    for key in missing_optional_defaults:
        warnings.append(f"{key} is omitted; compose/runtime default will be used")

    return errors, warnings


def main() -> None:
    args = _parse_args()
    schema = load_schema(args.schema)
    errors, warnings = validate_env(schema, args.profile, args.env_file, strict_unknown=args.strict_unknown)

    for warning in warnings:
        print(f"[env-doctor] WARN: {warning}")
    for error in errors:
        print(f"[env-doctor] ERROR: {error}", file=sys.stderr)

    if errors and not args.warn_only:
        raise SystemExit(1)
    print(f"[env-doctor] OK: {args.env_file} checked for {args.profile}")


if __name__ == "__main__":
    main()
