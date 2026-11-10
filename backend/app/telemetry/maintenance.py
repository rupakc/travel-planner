"""Hourly telemetry maintenance: daily rollups and raw-event pruning."""

import asyncio
import logging
from datetime import UTC, datetime, timedelta

from ..core.config import settings
from ..db import telemetry_db
from ..db.database import get_connection
from .registry import MAX_SKEW_DAYS

logger = logging.getLogger(__name__)

INTERVAL_SECONDS = 3600
_FIRST_RUN_DAYS = 7  # with no rollup yet, start this far back
_MAX_CATCHUP_DAYS = 120


def _last_rollup_day() -> str | None:
    with get_connection() as conn:
        row = conn.execute("SELECT MAX(day) FROM telemetry_rollups").fetchone()
    return row[0] if row and row[0] else None


def maintain_once(now: datetime | None = None) -> None:
    """Roll up every UTC day after the last rollup up to yesterday, then prune
    raw events past retention. Errors are logged, never raised."""
    try:
        now = now or datetime.now(UTC)
        yesterday = now.date() - timedelta(days=1)
        last = _last_rollup_day()
        if last:
            start = datetime.fromisoformat(last).date() + timedelta(days=1)
        else:
            start = yesterday - timedelta(days=_FIRST_RUN_DAYS - 1)
        # Clients may send events up to MAX_SKEW_DAYS old (offline mobile), so
        # re-roll that trailing window too (rollup_day is idempotent).
        start = min(start, yesterday - timedelta(days=MAX_SKEW_DAYS - 1))
        start = max(start, yesterday - timedelta(days=_MAX_CATCHUP_DAYS))
        day = start
        while day <= yesterday:
            telemetry_db.rollup_day(day.isoformat())
            day += timedelta(days=1)
        cutoff = now - timedelta(days=settings.telemetry_retention_days)
        telemetry_db.prune(int(cutoff.timestamp() * 1000))
    except Exception:
        logger.exception("telemetry maintenance failed")


async def telemetry_maintenance() -> None:
    """Lifespan task: ``maintain_once`` every hour (cancelled on shutdown)."""
    while True:
        try:
            await asyncio.to_thread(maintain_once)
        except Exception:  # pragma: no cover - maintain_once already guards
            logger.exception("telemetry maintenance failed")
        await asyncio.sleep(INTERVAL_SECONDS)
