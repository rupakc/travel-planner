"""Senders for the ``social`` and ``quiz`` notification categories (Phase 5).

Fire-and-forget: every public function swallows and logs its own errors, so a
broken notification never fails or slows the request that caused it (the push
itself is sent later by ``notify_center.flush_due``). Text is generic on
purpose: no handles, names or ids, only the shared catalog. The ``quiz`` kinds
are never sent to a user who hides the game."""

import logging
from datetime import UTC, datetime

from ..core.config import settings
from ..db import game_db, social_db, user_settings_db
from . import notify_center, notify_text

logger = logging.getLogger(__name__)

IDEA_SAVED = "social_idea_saved"
NEW_FOLLOWER = "social_new_follower"
IDEA_LIKED = "social_idea_liked"
IDEA_COMMENT = "social_idea_comment"
QUIZ_DAILY = "quiz_daily"
H2H_INVITE = "quiz_h2h_invite"
H2H_RESULT = "quiz_h2h_result"


def _enqueue(
    user_id: str, kind: str, category: str, key: str, link: str, now: datetime | None
) -> None:
    try:
        if category == "quiz" and (
            game_db.hide_game(user_id)
            or not settings.play_enabled
            or not settings.game_enabled
        ):
            return
        if category == "social" and user_settings_db.get_settings(user_id).get(
            "hide_community"
        ):
            return
        body = notify_text.render(kind, notify_center.user_locale(user_id))
        notify_center.enqueue_category(
            user_id,
            None,
            kind,
            category,
            key,
            "Voyager",
            body,
            {"link": link},
            now or datetime.now(UTC),
        )
    except Exception:  # noqa: BLE001
        logger.warning("social notification failed (kind=%s)", kind, exc_info=True)


def idea_saved(author_id: str, saver_id: str, idea_id: int) -> None:
    if author_id != saver_id:
        _enqueue(
            author_id,
            IDEA_SAVED,
            "social",
            f"{IDEA_SAVED}:{author_id}:{saver_id}:{idea_id}",
            "/feed",
            None,
        )


def new_follower(followee_id: str, follower_id: str) -> None:
    if followee_id != follower_id:
        _enqueue(
            followee_id,
            NEW_FOLLOWER,
            "social",
            f"{NEW_FOLLOWER}:{followee_id}:{follower_id}",
            "/feed",
            None,
        )


def _engagement(
    kind: str, author_id: str, actor_id: str, idea_id: int, now: datetime | None
) -> None:
    """Like / comment push: never for one's own action or across a block, and
    batched to at most one per idea per UTC day (so a popular idea cannot
    spam its author; the user's daily cap applies on top)."""
    try:
        if author_id == actor_id or social_db.is_blocked_either_way(
            author_id, actor_id
        ):
            return
    except Exception:  # noqa: BLE001
        logger.warning("social notification failed (kind=%s)", kind, exc_info=True)
        return
    now = now or datetime.now(UTC)
    _enqueue(
        author_id,
        kind,
        "social",
        f"{kind}:{author_id}:{idea_id}:{now.date().isoformat()}",
        "/feed",
        now,
    )


def idea_liked(
    author_id: str, liker_id: str, idea_id: int, now: datetime | None = None
) -> None:
    _engagement(IDEA_LIKED, author_id, liker_id, idea_id, now)


def idea_commented(
    author_id: str, commenter_id: str, idea_id: int, now: datetime | None = None
) -> None:
    """Call only for a published comment (held ones are not announced)."""
    _engagement(IDEA_COMMENT, author_id, commenter_id, idea_id, now)


def quiz_daily(user_id: str, day: str, now: datetime | None = None) -> None:
    """Daily-quiz reminder; ``day`` is the user's local date (ISO), so it goes
    out at most once per user per local day."""
    _enqueue(user_id, QUIZ_DAILY, "quiz", f"{QUIZ_DAILY}:{user_id}:{day}", "/play", now)


def h2h_invite(opponent_id: str, match_id: str) -> None:
    _enqueue(
        opponent_id,
        H2H_INVITE,
        "quiz",
        f"{H2H_INVITE}:{opponent_id}:{match_id}",
        f"/play/h2h/{match_id}",
        None,
    )


def h2h_result(user_id: str, match_id: str, now: datetime | None = None) -> None:
    """For the side that finished first and is now waiting."""
    _enqueue(
        user_id,
        H2H_RESULT,
        "quiz",
        f"{H2H_RESULT}:{user_id}:{match_id}",
        f"/play/h2h/{match_id}",
        now,
    )
