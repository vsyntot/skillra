from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette import status
from starlette.exceptions import HTTPException

logger = logging.getLogger(__name__)


def _error_response(status_code: int, error_code: str, message: str, details: Any | None = None) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={
            "error_code": error_code,
            "message": message,
            "details": details if details is not None else {},
        },
    )


async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:  # noqa: ARG001
    detail = exc.detail

    if isinstance(detail, Mapping) and {
        "error_code",
        "message",
        "details",
    }.issubset(detail):
        content = {
            "error_code": detail["error_code"],
            "message": detail["message"],
            "details": detail.get("details", {}),
        }
    else:
        content = {
            "error_code": "HTTP_ERROR",
            "message": str(detail) if detail else "HTTP error",
            "details": detail if isinstance(detail, Mapping) else {},
        }

    return JSONResponse(status_code=exc.status_code, content=content)


async def validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:  # noqa: ARG001
    details = {"errors": exc.errors()}
    if exc.body:
        details["body_present"] = True

    return _error_response(
        status.HTTP_422_UNPROCESSABLE_CONTENT,
        error_code="VALIDATION_ERROR",
        message="Request validation error.",
        details=details,
    )


async def generic_exception_handler(request: Request, exc: Exception) -> JSONResponse:  # noqa: ARG001
    logger.exception("Unhandled exception: %s", exc)

    return _error_response(
        status.HTTP_500_INTERNAL_SERVER_ERROR,
        error_code="INTERNAL_ERROR",
        message="Internal server error.",
        details={},
    )
