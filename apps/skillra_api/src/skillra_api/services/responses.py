from __future__ import annotations

from fastapi.responses import JSONResponse
from skillra_api.datastore import DataStore


def data_unavailable_error(datastore: DataStore) -> JSONResponse:
    return JSONResponse(
        status_code=503,
        content={
            "error_code": "DATA_UNAVAILABLE",
            "message": "Данные недоступны. Запусти pipeline: python scripts/run_pipeline.py",
            "details": {"datastore": datastore.status()},
        },
    )


def invalid_skills_error(invalid_skills: list[str]) -> JSONResponse:
    return JSONResponse(
        status_code=400,
        content={
            "error_code": "UNKNOWN_SKILLS",
            "message": "Some of the provided skills are not recognised.",
            "details": {"invalid_skills": list(invalid_skills)},
        },
    )


def profile_not_found_error(telegram_user_id: int) -> JSONResponse:
    return JSONResponse(
        status_code=404,
        content={
            "error_code": "PROFILE_NOT_FOUND",
            "message": "Profile for the user was not found.",
            "details": {"telegram_user_id": telegram_user_id},
        },
    )


def subscription_not_found_error(telegram_user_id: int) -> JSONResponse:
    return JSONResponse(
        status_code=404,
        content={
            "error_code": "SUBSCRIPTION_NOT_FOUND",
            "message": "Weekly subscription for the user was not found.",
            "details": {"telegram_user_id": telegram_user_id},
        },
    )


def subscription_not_claimed_error(telegram_user_id: int) -> JSONResponse:
    return JSONResponse(
        status_code=409,
        content={
            "error_code": "SUBSCRIPTION_NOT_CLAIMED",
            "message": "Subscription must be claimed before acknowledgement.",
            "details": {"telegram_user_id": telegram_user_id},
        },
    )


def subscription_lock_mismatch_error(telegram_user_id: int) -> JSONResponse:
    return JSONResponse(
        status_code=409,
        content={
            "error_code": "SUBSCRIPTION_LOCK_MISMATCH",
            "message": "Lock token does not match the active claim.",
            "details": {"telegram_user_id": telegram_user_id},
        },
    )


def invalid_time_error(time_local: str) -> JSONResponse:
    return JSONResponse(
        status_code=422,
        content={
            "error_code": "VALIDATION_ERROR",
            "message": "time_local must be in HH:MM 24h format.",
            "details": {"time_local": time_local},
        },
    )


def invalid_timezone_error(timezone_name: str) -> JSONResponse:
    return JSONResponse(
        status_code=422,
        content={
            "error_code": "VALIDATION_ERROR",
            "message": "Timezone must be a valid IANA name.",
            "details": {"timezone": timezone_name},
        },
    )


def invalid_timestamp_error(timestamp: str | None) -> JSONResponse:
    return JSONResponse(
        status_code=400,
        content={
            "error_code": "INVALID_TIMESTAMP",
            "message": "now_utc must be an ISO timestamp with timezone.",
            "details": {"now_utc": timestamp},
        },
    )
