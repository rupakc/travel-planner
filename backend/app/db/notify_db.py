"""SQLite persistence for Notifications 2.0: per-user category toggles and the
once-per-(user, plan, kind) delivery log. Additive tables only; both are user
tables (backed up, exported and deleted with the account)."""

import json
from datetime import datetime

from .database import get_connection


def create_notify_tables() -> None:
    with get_connection() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS notify_prefs (
                user_id     TEXT PRIMARY KEY,
                data        TEXT NOT NULL,
                updated_at  TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS notify_log (
                id               INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id          TEXT    NOT NULL,
                plan_id          INTEGER,
                kind             TEXT    NOT NULL,
                dedupe_key       TEXT    NOT NULL UNIQUE,
                category         TEXT    NOT NULL,
                status           TEXT    NOT NULL DEFAULT 'pending',
                due_at           TEXT,
                sent_at          TEXT,
                dropped_reason   TEXT,
                notification_id  INTEGER,
                created_at       TEXT    NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_notify_log_due
                ON notify_log (status, due_at);
            CREATE INDEX IF NOT EXISTS idx_notify_log_user
                ON notify_log (user_id, created_at);
        """)


def _now() -> str:
    return datetime.utcnow().isoformat() + "Z"


def get_data(user_id: str) -> dict:
    """The stored prefs object (``{}`` when none or unreadable)."""
    with get_connection() as conn:
        row = conn.execute(
            "SELECT data FROM notify_prefs WHERE user_id = ?", (user_id,)
        ).fetchone()
    if not row:
        return {}
    try:
        data = json.loads(row["data"])
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


def put_data(user_id: str, data: dict) -> None:
    with get_connection() as conn:
        conn.execute(
            "INSERT INTO notify_prefs (user_id, data, updated_at) VALUES (?, ?, ?)"
            " ON CONFLICT(user_id) DO UPDATE SET data = excluded.data,"
            " updated_at = excluded.updated_at",
            (user_id, json.dumps(data), _now()),
        )
