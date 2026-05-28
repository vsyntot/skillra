from __future__ import annotations

from fastapi import APIRouter, Depends
from fastapi.responses import Response
from prometheus_client import generate_latest

from skillra_api.deps.auth import require_admin_token

router = APIRouter()


@router.get(
    "/metrics",
    response_class=Response,
    tags=["metrics"],
)
def get_metrics(_: str = Depends(require_admin_token)) -> Response:
    """Expose Prometheus metrics, protected by admin token."""

    return Response(
        content=generate_latest(),
        media_type="text/plain; version=0.0.4; charset=utf-8",
    )


@router.get(
    "/internal/metrics",
    response_class=Response,
    tags=["metrics"],
)
def get_internal_metrics() -> Response:
    """Expose Prometheus metrics for internal scraping."""

    return Response(
        content=generate_latest(),
        media_type="text/plain; version=0.0.4; charset=utf-8",
    )
