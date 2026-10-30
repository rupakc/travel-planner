"""Per-user (or per-client-IP) rate limits for the AI endpoints.

In-process sliding window: each key keeps the timestamps of its accepted
requests inside the window. Single-process only — fine for one uvicorn
worker; a multi-instance deployment would need a shared store.
"""

import math
import threading
import time
from collections import deque
from collections.abc import Callable

from fastapi import Depends, HTTPException, Request

from .auth import get_optional_user
from .config import settings


class SlidingWindowLimiter:
    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._hits: dict[str, deque[float]] = {}
        self._lock = threading.Lock()
        self._last_sweep = clock()

    def hit(self, key: str, limit: int, window: float) -> int | None:
        """Record a request. Returns None if allowed, else seconds to wait."""
        with self._lock:
            now = self._clock()
            if now - self._last_sweep >= window:  # drop idle keys once a window
                self._prune_locked(now, window)
            hits = self._hits.setdefault(key, deque())
            while hits and hits[0] <= now - window:
                hits.popleft()
            if len(hits) >= limit:
                if limit <= 0:
                    return max(1, math.ceil(window))
                # A slot frees when the hit `limit` places from the end expires.
                freed_at = hits[len(hits) - limit] + window
                return max(1, math.ceil(freed_at - now))
            hits.append(now)
            return None

    def prune(self, window: float) -> None:
        """Drop keys with no request inside the window."""
        with self._lock:
            self._prune_locked(self._clock(), window)

    def _prune_locked(self, now: float, window: float) -> None:
        self._last_sweep = now
        for key in [k for k, h in self._hits.items() if not h or h[-1] <= now - window]:
            del self._hits[key]


limiter = SlidingWindowLimiter()


def _bucket_limit(bucket: str) -> int:
    return getattr(settings, f"rate_limit_{bucket}")


def caller_key(request: Request, user: dict | None) -> str:
    """Whose budget a request draws on: the signed-in user, else the client IP."""
    if user and user.get("username"):
        return f"user:{user['username']}"
    host = request.client.host if request.client else "unknown"
    return f"ip:{host}"


def try_consume(bucket: str, key: str) -> int | None:
    """Take one ``bucket`` token for caller ``key`` (see caller_key).

    Returns None when allowed (or limiting is disabled), else the seconds
    until a token frees up.
    """
    if not settings.rate_limit_enabled:
        return None
    return limiter.hit(
        f"{bucket}:{key}", _bucket_limit(bucket), settings.rate_limit_window_seconds
    )


def rate_limit(bucket: str) -> Callable:
    """FastAPI dependency enforcing the ``rate_limit_<bucket>`` setting."""
    _bucket_limit(bucket)  # fail fast on a bucket with no setting

    async def enforce(
        request: Request, user: dict | None = Depends(get_optional_user)
    ) -> None:
        wait = try_consume(bucket, caller_key(request, user))
        if wait is not None:
            raise HTTPException(
                status_code=429,
                detail=f"Too many requests — please wait {wait} seconds and try again.",
                headers={"Retry-After": str(wait)},
            )

    return enforce
