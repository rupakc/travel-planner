"""Request-level analytics logging middleware."""

import json
import logging
import time

from starlette.middleware.base import BaseHTTPMiddleware

logger = logging.getLogger(__name__)

# Paths that are too noisy to log individually
_SKIP_PATHS = {"/health", "/docs", "/openapi.json", "/redoc"}


class AnalyticsMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        if request.url.path in _SKIP_PATHS:
            return await call_next(request)

        start = time.monotonic()
        response = await call_next(request)
        duration_ms = round((time.monotonic() - start) * 1000)

        logger.info(
            json.dumps(
                {
                    "event": "api_request",
                    "method": request.method,
                    "path": request.url.path,
                    "status_code": response.status_code,
                    "duration_ms": duration_ms,
                    "user": getattr(request.state, "username", "anonymous"),
                }
            )
        )
        return response
