"""Persistence for the game: xp_ledger, user_badges, user_streaks."""

import json
import sqlite3
from datetime import datetime

from .database import get_connection


def iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def total_xp(conn: sqlite3.Connection, user_id: str) -> int:
    row = conn.execute(
        "SELECT COALESCE(SUM(points), 0) FROM xp_ledger WHERE user_id = ?", (user_id,)
    ).fetchone()
    return int(row[0])


def count_rule(
    conn: sqlite3.Connection, user_id: str, rule: str, since: str | None = None
) -> int:
    sql = "SELECT COUNT(*) FROM xp_ledger WHERE user_id = ? AND rule = ?"
    args: list = [user_id, rule]
    if since:
        sql += " AND created_at >= ?"
        args.append(since)
    return int(conn.execute(sql, args).fetchone()[0])


def insert_ledger(
    conn: sqlite3.Connection,
    user_id: str,
    rule: str,
    points: int,
    idem_key: str,
    meta: dict | None,
    created_at: str,
) -> bool:
    """False when ``idem_key`` already exists."""
    cur = conn.execute(
        "INSERT OR IGNORE INTO xp_ledger (user_id, rule, points, idem_key, meta, created_at)"
        " VALUES (?, ?, ?, ?, ?, ?)",
        (
            user_id,
            rule,
            points,
            idem_key,
            json.dumps(meta) if meta else None,
            created_at,
        ),
    )
    return cur.rowcount == 1


def get_badge(conn: sqlite3.Connection, user_id: str, badge_id: str):
    return conn.execute(
        "SELECT * FROM user_badges WHERE user_id = ? AND badge_id = ?",
        (user_id, badge_id),
    ).fetchone()


def upsert_badge(
    conn: sqlite3.Connection,
    user_id: str,
    badge_id: str,
    progress: int,
    target: int,
    earned_at: str | None,
    now: str,
) -> None:
    conn.execute(
        "INSERT INTO user_badges (user_id, badge_id, progress, target, earned_at, updated_at)"
        " VALUES (?, ?, ?, ?, ?, ?)"
        " ON CONFLICT(user_id, badge_id) DO UPDATE SET progress = excluded.progress,"
        " target = excluded.target, earned_at = excluded.earned_at,"
        " updated_at = excluded.updated_at",
        (user_id, badge_id, progress, target, earned_at, now),
    )


def list_badges(conn: sqlite3.Connection, user_id: str) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM user_badges WHERE user_id = ? ORDER BY badge_id", (user_id,)
    ).fetchall()


def recent(conn: sqlite3.Connection, user_id: str, limit: int = 10) -> list[dict]:
    rows = conn.execute(
        "SELECT rule, points, created_at FROM xp_ledger WHERE user_id = ?"
        " ORDER BY id DESC LIMIT ?",
        (user_id, limit),
    ).fetchall()
    return [dict(r) for r in rows]


def get_streak(conn: sqlite3.Connection, user_id: str, kind: str):
    return conn.execute(
        "SELECT * FROM user_streaks WHERE user_id = ? AND kind = ?", (user_id, kind)
    ).fetchone()


def save_streak(
    conn: sqlite3.Connection, user_id: str, kind: str, s: dict, now: str
) -> None:
    conn.execute(
        "INSERT INTO user_streaks (user_id, kind, current, longest, last_day, freezes,"
        " freeze_week, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)"
        " ON CONFLICT(user_id, kind) DO UPDATE SET current = excluded.current,"
        " longest = excluded.longest, last_day = excluded.last_day,"
        " freezes = excluded.freezes, freeze_week = excluded.freeze_week,"
        " updated_at = excluded.updated_at",
        (
            user_id,
            kind,
            s["current"],
            s["longest"],
            s["last_day"],
            s["freezes"],
            s["freeze_week"],
            now,
        ),
    )


def hide_game(user_id: str) -> bool:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT data FROM user_settings WHERE user_id = ?", (user_id,)
        ).fetchone()
    if not row:
        return False
    try:
        return bool(json.loads(row["data"]).get("hide_game", False))
    except (ValueError, AttributeError):
        return False
