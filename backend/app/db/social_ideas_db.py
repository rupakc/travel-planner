"""SQLite persistence for Phase 5 ideas, likes, saves, comments, reports and
restrictions. Additive only (``CREATE TABLE IF NOT EXISTS``).

Statuses (ideas and comments): ``published``, ``held`` (filter unsure, author
and admins only), ``hidden`` (auto-hidden by reports until an admin decides)
and ``removed``. Visibility rules live in the SQL clauses below so feed, single
reads and comment lists agree.
"""

import json
from datetime import UTC, datetime, timedelta

from .database import get_connection
from .social_db import now_iso


def create_social_ideas_tables() -> None:
    with get_connection() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS ideas (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                author_id     TEXT NOT NULL,
                plan_id       INTEGER NOT NULL,
                kind          TEXT NOT NULL,
                title         TEXT NOT NULL,
                caption       TEXT NOT NULL DEFAULT '',
                snapshot_json TEXT NOT NULL,
                tags_json     TEXT NOT NULL DEFAULT '[]',
                status        TEXT NOT NULL DEFAULT 'published',
                created_at    TEXT NOT NULL,
                updated_at    TEXT NOT NULL,
                UNIQUE (author_id, plan_id, kind)
            );
            CREATE INDEX IF NOT EXISTS idx_ideas_feed ON ideas (status, id);
            CREATE INDEX IF NOT EXISTS idx_ideas_author ON ideas (author_id, id);
            CREATE TABLE IF NOT EXISTS idea_likes (
                idea_id     INTEGER NOT NULL,
                user_id     TEXT NOT NULL,
                created_at  TEXT NOT NULL,
                PRIMARY KEY (idea_id, user_id)
            );
            CREATE TABLE IF NOT EXISTS idea_saves (
                idea_id     INTEGER NOT NULL,
                user_id     TEXT NOT NULL,
                plan_id     INTEGER,
                created_at  TEXT NOT NULL,
                PRIMARY KEY (idea_id, user_id)
            );
            CREATE TABLE IF NOT EXISTS comments (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                idea_id     INTEGER NOT NULL,
                author_id   TEXT NOT NULL,
                text        TEXT NOT NULL,
                status      TEXT NOT NULL DEFAULT 'published',
                helpful     INTEGER NOT NULL DEFAULT 0,
                created_at  TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_comments_idea ON comments (idea_id, id);
            CREATE TABLE IF NOT EXISTS reports (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                target       TEXT NOT NULL,
                target_id    TEXT NOT NULL,
                reporter_id  TEXT NOT NULL,
                reason       TEXT NOT NULL,
                note         TEXT NOT NULL DEFAULT '',
                counted      INTEGER NOT NULL DEFAULT 0,
                resolved     INTEGER NOT NULL DEFAULT 0,
                created_at   TEXT NOT NULL,
                UNIQUE (reporter_id, target, target_id)
            );
            CREATE INDEX IF NOT EXISTS idx_reports_target ON reports (target, target_id);
            CREATE TABLE IF NOT EXISTS restrictions (
                user_id     TEXT PRIMARY KEY,
                until       TEXT NOT NULL,
                created_at  TEXT NOT NULL
            );
        """)


# ── visibility ────────────────────────────────────────────────────────────────

_NOT_BLOCKED = (
    "NOT EXISTS (SELECT 1 FROM social_blocks b WHERE"
    " (b.blocker_id = :viewer AND b.blocked_id = {a})"
    " OR (b.blocker_id = {a} AND b.blocked_id = :viewer))"
)
_FOLLOWS = (
    "EXISTS (SELECT 1 FROM social_follows f WHERE f.follower_id = :viewer"
    " AND f.followee_id = {a} AND f.state = 'following')"
)


def _public_clause(author: str = "i.author_id") -> str:
    """Ideas a non-admin viewer may see: published, author non-private (a
    ``followers`` author only to followers and themself), not blocked."""
    return (
        "i.status = 'published' AND p.visibility != 'private'"
        f" AND (p.visibility = 'public' OR {author} = :viewer OR "
        + _FOLLOWS.format(a=author)
        + ") AND "
        + _NOT_BLOCKED.format(a=author)
    )


_SELECT = """
SELECT i.id, i.author_id, i.plan_id, i.kind, i.title, i.caption, i.snapshot_json,
       i.tags_json, i.status, i.created_at, p.handle AS author_handle,
       p.visibility AS author_visibility, p.show_avatar AS author_show_avatar,
       (SELECT COUNT(*) FROM idea_likes l WHERE l.idea_id = i.id) AS likes,
       (SELECT COUNT(*) FROM idea_saves s WHERE s.idea_id = i.id) AS saves,
       (SELECT COUNT(*) FROM comments c WHERE c.idea_id = i.id
          AND c.status = 'published') AS comments,
       EXISTS (SELECT 1 FROM idea_likes l WHERE l.idea_id = i.id
          AND l.user_id = :viewer) AS liked,
       EXISTS (SELECT 1 FROM idea_saves s WHERE s.idea_id = i.id
          AND s.user_id = :viewer) AS saved
FROM ideas i JOIN social_profiles p ON p.user_id = i.author_id
"""


def _idea(row) -> dict:
    d = dict(row)
    d["snapshot"] = json.loads(d.pop("snapshot_json"))
    d.pop("tags_json", None)
    for k in ("liked", "saved"):
        d[k] = bool(d[k])
    return d


def _run(sql: str, params: dict, viewer: str) -> list[dict]:
    params = {**params, "viewer": viewer}
    with get_connection() as conn:
        rows = conn.execute(sql, params).fetchall()
    out = []
    for r in rows:
        d = _idea(r)
        d["mine"] = d["author_id"] == viewer
        out.append(d)
    return out


def get_idea(idea_id: int, viewer: str, *, admin: bool = False) -> dict | None:
    """The idea if ``viewer`` may see it (author: own non-removed ideas;
    admin: any; else published and public to them), else None."""
    rows = _run(_SELECT + " WHERE i.id = :id", {"id": idea_id}, viewer)
    if not rows:
        return None
    idea = rows[0]
    if admin:
        return idea
    if idea["author_id"] == viewer:
        return idea if idea["status"] != "removed" else None
    with get_connection() as conn:
        ok = conn.execute(
            _SELECT + " WHERE i.id = :id AND " + _public_clause(),
            {"id": idea_id, "viewer": viewer},
        ).fetchone()
    return idea if ok else None


def get_idea_raw(idea_id: int) -> dict | None:
    with get_connection() as conn:
        row = conn.execute("SELECT * FROM ideas WHERE id = ?", (idea_id,)).fetchone()
    return dict(row) if row else None


def find_idea(author_id: str, plan_id: int, kind: str) -> dict | None:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM ideas WHERE author_id = ? AND plan_id = ? AND kind = ?",
            (author_id, plan_id, kind),
        ).fetchone()
    return dict(row) if row else None


def upsert_idea(
    author_id: str,
    plan_id: int,
    kind: str,
    title: str,
    caption: str,
    snapshot: dict,
    tags: list[str],
    status: str,
) -> int:
    ts = now_iso()
    with get_connection() as conn:
        conn.execute(
            "INSERT INTO ideas (author_id, plan_id, kind, title, caption,"
            " snapshot_json, tags_json, status, created_at, updated_at)"
            " VALUES (?,?,?,?,?,?,?,?,?,?)"
            " ON CONFLICT (author_id, plan_id, kind) DO UPDATE SET"
            " title = excluded.title, caption = excluded.caption,"
            " snapshot_json = excluded.snapshot_json, tags_json = excluded.tags_json,"
            " status = excluded.status, updated_at = excluded.updated_at",
            (
                author_id,
                plan_id,
                kind,
                title,
                caption,
                json.dumps(snapshot),
                json.dumps(tags, ensure_ascii=False),
                status,
                ts,
                ts,
            ),
        )
        return conn.execute(
            "SELECT id FROM ideas WHERE author_id = ? AND plan_id = ? AND kind = ?",
            (author_id, plan_id, kind),
        ).fetchone()["id"]


def delete_idea(idea_id: int) -> None:
    with get_connection() as conn:
        for t in ("idea_likes", "idea_saves", "comments"):
            conn.execute(f"DELETE FROM {t} WHERE idea_id = ?", (idea_id,))  # nosec B608
        conn.execute(
            "DELETE FROM reports WHERE target = 'idea' AND target_id = ?",
            (str(idea_id),),
        )
        conn.execute("DELETE FROM ideas WHERE id = ?", (idea_id,))


def set_status(table: str, row_id: int, status: str) -> None:
    assert table in ("ideas", "comments")  # noqa: S101
    with get_connection() as conn:
        conn.execute(
            f"UPDATE {table} SET status = ? WHERE id = ?",  # nosec B608
            (status, row_id),
        )


# ── feed ──────────────────────────────────────────────────────────────────────


def feed(
    viewer: str,
    scope: str,
    *,
    cursor: int | None,
    limit: int,
    interests: list[str] | None = None,
) -> tuple[list[dict], int | None]:
    """One page of the feed. ``new`` / ``following`` are keyset on id (cursor =
    last id); ``for_you`` is ranked and uses an offset cursor."""
    where = _public_clause()
    if scope == "following":
        where += " AND " + _FOLLOWS.format(a="i.author_id")
    params: dict = {}
    if scope == "for_you":
        from ..services import feed_rank

        score, sparams = feed_rank.score_sql(interests or [])
        params.update(sparams)
        sql = (
            f"{_SELECT} WHERE {where} ORDER BY {score} DESC, i.id DESC"
            " LIMIT :limit OFFSET :offset"
        )
        params.update(limit=limit + 1, offset=cursor or 0)
        rows = _run(sql, params, viewer)
        more = len(rows) > limit
        return rows[:limit], ((cursor or 0) + limit if more else None)
    if cursor is not None:
        where += " AND i.id < :cursor"
        params["cursor"] = cursor
    sql = f"{_SELECT} WHERE {where} ORDER BY i.id DESC LIMIT :limit"
    params["limit"] = limit + 1
    rows = _run(sql, params, viewer)
    more = len(rows) > limit
    rows = rows[:limit]
    return rows, (rows[-1]["id"] if more else None)


def profile_ideas(
    viewer: str, author_id: str, *, cursor: int | None, limit: int
) -> tuple[list[dict], int | None]:
    where = (
        "i.author_id = :author AND i.status != 'removed'"
        if author_id == viewer
        else _public_clause() + " AND i.author_id = :author"
    )
    params: dict = {"author": author_id}
    if cursor is not None:
        where += " AND i.id < :cursor"
        params["cursor"] = cursor
    params["limit"] = limit + 1
    rows = _run(
        f"{_SELECT} WHERE {where} ORDER BY i.id DESC LIMIT :limit", params, viewer
    )
    more = len(rows) > limit
    rows = rows[:limit]
    return rows, (rows[-1]["id"] if more else None)


# ── likes and saves ───────────────────────────────────────────────────────────


def set_like(idea_id: int, user_id: str, on: bool) -> None:
    with get_connection() as conn:
        if on:
            conn.execute(
                "INSERT OR IGNORE INTO idea_likes (idea_id, user_id, created_at)"
                " VALUES (?,?,?)",
                (idea_id, user_id, now_iso()),
            )
        else:
            conn.execute(
                "DELETE FROM idea_likes WHERE idea_id = ? AND user_id = ?",
                (idea_id, user_id),
            )


def get_save(idea_id: int, user_id: str) -> dict | None:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM idea_saves WHERE idea_id = ? AND user_id = ?",
            (idea_id, user_id),
        ).fetchone()
    return dict(row) if row else None


def put_save(idea_id: int, user_id: str, plan_id: int) -> None:
    with get_connection() as conn:
        conn.execute(
            "INSERT INTO idea_saves (idea_id, user_id, plan_id, created_at)"
            " VALUES (?,?,?,?) ON CONFLICT (idea_id, user_id)"
            " DO UPDATE SET plan_id = excluded.plan_id",
            (idea_id, user_id, plan_id, now_iso()),
        )


def delete_save(idea_id: int, user_id: str) -> None:
    with get_connection() as conn:
        conn.execute(
            "DELETE FROM idea_saves WHERE idea_id = ? AND user_id = ?",
            (idea_id, user_id),
        )


# ── comments ──────────────────────────────────────────────────────────────────


def add_comment(idea_id: int, author_id: str, text: str, status: str) -> int:
    with get_connection() as conn:
        cur = conn.execute(
            "INSERT INTO comments (idea_id, author_id, text, status, created_at)"
            " VALUES (?,?,?,?,?)",
            (idea_id, author_id, text, status, now_iso()),
        )
        return cur.lastrowid


def get_comment(comment_id: int) -> dict | None:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT c.*, p.handle AS author_handle FROM comments c"
            " LEFT JOIN social_profiles p ON p.user_id = c.author_id WHERE c.id = ?",
            (comment_id,),
        ).fetchone()
    return dict(row) if row else None


def list_comments(
    idea_id: int, viewer: str, *, admin: bool, cursor: int | None, limit: int
) -> tuple[list[dict], int | None]:
    """Oldest first. Published comments, plus the viewer's own held ones (all
    held ones for an admin); never a blocked pair's."""
    where = (
        "c.idea_id = :idea AND (c.status = 'published' OR"
        " (c.status = 'held' AND (c.author_id = :viewer OR :admin)))"
        " AND " + _NOT_BLOCKED.format(a="c.author_id")
    )
    params: dict = {"idea": idea_id, "viewer": viewer, "admin": int(admin)}
    if cursor is not None:
        where += " AND c.id > :cursor"
        params["cursor"] = cursor
    params["limit"] = limit + 1
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT c.id, c.text, c.helpful, c.status, c.created_at, c.author_id,"
            " p.handle AS author_handle FROM comments c"
            " JOIN social_profiles p ON p.user_id = c.author_id"
            f" WHERE {where} ORDER BY c.id ASC LIMIT :limit",  # nosec B608
            params,
        ).fetchall()
    more = len(rows) > limit
    rows = [dict(r) for r in rows[:limit]]
    for r in rows:
        r["helpful"] = bool(r["helpful"])
        r["mine"] = r["author_id"] == viewer
    return rows, (rows[-1]["id"] if more else None)


