"""SQLite persistence for Phase 5 social profiles, follows and blocks.

Rows are keyed by user id, never by handle, so a handle change touches one
row. Additive only (``CREATE TABLE IF NOT EXISTS``).
"""

import sqlite3
from datetime import UTC, datetime, timedelta

from .database import get_connection


def now_iso() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def create_social_tables() -> None:
    with get_connection() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS social_profiles (
                user_id             TEXT PRIMARY KEY,
                handle              TEXT NOT NULL,
                handle_lower        TEXT NOT NULL UNIQUE,
                visibility          TEXT NOT NULL DEFAULT 'private',
                bio                 TEXT NOT NULL DEFAULT '',
                show_avatar         INTEGER NOT NULL DEFAULT 0,
                show_home_country   INTEGER NOT NULL DEFAULT 0,
                show_countries      INTEGER NOT NULL DEFAULT 0,
                show_level          INTEGER NOT NULL DEFAULT 0,
                show_badges         INTEGER NOT NULL DEFAULT 0,
                leaderboard_opt_in  INTEGER NOT NULL DEFAULT 0,
                home_country        TEXT,
                handle_changed_at   TEXT,
                created_at          TEXT NOT NULL,
                updated_at          TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS social_follows (
                follower_id  TEXT NOT NULL,
                followee_id  TEXT NOT NULL,
                state        TEXT NOT NULL,
                created_at   TEXT NOT NULL,
                PRIMARY KEY (follower_id, followee_id)
            );
            CREATE INDEX IF NOT EXISTS idx_social_follows_followee
                ON social_follows (followee_id, state);
            CREATE TABLE IF NOT EXISTS social_blocks (
                blocker_id  TEXT NOT NULL,
                blocked_id  TEXT NOT NULL,
                created_at  TEXT NOT NULL,
                PRIMARY KEY (blocker_id, blocked_id)
            );
            CREATE INDEX IF NOT EXISTS idx_social_blocks_blocked
                ON social_blocks (blocked_id);
            CREATE TABLE IF NOT EXISTS social_limits (
                user_id  TEXT NOT NULL,
                day      TEXT NOT NULL,
                kind     TEXT NOT NULL,
                n        INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (user_id, day, kind)
            );
        """)


_FLAGS = (
    "show_avatar",
    "show_home_country",
    "show_countries",
    "show_level",
    "show_badges",
    "leaderboard_opt_in",
)


def _profile(row: sqlite3.Row | None) -> dict | None:
    if not row:
        return None
    d = dict(row)
    for k in _FLAGS:
        d[k] = bool(d[k])
    return d


def get_profile(user_id: str) -> dict | None:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM social_profiles WHERE user_id = ?", (user_id,)
        ).fetchone()
    return _profile(row)


def get_profile_by_handle(handle: str) -> dict | None:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM social_profiles WHERE handle_lower = ?",
            ((handle or "").lower(),),
        ).fetchone()
    return _profile(row)


def handle_owner(handle: str) -> str | None:
    p = get_profile_by_handle(handle)
    return p["user_id"] if p else None


def save_profile(user_id: str, fields: dict) -> dict:
    """Create or update the caller's profile from ``fields`` (already
    validated). ``handle`` (when present) also sets ``handle_lower``.
    Raises ``sqlite3.IntegrityError`` when the handle is taken."""
    fields = dict(fields)
    if "handle" in fields:
        fields["handle_lower"] = fields["handle"].lower()
    for k in _FLAGS:
        if k in fields:
            fields[k] = int(bool(fields[k]))
    ts = now_iso()
    with get_connection() as conn:
        cur = conn.execute(
            "SELECT 1 FROM social_profiles WHERE user_id = ?", (user_id,)
        ).fetchone()
        if cur:
            fields["updated_at"] = ts
            sets = ", ".join(f"{k} = ?" for k in fields)
            conn.execute(
                f"UPDATE social_profiles SET {sets} WHERE user_id = ?",  # nosec B608
                (*fields.values(), user_id),
            )
        else:
            fields.update(user_id=user_id, created_at=ts, updated_at=ts)
            cols = ", ".join(fields)
            marks = ", ".join("?" * len(fields))
            conn.execute(
                f"INSERT INTO social_profiles ({cols}) VALUES ({marks})",  # nosec B608
                tuple(fields.values()),
            )
    return get_profile(user_id)


# ── blocks ────────────────────────────────────────────────────────────────────


def is_blocked_either_way(a: str, b: str) -> bool:
    with get_connection() as conn:
        return (
            conn.execute(
                "SELECT 1 FROM social_blocks WHERE (blocker_id = ? AND blocked_id = ?)"
                " OR (blocker_id = ? AND blocked_id = ?)",
                (a, b, b, a),
            ).fetchone()
            is not None
        )


def has_blocked(blocker: str, blocked: str) -> bool:
    with get_connection() as conn:
        return (
            conn.execute(
                "SELECT 1 FROM social_blocks WHERE blocker_id = ? AND blocked_id = ?",
                (blocker, blocked),
            ).fetchone()
            is not None
        )


def block(blocker: str, blocked: str) -> None:
    """Block and drop every follow or request between the pair, both ways."""
    with get_connection() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO social_blocks (blocker_id, blocked_id, created_at)"
            " VALUES (?,?,?)",
            (blocker, blocked, now_iso()),
        )
        conn.execute(
            "DELETE FROM social_follows WHERE (follower_id = ? AND followee_id = ?)"
            " OR (follower_id = ? AND followee_id = ?)",
            (blocker, blocked, blocked, blocker),
        )


def unblock(blocker: str, blocked: str) -> None:
    with get_connection() as conn:
        conn.execute(
            "DELETE FROM social_blocks WHERE blocker_id = ? AND blocked_id = ?",
            (blocker, blocked),
        )


def list_blocks(blocker: str) -> list[str]:
    """Handles the caller blocked, newest first."""
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT p.handle FROM social_blocks b JOIN social_profiles p"
            " ON p.user_id = b.blocked_id WHERE b.blocker_id = ?"
            " ORDER BY b.created_at DESC, b.rowid DESC",
            (blocker,),
        ).fetchall()
    return [r["handle"] for r in rows]


# ── follows ───────────────────────────────────────────────────────────────────


def follow_state(follower: str, followee: str) -> str | None:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT state FROM social_follows WHERE follower_id = ? AND followee_id = ?",
            (follower, followee),
        ).fetchone()
    return row["state"] if row else None


def set_follow(follower: str, followee: str, state: str) -> None:
    with get_connection() as conn:
        conn.execute(
            "INSERT INTO social_follows (follower_id, followee_id, state, created_at)"
            " VALUES (?,?,?,?) ON CONFLICT (follower_id, followee_id)"
            " DO UPDATE SET state = excluded.state",
            (follower, followee, state, now_iso()),
        )


def delete_follow(follower: str, followee: str) -> bool:
    with get_connection() as conn:
        cur = conn.execute(
            "DELETE FROM social_follows WHERE follower_id = ? AND followee_id = ?",
            (follower, followee),
        )
    return cur.rowcount > 0


def count_followers(user_id: str) -> int:
    with get_connection() as conn:
        return conn.execute(
            "SELECT COUNT(*) FROM social_follows f JOIN social_profiles p"
            " ON p.user_id = f.follower_id"
            " WHERE f.followee_id = ? AND f.state = 'following'"
            " AND p.visibility != 'private'",
            (user_id,),
        ).fetchone()[0]


def count_following(user_id: str) -> int:
    with get_connection() as conn:
        return conn.execute(
            "SELECT COUNT(*) FROM social_follows f JOIN social_profiles p"
            " ON p.user_id = f.followee_id"
            " WHERE f.follower_id = ? AND f.state = 'following'"
            " AND p.visibility != 'private'",
            (user_id,),
        ).fetchone()[0]


def list_follow_edges(
    user_id: str, direction: str, cursor: int | None, limit: int
) -> tuple[list[dict], int | None]:
    """Accepted followers (``direction='followers'``) or followed users
    (``'following'``) of ``user_id`` with a visible (non-private) profile.
    Newest first; the cursor is the last row's rowid."""
    mine, other = (
        ("followee_id", "follower_id")
        if direction == "followers"
        else ("follower_id", "followee_id")
    )
    sql = (
        f"SELECT f.rowid AS rid, p.handle FROM social_follows f"  # nosec B608
        f" JOIN social_profiles p ON p.user_id = f.{other}"
        f" WHERE f.{mine} = ? AND f.state = 'following'"
        f" AND p.visibility != 'private'"
    )
    params: list = [user_id]
    if cursor is not None:
        sql += " AND f.rowid < ?"
        params.append(cursor)
    sql += " ORDER BY f.rowid DESC LIMIT ?"
    params.append(limit + 1)
    with get_connection() as conn:
        rows = conn.execute(sql, params).fetchall()
    more = len(rows) > limit
    rows = rows[:limit]
    return [{"handle": r["handle"]} for r in rows], (rows[-1]["rid"] if more else None)


