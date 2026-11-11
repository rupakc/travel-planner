"""Per-user (or per-IP when anonymous) daily AI quota, counted in ai_usage_daily.

Days are UTC. The increment is one atomic upsert, so concurrent requests
cannot overshoot the limit. Admins, a limit of 0 and
AI_DAILY_QUOTA_ENABLED=false all skip the check.
"""

import asyncio
from collections.abc import Callable
from datetime import UTC, datetime, time, timedelta

from fastapi import Depends, Request

from ..db.database import get_connection
from .auth import get_optional_user
from .config import settings
from .errors import ApiError

BUCKETS = ("search", "chat", "compare", "discover", "light_ai", "import")

LABELS = {
    "search": "searches",
    "chat": "chat",
    "compare": "comparisons",
    "discover": "Surprise me",
    "light_ai": "quick AI tools",
    "import": "link imports",
}


def _now() -> datetime:
    return datetime.now(UTC)


def _limit(bucket: str) -> int:
    return int(getattr(settings, f"ai_daily_quota_{bucket}"))


def _unlimited(user: dict | None) -> bool:
    return not settings.ai_daily_quota_enabled or bool(user and user.get("is_admin"))


def _next_midnight(now: datetime) -> datetime:
    now = now.astimezone(UTC)
    return datetime.combine(now.date() + timedelta(days=1), time.min, tzinfo=UTC)


def _iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def user_key(user: dict | None, request: Request | None) -> str:
    if user and user.get("id"):
        return f"user:{user['id']}"
    host = request.client.host if request is not None and request.client else "unknown"
    return f"ip:{host}"


def consume_key(
    bucket: str, key: str, user: dict | None, now: datetime | None = None
) -> None:
    """Take one ``bucket`` unit for ``key`` or raise the 429 ``ai_daily_quota``."""
    limit = _limit(bucket)
    if limit <= 0 or _unlimited(user):
        return
    now = (now or _now()).astimezone(UTC)
    day = now.date().isoformat()
    with get_connection() as conn:
        conn.execute(
            "INSERT INTO ai_usage_daily(day, user_key, bucket, used) VALUES(?,?,?,1) "
            "ON CONFLICT(day, user_key, bucket) DO UPDATE SET used = used + 1 "
            "WHERE used < ?",
            (day, key, bucket, limit),
        )
        took = conn.execute("SELECT changes()").fetchone()[0] > 0
    if took:
        return
    reset = _next_midnight(now)
    wait = max(1, int((reset - now).total_seconds()))
    raise ApiError(
        429,
        "ai_daily_quota",
        f"You've used today's AI allowance for {LABELS[bucket]}. "
        "It resets at midnight UTC.",
        headers={"Retry-After": str(wait)},
        bucket=bucket,
        resets_at=_iso(reset),
    )


def consume(
    bucket: str, user: dict | None, request: Request, now: datetime | None = None
) -> None:
    consume_key(bucket, user_key(user, request), user, now)


def usage(user: dict, now: datetime | None = None) -> dict:
    now = (now or _now()).astimezone(UTC)
    day = now.date().isoformat()
    key = user_key(user, None)
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT bucket, used FROM ai_usage_daily WHERE day = ? AND user_key = ?",
            (day, key),
        ).fetchall()
    used = {r["bucket"]: r["used"] for r in rows}
    unlimited = _unlimited(user)
    buckets = {}
    for b in BUCKETS:
        limit = _limit(b)
        buckets[b] = {
            "used": used.get(b, 0),
            "limit": None if unlimited or limit <= 0 else limit,
        }
    return {"day": day, "resets_at": _iso(_next_midnight(now)), "buckets": buckets}


def daily_quota(bucket: str) -> Callable:
    _limit(bucket)  # fail fast on an unknown bucket

    async def _dependency(
        request: Request, user: dict | None = Depends(get_optional_user)
    ) -> None:
        await asyncio.to_thread(consume, bucket, user, request)

    return _dependency
