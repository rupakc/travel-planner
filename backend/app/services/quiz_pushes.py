"""Daily-quiz reminder push (category ``quiz``, kind ``quiz_daily``).

``run_due(now)`` runs from the alert loop next to ``trip_pushes`` (flag
``notifications_v2_enabled``). Only users who played a quiz in the last
``ACTIVE_DAYS`` days, have a registered device, a known timezone, the game and
Play switched on and today's daily quiz still open are considered; the push is
enqueued once per user per local day, between ``START_HOUR`` and ``END_HOUR``
local time. Quiet hours, caps and the ``quiz`` category switch are applied by
``notify_center``. No AI, no game wording beyond the generic catalog text."""

import logging
from datetime import UTC, datetime, timedelta

from ..core.config import settings
from ..db import game_db, user_settings_db
from ..db.database import get_connection
from . import alert_delivery, social_notify

logger = logging.getLogger(__name__)

MAX_USERS = 1000
ACTIVE_DAYS = 30
START_HOUR = 12
END_HOUR = 20


_cursor = ""  # keyset cursor (users.id) of the last page, in memory


def _page(since_ms: int, after: str) -> list[dict]:
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT u.id AS user_id FROM users u WHERE u.is_active = 1 AND u.id > ?"
            " AND EXISTS (SELECT 1 FROM devices d WHERE d.username = u.username)"
            " AND EXISTS (SELECT 1 FROM quiz_sessions q WHERE q.user_id = u.id"
            " AND q.created_ms >= ?) ORDER BY u.id LIMIT ?",
            (after, since_ms, MAX_USERS),
        ).fetchall()
    return [dict(r) for r in rows]


def _candidates(now: datetime) -> list[dict]:
    """The next page of up to ``MAX_USERS`` active players after the cursor,
    wrapping to the start past the last one, so every player is eventually
    considered however many there are (a restart just begins again)."""
    global _cursor
    since_ms = int((now - timedelta(days=ACTIVE_DAYS)).timestamp() * 1000)
    rows = _page(since_ms, _cursor)
    if len(rows) < MAX_USERS:  # reached the end: next pass starts over
        if _cursor and not rows:
            rows = _page(since_ms, "")
            _cursor = rows[-1]["user_id"] if len(rows) == MAX_USERS else ""
        else:
            _cursor = ""
    else:
        _cursor = rows[-1]["user_id"]
    return rows


def _daily_done(user_id: str, utc_day: str) -> bool:
    with get_connection() as conn:
        return bool(
            conn.execute(
                "SELECT 1 FROM quiz_sessions WHERE user_id = ? AND mode = 'daily'"
                " AND day = ? AND finished_ms IS NOT NULL LIMIT 1",
                (user_id, utc_day),
            ).fetchone()
        )


def _one(user_id: str, now: datetime) -> int:
    tz = user_settings_db.get_settings(user_id).get("timezone")
    zone = alert_delivery._zone(tz)
    if zone is None:
        return 0
    local = now.astimezone(zone)
    if not START_HOUR <= local.hour < END_HOUR:
        return 0
    if game_db.hide_game(user_id) or _daily_done(user_id, now.date().isoformat()):
        return 0
    social_notify.quiz_daily(user_id, local.date().isoformat(), now)
    return 1


def run_due(now: datetime) -> int:
    """Consider every candidate; returns how many were handed to the sender
    (the dedupe key and notify_center may still drop them). One failing user
    never stops the pass."""
    if not (settings.play_enabled and settings.game_enabled):
        return 0
    now = now.astimezone(UTC)
    total = 0
    for c in _candidates(now):
        try:
            total += _one(c["user_id"], now)
        except Exception:  # noqa: BLE001
            logger.warning("quiz push failed", exc_info=True)
    return total
