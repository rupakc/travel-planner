"""SQLite persistence for user feedback submissions."""

import json
import logging
import uuid
from datetime import datetime, timezone

from .database import get_connection

logger = logging.getLogger(__name__)


def create_feedback_table() -> None:
    with get_connection() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS feedback (
                id         TEXT PRIMARY KEY,
                username   TEXT,
                page       TEXT,
                rating     INTEGER,
                category   TEXT,
                message    TEXT,
                metadata   TEXT,
                created_at TEXT DEFAULT (datetime('now'))
            );
            CREATE INDEX IF NOT EXISTS idx_feedback_created ON feedback(created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_feedback_page     ON feedback(page);
            CREATE INDEX IF NOT EXISTS idx_feedback_rating   ON feedback(rating);
        """)


def submit_feedback(
    *,
    username: str | None,
    page: str,
    rating: int,
    category: str,
    message: str | None = None,
    metadata: dict | None = None,
) -> dict:
    fid = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    meta_str = json.dumps(metadata) if metadata else None
    with get_connection() as conn:
        conn.execute(
            """INSERT INTO feedback (id, username, page, rating, category, message, metadata, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (fid, username, page, rating, category, message, meta_str, now),
        )
    return get_feedback_by_id(fid)


def get_feedback_by_id(fid: str) -> dict | None:
    with get_connection() as conn:
        row = conn.execute("SELECT * FROM feedback WHERE id = ?", (fid,)).fetchone()
    return _row_to_dict(row) if row else None


def list_feedback(
    *,
    page: str | None = None,
    category: str | None = None,
    min_rating: int | None = None,
    limit: int = 200,
) -> list[dict]:
    clauses, params = [], []
    if page:
        clauses.append("page = ?")
        params.append(page)
    if category:
        clauses.append("category = ?")
        params.append(category)
    if min_rating is not None:
        clauses.append("rating >= ?")
        params.append(min_rating)
    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    params.append(limit)
    with get_connection() as conn:
        sql = f"SELECT * FROM feedback {where} ORDER BY created_at DESC LIMIT ?"  # nosec B608
        rows = conn.execute(sql, params).fetchall()
    return [_row_to_dict(r) for r in rows]


def _row_to_dict(row) -> dict:
    d = dict(row)
    if d.get("metadata"):
        try:
            d["metadata"] = json.loads(d["metadata"])
        except Exception:
            d["metadata"] = {}
    return d
