"""SQLite persistence for Phase 4 share links (``shares``). Additive only."""

import json
import secrets
from datetime import UTC, datetime

from .database import get_connection

OPTION_KEYS = ("dates", "show_origin", "show_name", "locale")


def create_shares_table() -> None:
    with get_connection() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS shares (
                token         TEXT PRIMARY KEY,
                username      TEXT NOT NULL,
                kind          TEXT NOT NULL,
                plan_id       INTEGER,
                options_json  TEXT NOT NULL,
                created_at    TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_shares_username
                ON shares (username, created_at);
            CREATE INDEX IF NOT EXISTS idx_shares_plan ON shares (plan_id);
            CREATE UNIQUE INDEX IF NOT EXISTS idx_shares_unique
                ON shares (username, kind, COALESCE(plan_id, -1));
        """)


def _row(row) -> dict:
    d = dict(row)
    d["options"] = json.loads(d.pop("options_json"))
    return d


def upsert_share(username: str, kind: str, plan_id: int | None, options: dict) -> dict:
    """The caller's share for (kind, plan_id): created, or its options updated."""
    payload = json.dumps({k: options.get(k) for k in OPTION_KEYS})
    with get_connection() as conn:
        row = conn.execute(
            "SELECT token FROM shares WHERE username = ? AND kind = ? "
            "AND COALESCE(plan_id, -1) = COALESCE(?, -1)",
            (username, kind, plan_id),
        ).fetchone()
        if row:
            token = row["token"]
            conn.execute(
                "UPDATE shares SET options_json = ? WHERE token = ?", (payload, token)
            )
        else:
            token = secrets.token_urlsafe(16)
            conn.execute(
                "INSERT INTO shares (token, username, kind, plan_id, options_json,"
                " created_at) VALUES (?,?,?,?,?,?)",
                (
                    token,
                    username,
                    kind,
                    plan_id,
                    payload,
                    datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
                ),
            )
    return get_share(token)


def get_share(token: str) -> dict | None:
    if not token:
        return None
    with get_connection() as conn:
        row = conn.execute("SELECT * FROM shares WHERE token = ?", (token,)).fetchone()
    return _row(row) if row else None


def list_shares(username: str, limit: int = 100) -> list[dict]:
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM shares WHERE username = ? "
            "ORDER BY created_at DESC, rowid DESC LIMIT ?",
            (username, limit),
        ).fetchall()
    return [_row(r) for r in rows]


def delete_share(token: str, username: str) -> bool:
    with get_connection() as conn:
        cur = conn.execute(
            "DELETE FROM shares WHERE token = ? AND username = ?", (token, username)
        )
    return cur.rowcount > 0
