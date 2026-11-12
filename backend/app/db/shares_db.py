"""SQLite persistence for Phase 4 share links (``shares``). Additive only."""

import hashlib
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
        """)
        # Phase 5: a share may point at a quiz session (``ref``) instead of a
        # plan. Additive column; the unique key gains ``ref``.
        cols = {r["name"] for r in conn.execute("PRAGMA table_info(shares)")}
        if "ref" not in cols:
            conn.execute("ALTER TABLE shares ADD COLUMN ref TEXT")
        # idx_shares_unique (the previous release's key) is kept so a rollback
        # can recreate it; ref shares use a distinct negative plan_id surrogate.
        conn.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_shares_unique2 ON shares "
            "(username, kind, COALESCE(plan_id, -1), COALESCE(ref, ''))"
        )


def _surrogate(ref: str) -> int:
    """Distinct negative plan_id for a ref share (never a real plan id)."""
    return -2 - int(
        hashlib.sha1(ref.encode(), usedforsecurity=False).hexdigest()[:8], 16
    )


def _row(row) -> dict:
    d = dict(row)
    if d.get("ref") and (d.get("plan_id") or 0) < 0:
        d["plan_id"] = None
    d["options"] = json.loads(d.pop("options_json"))
    return d


def upsert_share(
    username: str,
    kind: str,
    plan_id: int | None,
    options: dict,
    ref: str | None = None,
) -> dict:
    """The caller's share for (kind, plan_id, ref): created, or its options
    updated. ``ref`` is a non-plan target (a quiz session id)."""
    payload = json.dumps({k: options.get(k) for k in OPTION_KEYS})
    if ref:
        plan_id = _surrogate(ref)
    with get_connection() as conn:
        row = conn.execute(
            "SELECT token FROM shares WHERE username = ? AND kind = ? "
            "AND COALESCE(plan_id, -1) = COALESCE(?, -1) "
            "AND COALESCE(ref, '') = COALESCE(?, '')",
            (username, kind, plan_id, ref),
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
                " created_at, ref) VALUES (?,?,?,?,?,?,?)",
                (
                    token,
                    username,
                    kind,
                    plan_id,
                    payload,
                    datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
                    ref,
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
