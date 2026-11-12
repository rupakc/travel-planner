"""The flag-gated seam in each watch service's ``_notify`` (Phase 3).

Bodies are filled by later tasks; with the flag off nothing here runs."""

from datetime import datetime

from ..core.config import settings


def enabled() -> bool:
    return bool(settings.price_alerts_v2_enabled)


def enrich(watch: dict, watch_kind: str, note: dict) -> dict:
    """Return the note, with drop facts added to ``data`` (stub: unchanged)."""
    return note


def after_insert(watch: dict, watch_kind: str, row: dict, now: datetime) -> bool:
    """Record savings/XP and hand push and email to the delivery layer.
    ``True`` means v2 took over push and email (stub: ``False``)."""
    return False
