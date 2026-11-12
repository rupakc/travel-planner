"""SQLite persistence for asynchronous head-to-head matches (``h2h_matches``).
Additive only. Times are epoch milliseconds (server clock). A match points at
two ``quiz_sessions`` (same questions); scores are read from those sessions."""

import sqlite3

from .database import get_connection


def create_play_tables() -> None:
    with get_connection() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS h2h_matches (
                id                  TEXT PRIMARY KEY,
                creator_id          TEXT NOT NULL,
                opponent_id         TEXT NOT NULL,
                pack                TEXT NOT NULL,
                seed                TEXT NOT NULL,
                creator_session_id  TEXT NOT NULL,
                opponent_session_id TEXT,
                declined            INTEGER NOT NULL DEFAULT 0,
                created_ms          INTEGER NOT NULL,
                expires_ms          INTEGER NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_h2h_creator
                ON h2h_matches (creator_id, created_ms);
            CREATE INDEX IF NOT EXISTS idx_h2h_opponent
                ON h2h_matches (opponent_id, created_ms);
            CREATE INDEX IF NOT EXISTS idx_h2h_creator_session
                ON h2h_matches (creator_session_id);
            CREATE INDEX IF NOT EXISTS idx_h2h_opponent_session
                ON h2h_matches (opponent_session_id);
        """)


def create_match(
    conn: sqlite3.Connection,
    mid: str,
    creator_id: str,
    opponent_id: str,
    pack: str,
    seed: str,
    creator_session_id: str,
    now_ms: int,
    ttl_ms: int,
) -> None:
    conn.execute(
        "INSERT INTO h2h_matches (id, creator_id, opponent_id, pack, seed,"
        " creator_session_id, created_ms, expires_ms) VALUES (?,?,?,?,?,?,?,?)",
        (
            mid,
            creator_id,
            opponent_id,
            pack,
            seed,
            creator_session_id,
            now_ms,
            now_ms + ttl_ms,
        ),
    )


def get_match(conn: sqlite3.Connection, mid: str) -> dict | None:
    row = conn.execute("SELECT * FROM h2h_matches WHERE id = ?", (mid,)).fetchone()
    return dict(row) if row else None


def match_for_session(conn: sqlite3.Connection, sid: str) -> dict | None:
    row = conn.execute(
        "SELECT * FROM h2h_matches WHERE creator_session_id = ?"
        " OR opponent_session_id = ?",
        (sid, sid),
    ).fetchone()
    return dict(row) if row else None


def set_opponent_session(conn: sqlite3.Connection, mid: str, sid: str) -> None:
    conn.execute(
        "UPDATE h2h_matches SET opponent_session_id = ? WHERE id = ?", (sid, mid)
    )


def decline(conn: sqlite3.Connection, mid: str) -> None:
    conn.execute("UPDATE h2h_matches SET declined = 1 WHERE id = ?", (mid,))


def list_for_user(
    conn: sqlite3.Connection, user_id: str, limit: int = 50
) -> list[dict]:
    rows = conn.execute(
        "SELECT * FROM h2h_matches WHERE creator_id = ? OR opponent_id = ?"
        " ORDER BY created_ms DESC, id LIMIT ?",
        (user_id, user_id, limit),
    ).fetchall()
    return [dict(r) for r in rows]


def count_created_since(conn: sqlite3.Connection, user_id: str, since_ms: int) -> int:
    return conn.execute(
        "SELECT COUNT(*) FROM h2h_matches WHERE creator_id = ? AND created_ms >= ?",
        (user_id, since_ms),
    ).fetchone()[0]


def count_open_created(conn: sqlite3.Connection, user_id: str, now_ms: int) -> int:
    """Matches I started that are still undecided: not declined, not expired
    and not yet finished by both."""
    return conn.execute(
        "SELECT COUNT(*) FROM h2h_matches m WHERE m.creator_id = ? AND m.declined = 0"
        " AND m.expires_ms > ? AND NOT ("
        " m.opponent_session_id IS NOT NULL"
        " AND EXISTS (SELECT 1 FROM quiz_sessions s WHERE s.id = m.creator_session_id"
        "   AND s.finished_ms IS NOT NULL)"
        " AND EXISTS (SELECT 1 FROM quiz_sessions s WHERE s.id = m.opponent_session_id"
        "   AND s.finished_ms IS NOT NULL))",
        (user_id, now_ms),
    ).fetchone()[0]
