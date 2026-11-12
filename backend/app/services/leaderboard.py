"""Weekly leaderboards. Score = the points of a user's finished quiz sessions
(daily, packs, head-to-head and the challenge) in an ISO week, Monday 00:00
UTC. Global shows opted-in users only; friends are the people the caller
follows (approved) who opted in, plus the caller. Handles only; hidden-game
users, private profiles and blocked pairs never appear. Pure SQL, no AI."""

from datetime import UTC, date, datetime, timedelta

from ..db import social_db
from ..db.database import get_connection
from ..game import engine as game_engine
from . import challenge

GLOBAL_LIMIT = 50

_HIDDEN = (
    "NOT EXISTS (SELECT 1 FROM user_settings us WHERE us.user_id = p.user_id"
    " AND json_valid(us.data) AND json_extract(us.data, '$.hide_game') IN (1, 'true'))"
)
_NOT_BLOCKED = (
    "NOT EXISTS (SELECT 1 FROM social_blocks b WHERE"
    " (b.blocker_id = :uid AND b.blocked_id = p.user_id)"
    " OR (b.blocker_id = p.user_id AND b.blocked_id = :uid))"
)


def week_day(week: str, now_ms: int) -> date:
    today = datetime.fromtimestamp(now_ms / 1000, UTC).date()
    return today - timedelta(days=7) if week == "previous" else today


def _scores(conn, user_id: str, scope: str, start: int, end: int) -> list[dict]:
    """Rows (user_id, handle, score, show_level) with score > 0, best first."""
    sums = (
        "SELECT user_id, SUM(score) AS score FROM quiz_sessions"
        " WHERE finished_ms >= :start AND finished_ms < :end GROUP BY user_id"
    )
    base = (
        "SELECT p.user_id, p.handle, p.show_level, q.score FROM social_profiles p"
        f" JOIN ({sums}) q ON q.user_id = p.user_id"  # nosec B608
        f" WHERE q.score > 0 AND {_HIDDEN} AND {_NOT_BLOCKED}"  # nosec B608
    )
    if scope == "friends":
        where = (
            " AND (p.user_id = :uid OR (p.leaderboard_opt_in = 1"
            " AND p.visibility != 'private' AND EXISTS (SELECT 1 FROM social_follows f"
            " WHERE f.follower_id = :uid AND f.followee_id = p.user_id"
            " AND f.state = 'following')))"
        )
    else:
        where = " AND p.leaderboard_opt_in = 1 AND p.visibility != 'private'"
    rows = conn.execute(
        base + where + " ORDER BY q.score DESC, p.handle_lower",
        {"uid": user_id, "start": start, "end": end},
    ).fetchall()
    return [dict(r) for r in rows]


def _my_score(conn, user_id: str, start: int, end: int) -> int:
    return conn.execute(
        "SELECT COALESCE(SUM(score), 0) FROM quiz_sessions WHERE user_id = ?"
        " AND finished_ms >= ? AND finished_ms < ?",
        (user_id, start, end),
    ).fetchone()[0]


def _level(user_id: str) -> int:
    from ..db import game_db

    with get_connection() as conn:
        xp = game_db.total_xp(conn, user_id)
    return game_engine.level_for(xp, game_engine.get_rules())


def board(user_id: str, scope: str, week: str, now_ms: int) -> dict:
    day = week_day(week, now_ms)
    start, end = challenge.week_bounds_ms(day)
    with get_connection() as conn:
        rows = _scores(conn, user_id, scope, start, end)
        mine = social_db.get_profile(user_id)
        my_score = _my_score(conn, user_id, start, end) if mine else 0
    out, you = [], None
    for r in rows:
        rank = 1 + sum(1 for o in rows if o["score"] > r["score"])
        if r["user_id"] == user_id:
            you = {
                "rank": rank,
                "score": r["score"],
                "opted_in": bool(mine["leaderboard_opt_in"]),
            }
        if len(out) < GLOBAL_LIMIT:
            row = {
                "rank": rank,
                "handle": r["handle"],
                "score": r["score"],
                "you": r["user_id"] == user_id,
            }
            if r["show_level"]:
                row["level"] = _level(r["user_id"])
            out.append(row)
    if mine and you is None:
        # not on the board: no points this week, or not opted in (global)
        you = {
            "rank": None,
            "score": my_score,
            "opted_in": bool(mine["leaderboard_opt_in"]),
        }
    return {"week": challenge.iso_week(day), "rows": out, "you": you}