def set_helpful(comment_id: int, on: bool) -> None:
    with get_connection() as conn:
        conn.execute(
            "UPDATE comments SET helpful = ? WHERE id = ?", (int(on), comment_id)
        )


def delete_comment(comment_id: int) -> None:
    with get_connection() as conn:
        conn.execute("DELETE FROM comments WHERE id = ?", (comment_id,))
        conn.execute(
            "DELETE FROM reports WHERE target = 'comment' AND target_id = ?",
            (str(comment_id),),
        )


# ── reports ───────────────────────────────────────────────────────────────────


def add_report(
    reporter_id: str, target: str, target_id: str, reason: str, note: str, counted: bool
) -> bool:
    """False when this reporter already reported the target."""
    with get_connection() as conn:
        cur = conn.execute(
            "INSERT OR IGNORE INTO reports (target, target_id, reporter_id, reason,"
            " note, counted, created_at) VALUES (?,?,?,?,?,?,?)",
            (target, target_id, reporter_id, reason, note, int(counted), now_iso()),
        )
    return cur.rowcount > 0


def counted_reporters(target: str, target_id: str) -> int:
    with get_connection() as conn:
        return conn.execute(
            "SELECT COUNT(*) FROM reports WHERE target = ? AND target_id = ?"
            " AND counted = 1 AND resolved = 0",
            (target, target_id),
        ).fetchone()[0]


