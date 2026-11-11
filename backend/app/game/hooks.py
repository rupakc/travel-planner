"""Game hooks called by the account flows. A game failure never breaks auth."""

import logging

from ..core.config import settings

logger = logging.getLogger(__name__)


def _award(user_id: str, rule: str) -> dict | None:
    if not settings.game_enabled:
        return None
    try:
        from . import engine

        return engine.award(user_id, rule, f"{rule}:{user_id}")
    except Exception:
        logger.exception("game award failed (rule=%s)", rule)
        return _empty(user_id)  # None would read as "game disabled"


def _empty(user_id: str) -> dict:
    try:
        from ..db import game_db
        from ..db.database import get_connection

        with get_connection() as conn:
            xp = game_db.total_xp(conn, user_id)
    except Exception:
        xp = 0
    return {"xp": xp, "awards": [], "badges": [], "level_up": None}


def on_email_verified(user_id: str) -> dict | None:
    return _award(user_id, "email_verified")


def on_onboarding_complete(user_id: str) -> dict | None:
    return _award(user_id, "onboarding_complete")
