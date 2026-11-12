"""The flag-gated seam in each watch service's ``_notify`` (Phase 3).

Bodies are filled by later tasks; with the flag off nothing here runs."""

import json
import logging
from datetime import datetime

from ..core.config import settings
from ..db.database import get_connection
from ..game import alert_hooks
from ..game.trip_hooks import merge_deltas
from . import alert_delivery, alert_moments

logger = logging.getLogger(__name__)


def enabled() -> bool:
    return bool(settings.price_alerts_v2_enabled)


def enrich(watch: dict, watch_kind: str, note: dict) -> dict:
    """Return the note with ``data.drop`` added for an observed drop or target
    hit; every other note (expired, error, estimates) is unchanged."""
    base = {"category": "price_drops", "plan_id": None, **note["data"]}
    note = {**note, "data": base}
    facts = alert_moments.drop_facts(watch_kind, watch, note)
    if not facts:
        return note
    return {**note, "data": {**base, "drop": facts}}


def _update_data(note_id: int, data: dict) -> None:
    with get_connection() as conn:
        conn.execute(
            "UPDATE notifications SET data = ? WHERE id = ?",
            (json.dumps(data), note_id),
        )


def _drop_game(watch_kind: str, watch: dict, row: dict) -> dict | None:
    """Record the savings row and award Deal-hunter XP for a drop row."""
    drop = row["data"].get("drop")
    if not drop:
        return None
    alert_moments.record(watch_kind, watch, row)
    user_id = row["user_id"]
    delta = alert_hooks.on_drop(user_id, watch_kind, watch["id"], row["id"], drop)
    try:
        total = alert_moments.summary(user_id)["total_usd"]
    except Exception:  # the tally must never lose the drop's own award
        logger.warning("savings summary failed", exc_info=True)
        total = 0
    return merge_deltas(delta, alert_hooks.on_savings(user_id, total))


def after_insert(watch: dict, watch_kind: str, row: dict, now: datetime) -> bool:
    """Record savings/XP and hand push and email to the delivery layer.
    ``True`` means v2 took over push and email AND has persisted ``_v2`` in
    the stored notification's ``data`` itself; ``_notify`` relies only on the
    returned bool. Raising is safe: ``_notify`` falls back to legacy push and
    email (``_v2`` is only written once delivery has accepted the item)."""
    data = row["data"]
    if data.get("drop"):
        data["game"] = _drop_game(watch_kind, watch, row)
        _update_data(row["id"], data)
    alert_delivery.dispatch(watch, watch_kind, row, now)
    data["_v2"] = True
    _update_data(row["id"], data)
    return True
