"""Request logging middleware for Skillra API."""

from __future__ import annotations

import logging
import time

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

from skillra_api.metrics import REQUEST_ERRORS_TOTAL, REQUEST_LATENCY_SECONDS
from skillra_api.middlewares.request_id import RequestIDMiddleware

logger = logging.getLogger(__name__)


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """Log basic request metadata for observability without leaking PII."""

    header_name = RequestIDMiddleware.header_name

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        start_time = time.perf_counter()
        response: Response | None = None
        status_code: int | None = None

        try:
            response = await call_next(request)
            status_code = response.status_code
            return response
        except Exception:
            status_code = 500
            raise
        finally:
            latency_seconds = time.perf_counter() - start_time
            latency_ms = latency_seconds * 1000
            request_id = self._resolve_request_id(request, response)
            safe_path = self._resolve_safe_path(request)
            resolved_status = status_code if status_code is not None else "unknown"

            logger.info(
                "Handled request method=%s path=%s status=%s latency_ms=%.2f request_id=%s",
                request.method,
                safe_path,
                resolved_status,
                latency_ms,
                request_id,
            )

            if status_code is not None:
                REQUEST_LATENCY_SECONDS.labels(
                    method=request.method,
                    path=safe_path,
                    status=str(status_code),
                ).observe(latency_seconds)

                if status_code >= 400:
                    REQUEST_ERRORS_TOTAL.labels(
                        method=request.method,
                        path=safe_path,
                        status=str(status_code),
                    ).inc()

    def _resolve_request_id(self, request: Request, response: Response | None) -> str:
        if hasattr(request.state, "request_id"):
            return str(request.state.request_id)

        if response and self.header_name in response.headers:
            return response.headers[self.header_name]

        return request.headers.get(self.header_name, "")

    @staticmethod
    def _resolve_safe_path(request: Request) -> str:
        route = request.scope.get("route")
        if route is not None:
            route_path = getattr(route, "path", None)
            if route_path:
                return route_path

        return request.url.path
