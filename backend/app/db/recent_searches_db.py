"""SQLite persistence for each user's recent trip searches."""

import hashlib
import json
import uuid
from datetime import UTC, datetime

from .database import get_connection

MAX_RECENT_SEARCHES = 8


def create_recent_searches_table() -> None:
    with get_connection() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS recent_searches (
                id            TEXT PRIMARY KEY,
                username      TEXT NOT NULL,
                search_key    TEXT NOT NULL,
                search_data   TEXT NOT NULL,
                last_used_at  TEXT NOT NULL,
                UNIQUE (username, search_key)
            );
            CREATE INDEX IF NOT EXISTS idx_recent_searches_user
                ON recent_searches(username, last_used_at);
        """)


def _search_key(search: dict) -> str:
    """Identity of a search — the same trip with interests in another order
    is the same search, so repeats merge instead of piling up."""
    canonical = {**search, "interests": sorted(search.get("interests") or [])}
    payload = json.dumps(canonical, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode()).hexdigest()


def _row_to_dict(row) -> dict:
    return {
        "id": row["id"],
        "search": json.loads(row["search_data"]),
        "last_used_at": row["last_used_at"],
    }


def record_search(username: str, search: dict) -> dict:
    """Insert a search (or bump an identical one to the top), then trim the
    user's history to the newest MAX_RECENT_SEARCHES entries."""
    now = datetime.now(UTC).isoformat()
    with get_connection() as conn:
        conn.execute(
            """INSERT INTO recent_searches (id, username, search_key, search_data, last_used_at)
               VALUES (?, ?, ?, ?, ?)
               ON CONFLICT(username, search_key) DO UPDATE SET
                   search_data  = excluded.search_data,
                   last_used_at = excluded.last_used_at
            """,
            (str(uuid.uuid4()), username, _search_key(search), json.dumps(search), now),
        )
        conn.execute(
            """DELETE FROM recent_searches
               WHERE username = ? AND id NOT IN (
                   SELECT id FROM recent_searches WHERE username = ?
                   ORDER BY last_used_at DESC LIMIT ?
               )""",
            (username, username, MAX_RECENT_SEARCHES),
        )
        row = conn.execute(
            "SELECT * FROM recent_searches WHERE username = ? AND search_key = ?",
            (username, _search_key(search)),
        ).fetchone()
    return _row_to_dict(row)


def list_recent_searches(username: str) -> list[dict]:
    with get_connection() as conn:
        rows = conn.execute(
            """SELECT * FROM recent_searches WHERE username = ?
               ORDER BY last_used_at DESC LIMIT ?""",
            (username, MAX_RECENT_SEARCHES),
        ).fetchall()
    return [_row_to_dict(r) for r in rows]


def delete_recent_search(username: str, search_id: str) -> bool:
    """Delete one of the user's entries. Returns False when it isn't theirs."""
    with get_connection() as conn:
        cur = conn.execute(
            "DELETE FROM recent_searches WHERE id = ? AND username = ?",
            (search_id, username),
        )
    return cur.rowcount > 0