def list_requests(user_id: str, limit: int = 100) -> list[dict]:
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT p.handle, f.created_at FROM social_follows f JOIN social_profiles p"
            " ON p.user_id = f.follower_id WHERE f.followee_id = ?"
            " AND f.state = 'pending' ORDER BY f.created_at DESC, f.rowid DESC LIMIT ?",
            (user_id, limit),
        ).fetchall()
    return [dict(r) for r in rows]


# ── daily limits ──────────────────────────────────────────────────────────────


def today() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%d")


def used_today(user_id: str, kind: str) -> int:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT n FROM social_limits WHERE user_id = ? AND day = ? AND kind = ?",
            (user_id, today(), kind),
        ).fetchone()
    return row["n"] if row else 0


def consume_daily(user_id: str, kind: str, cap: int) -> bool:
    """Count one use against today's cap; False (nothing counted) when at it."""
    day = today()
    with get_connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            "SELECT n FROM social_limits WHERE user_id = ? AND day = ? AND kind = ?",
            (user_id, day, kind),
        ).fetchone()
        n = row["n"] if row else 0
        if n >= cap:
            return False
        conn.execute(
            "INSERT INTO social_limits (user_id, day, kind, n) VALUES (?,?,?,1)"
            " ON CONFLICT (user_id, day, kind) DO UPDATE SET n = n + 1",
            (user_id, day, kind),
        )
        # keep the table small: drop counters older than a week
        old = (datetime.now(UTC) - timedelta(days=7)).strftime("%Y-%m-%d")
        conn.execute("DELETE FROM social_limits WHERE day < ?", (old,))
    return True


def ideas_count(user_id: str) -> int:
    """Published ideas by the user; 0 until the ideas table exists (T2)."""
    try:
        with get_connection() as conn:
            return conn.execute(
                "SELECT COUNT(*) FROM ideas WHERE author_id = ? AND status = 'published'",
                (user_id,),
            ).fetchone()[0]
    except sqlite3.OperationalError:
        return 0
