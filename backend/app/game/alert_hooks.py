"""Deal-hunter game hooks for price alerts. Server-observed alerts only.

Every hook catches its own errors and returns an empty delta (never ``None``
for a failure, which reads as "game disabled"), so a game failure never
breaks an alert. ``hide_game`` only hides the UI: awards and savings are
still recorded.
"""

from . import hooks
from .trip_hooks import _award, _guard, merge_deltas

SAVED_RULES = (
    (50, "deal_saved_50"),
    (200, "deal_saved_200"),
    (1000, "deal_saved_1000"),
)


def on_drop(
    user_id: str,
    watch_kind: str,
    watch_id: int,
    notification_id: int,
    facts: dict,
) -> dict | None:
    """XP for an observed drop (and a target hit); ``None`` when the game is off."""

    def run() -> dict | None:
        if not facts or not facts.get("observed"):
            return hooks._empty(user_id)
        meta = {"watch_kind": watch_kind, "watch_id": watch_id}
        key = f"{watch_kind}:{notification_id}"
        deltas = [_award(user_id, "deal_drop", f"deal_drop:{key}", meta)]
        if facts.get("target_hit"):
            deltas.append(_award(user_id, "deal_target", f"deal_target:{key}", meta))
        return merge_deltas(*deltas)

    return _guard(user_id, "deal_drop", run)


def on_savings(user_id: str, total_usd: float) -> dict | None:
    """One-time XP for each USD milestone the tally has reached (a jump from
    $40 to $230 awards both the $50 and the $200 one)."""

    def run() -> dict | None:
        deltas = [
            _award(user_id, rule, f"{rule}:{user_id}", {"total_usd": total_usd})
            for threshold, rule in SAVED_RULES
            if total_usd >= threshold
        ]
        return merge_deltas(*deltas) or hooks._empty(user_id)

    return _guard(user_id, "deal_saved", run)
