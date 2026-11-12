"""Quiet hours, caps, grouping and the outbox loop for push and email.
Filled by Task 6."""

import asyncio
from datetime import datetime
from typing import Any

Decision = Any  # the real dataclass arrives with Task 6


def plan(
    note_row: dict,
    watch_kind: str,
    prefs: dict,
    tz: str | None,
    counts: dict,
    last_push_at: datetime | None,
    now: datetime,
) -> Decision:
    raise NotImplementedError


def dispatch(watch: dict, watch_kind: str, row: dict, now: datetime) -> None:
    raise NotImplementedError


def flush(now: datetime) -> int:
    return 0


def start_loop() -> asyncio.Task | None:
    """The outbox flush loop; ``None`` while the v2 flag is off."""
    from ..core.config import settings

    if not settings.price_alerts_v2_enabled:
        return None
    return None  # Task 6 starts the real loop


async def stop_loop(task: asyncio.Task | None) -> None:
    if task is None:
        return
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
