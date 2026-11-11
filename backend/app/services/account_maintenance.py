"""Hourly account maintenance: purge expired tokens and stale pending accounts."""

import asyncio
import logging
from collections.abc import Callable
from datetime import UTC, datetime

logger = logging.getLogger(__name__)

INTERVAL_SECONDS = 3600


def _default_purge(now: datetime) -> dict[str, int]:
    from ..db.accounts_schema import purge_expired

    return purge_expired(now)


async def account_maintenance(
    purge: Callable[[datetime], dict[str, int]] | None = None,
    interval: float = INTERVAL_SECONDS,
) -> None:
    """Run purge_expired every `interval` seconds; errors are logged, never raised."""
    while True:
        try:
            counts = await asyncio.to_thread(purge or _default_purge, datetime.now(UTC))
            if any(counts.values()):
                logger.info("account maintenance purged %s", counts)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("account maintenance failed")
        await asyncio.sleep(interval)
