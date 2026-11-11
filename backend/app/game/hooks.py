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
        return None


def on_email_verified(user_id: str) -> dict | None:
    return _award(user_id, "email_verified")


def on_onboarding_complete(user_id: str) -> dict | None:
    return _award(user_id, "onboarding_complete")
