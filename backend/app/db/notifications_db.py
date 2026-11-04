"""SQLite persistence for in-app notifications (fare alerts and watch status)."""

import json
from datetime import datetime

from .database import get_connection


def create_notifications_table() -> None:
    with get_connection() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS notifications (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id     TEXT    NOT NULL REFERENCES users(id),
                kind        TEXT    NOT NULL,
                title       TEXT    NOT NULL,
                body        TEXT    NOT NULL DEFAULT '',
                data        TEXT    NOT NULL DEFAULT '{}',
                created_at  TEXT    NOT NULL,
                read_at     TEXT,
                emailed_at  TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_notifications_user
                ON notifications (user_id, created_at);
        """)


def _row(row) -> dict:
    d = dict(row)
    d["data"] = json.loads(d["data"] or "{}")
    return d


def add_notification(
    user_id: str, kind: str, title: str, body: str, data: dict, *, now: datetime
) -> dict:
    with get_connection() as conn:
        cur = conn.execute(
            "INSERT INTO notifications (user_id, kind, title, body, data, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (user_id, kind, title, body, json.dumps(data), now.isoformat()),
        )
        row = conn.execute(
            "SELECT * FROM notifications WHERE id = ?", (cur.lastrowid,)
        ).fetchone()
    return _row(row)


def list_notifications(
    user_id: str, *, unread_only: bool = False, limit: int = 20, offset: int = 0
) -> dict:
    where = "user_id = ?" + (" AND read_at IS NULL" if unread_only else "")
    with get_connection() as conn:
        rows = conn.execute(
            f"SELECT * FROM notifications WHERE {where} "  # nosec B608
            "ORDER BY created_at DESC, id DESC LIMIT ? OFFSET ?",
            (user_id, limit, offset),
        ).fetchall()
        total = conn.execute(
            f"SELECT COUNT(*) FROM notifications WHERE {where}",  # nosec B608
            (user_id,),
        ).fetchone()[0]
    return {"items": [_row(r) for r in rows], "total": total}


def count_unread(user_id: str) -> int:
    with get_connection() as conn:
        return conn.execute(
            "SELECT COUNT(*) FROM notifications WHERE user_id = ? AND read_at IS NULL",
            (user_id,),
        ).fetchone()[0]


def mark_read(user_id: str, ids: list[int] | None, *, now: datetime) -> int:
    """Mark the user's notifications read: the given ids, or all when None."""
    sql = "UPDATE notifications SET read_at = ? WHERE user_id = ? AND read_at IS NULL"
    params: list = [now.isoformat(), user_id]
    if ids is not None:
        if not ids:
            return 0
        sql += f" AND id IN ({','.join('?' * len(ids))})"
        params += list(ids)
    with get_connection() as conn:
        return conn.execute(sql, params).rowcount


def mark_emailed(notification_id: int, *, now: datetime) -> None:
    with get_connection() as conn:
        conn.execute(
            "UPDATE notifications SET emailed_at = ? WHERE id = ?",
            (now.isoformat(), notification_id),
        )


def delete_older_than(cutoff: datetime) -> int:
    """Retention: drop notifications created before ``cutoff``."""
    with get_connection() as conn:
        return conn.execute(
            "DELETE FROM notifications WHERE created_at < ?", (cutoff.isoformat(),)
        ).rowcount