def resolve_reports(target: str, target_id: str) -> None:
    with get_connection() as conn:
        conn.execute(
            "UPDATE reports SET resolved = 1 WHERE target = ? AND target_id = ?",
            (target, target_id),
        )


def reason_counts(target: str, target_id: str) -> dict[str, int]:
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT reason, COUNT(*) n FROM reports WHERE target = ? AND target_id = ?"
            " AND resolved = 0 GROUP BY reason",
            (target, target_id),
        ).fetchall()
    return {r["reason"]: r["n"] for r in rows}


# ── admin queue ───────────────────────────────────────────────────────────────


def queue(status: str) -> list[dict]:
    """Moderation items for ``held`` / ``hidden`` (by status) or ``reported``
    (published with open reports; profiles included), newest first."""
    items: list[dict] = []
    with get_connection() as conn:
        for target, table, text_col in (
            ("idea", "ideas", "title"),
            ("comment", "comments", "text"),
        ):
            if status == "reported":
                cond = (
                    "t.status = 'published' AND EXISTS (SELECT 1 FROM reports r"
                    " WHERE r.target = ? AND r.target_id = CAST(t.id AS TEXT)"
                    " AND r.resolved = 0)"
                )
                params: tuple = (target,)
            else:
                cond, params = "t.status = ?", (status,)
            author = "author_id"
            rows = conn.execute(
                f"SELECT t.id, CAST(t.id AS TEXT) AS _ref, t.status,"  # nosec B608
                f" t.{text_col} AS excerpt, t.created_at,"
                f" p.handle AS author_handle FROM {table} t"
                f" LEFT JOIN social_profiles p ON p.user_id = t.{author}"
                f" WHERE {cond}",
                params,
            ).fetchall()
            items += [{"target": target, **dict(r)} for r in rows]
        if status == "reported":
            rows = conn.execute(
                "SELECT p.handle AS id, p.user_id AS _ref, p.handle AS author_handle, p.bio AS excerpt,"
                " p.created_at FROM social_profiles p WHERE EXISTS (SELECT 1 FROM"
                " reports r WHERE r.target = 'profile' AND r.target_id = p.user_id"
                " AND r.resolved = 0)"
            ).fetchall()
            items += [
                {"target": "profile", "status": "reported", **dict(r)} for r in rows
            ]
    items.sort(key=lambda d: (d["created_at"], str(d["id"])), reverse=True)
    return items


# ── restrictions ──────────────────────────────────────────────────────────────


def restrict(user_id: str, days: int) -> str:
    ts = now_iso()
    until = (datetime.now(UTC) + timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")
    with get_connection() as conn:
        conn.execute(
            "INSERT INTO restrictions (user_id, until, created_at) VALUES (?,?,?)"
            " ON CONFLICT (user_id) DO UPDATE SET until = excluded.until",
            (user_id, until, ts),
        )
    return until


def lift(user_id: str) -> None:
    with get_connection() as conn:
        conn.execute("DELETE FROM restrictions WHERE user_id = ?", (user_id,))


def is_restricted(user_id: str) -> bool:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT until FROM restrictions WHERE user_id = ?", (user_id,)
        ).fetchone()
    return bool(row and row["until"] > now_iso())
