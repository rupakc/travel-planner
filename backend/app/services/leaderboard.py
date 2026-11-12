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
PACK_WEEKLY_CAP = 20  # finished pack sessions per user per week that score

_HIDDEN = (
    "NOT EXISTS (SELECT 1 FROM user_settings us WHERE us.user_id = p.user_id"
    " AND json_valid(us.data) AND json_extract(us.data, '$.hide_game') IN (1, 'true'))"
)
_VERIFIED = (
    "EXISTS (SELECT 1 FROM users u WHERE u.id = p.user_id"
    " AND (u.signup_method = 'admin' OR u.verified_at IS NOT NULL))"
)
_NOT_BLOCKED = (
    "NOT EXISTS (SELECT 1 FROM social_blocks b WHERE"
    " (b.blocker_id = :uid AND b.blocked_id = p.user_id)"
    " OR (b.blocker_id = p.user_id AND b.blocked_id = :uid))"
)


def week_day(week: str, now_ms: int) -> date:
    today = datetime.fromtimestamp(now_ms / 1000, UTC).date()
    return today - timedelta(days=7) if week == "previous" else today


def _sums(extra: str, cap: str) -> str:
    """Per-user weekly totals: every finished session in the week range (uses
    the finished_ms index), but only the first ``cap`` pack sessions count."""
    return (
        "SELECT user_id, SUM(score) AS score FROM ("  # nosec B608
        "SELECT user_id, mode, score, ROW_NUMBER() OVER (PARTITION BY user_id,"
        " mode = 'pack' ORDER BY finished_ms, id) AS rn FROM quiz_sessions"
        f" WHERE finished_ms >= :start AND finished_ms < :end{extra})"
        f" WHERE mode != 'pack' OR rn <= {cap} GROUP BY user_id"
    )


def _scores(conn, user_id: str, scope: str, start: int, end: int) -> list[dict]:
    """Rows (user_id, handle, score, show_level) with score > 0, best first."""
    sums = _sums("", f"{PACK_WEEKLY_CAP}")
    base = (
        "SELECT p.user_id, p.handle, p.show_level, q.score FROM social_profiles p"
        f" JOIN ({sums}) q ON q.user_id = p.user_id"  # nosec B608
        f" WHERE q.score > 0 AND {_VERIFIED} AND {_HIDDEN} AND {_NOT_BLOCKED}"  # nosec B608
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
    row = conn.execute(
        _sums(" AND user_id = :uid", f"{PACK_WEEKLY_CAP}"),
        {"uid": user_id, "start": start, "end": end},
    ).fetchone()
    return int(row["score"]) if row else 0


def _levels(conn, user_ids: list[str]) -> dict[str, int]:
    """One query for every shown user's level."""
    if not user_ids:
        return {}
    marks = ",".join("?" * len(user_ids))
    xp = {
        r[0]: int(r[1])
        for r in conn.execute(
            "SELECT user_id, SUM(points) FROM xp_ledger"  # nosec B608
            f" WHERE user_id IN ({marks}) GROUP BY user_id",
            user_ids,
        )
    }
    rules = game_engine.get_rules()
    return {u: game_engine.level_for(xp.get(u, 0), rules) for u in user_ids}


def board(user_id: str, scope: str, week: str, now_ms: int) -> dict:
    day = week_day(week, now_ms)
    start, end = challenge.week_bounds_ms(day)
    with get_connection() as conn:
        rows = _scores(conn, user_id, scope, start, end)  # already sorted by score
        mine = social_db.get_profile(user_id)
        my_score = _my_score(conn, user_id, start, end) if mine else 0
        # rank = 1 + number of strictly higher scores: one pass over sorted rows
        ranked, prev, rank = [], None, 0
        for i, r in enumerate(rows, 1):
            if r["score"] != prev:
                prev, rank = r["score"], i
            ranked.append((rank, r))
        top = ranked[:GLOBAL_LIMIT]
        levels = _levels(conn, [r["user_id"] for _, r in top if r["show_level"]])
    out, you = [], None
    for rank, r in ranked:
        if r["user_id"] == user_id:
            you = {
                "rank": rank,
                "score": r["score"],
                "opted_in": bool(mine["leaderboard_opt_in"]),
            }
            break
    for rank, r in top:
        row = {
            "rank": rank,
            "handle": r["handle"],
            "score": r["score"],
            "you": r["user_id"] == user_id,
        }
        if r["show_level"]:
            row["level"] = levels[r["user_id"]]
        out.append(row)
    if mine and you is None:
        # not on the board: no points this week, not opted in (global) or unverified
        you = {
            "rank": None,
            "score": my_score,
            "opted_in": bool(mine["leaderboard_opt_in"]),
        }
    return {"week": challenge.iso_week(day), "rows": out, "you": you}
