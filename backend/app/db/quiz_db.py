"""SQLite persistence for Play quizzes (``quiz_sessions``, ``quiz_answers``).
Additive only. Times are epoch milliseconds (server clock)."""

import json
import sqlite3

from .database import get_connection


def create_quiz_tables() -> None:
    with get_connection() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS quiz_sessions (
                id             TEXT PRIMARY KEY,
                user_id        TEXT NOT NULL,
                mode           TEXT NOT NULL,
                pack           TEXT,
                day            TEXT NOT NULL,
                seed           TEXT NOT NULL,
                questions_json TEXT NOT NULL,
                created_ms     INTEGER NOT NULL,
                updated_ms     INTEGER NOT NULL,
                finished_ms    INTEGER,
                score          INTEGER NOT NULL DEFAULT 0,
                correct        INTEGER NOT NULL DEFAULT 0,
                xp_json        TEXT,
                streak_json    TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_quiz_sessions_user
                ON quiz_sessions (user_id, mode, day);
            CREATE INDEX IF NOT EXISTS idx_quiz_sessions_done
                ON quiz_sessions (user_id, finished_ms);
            CREATE INDEX IF NOT EXISTS idx_quiz_sessions_finished
                ON quiz_sessions (finished_ms);
            CREATE TABLE IF NOT EXISTS quiz_answers (
                session_id  TEXT NOT NULL,
                idx         INTEGER NOT NULL,
                served_ms   INTEGER NOT NULL,
                answered_ms INTEGER,
                choice      TEXT,
                correct     INTEGER,
                points      INTEGER,
                elapsed_ms  INTEGER,
                PRIMARY KEY (session_id, idx)
            );
        """)


def _session(row: sqlite3.Row | None) -> dict | None:
    if row is None:
        return None
    d = dict(row)
    d["questions"] = json.loads(d.pop("questions_json"))
    d["xp"] = json.loads(d["xp_json"]) if d.get("xp_json") else None
    d["streak"] = json.loads(d["streak_json"]) if d.get("streak_json") else None
    return d


def create_session(
    conn: sqlite3.Connection,
    sid: str,
    user_id: str,
    mode: str,
    pack: str | None,
    day: str,
    seed: str,
    questions: list[dict],
    now_ms: int,
) -> None:
    conn.execute(
        "INSERT INTO quiz_sessions (id, user_id, mode, pack, day, seed, questions_json,"
        " created_ms, updated_ms) VALUES (?,?,?,?,?,?,?,?,?)",
        (sid, user_id, mode, pack, day, seed, json.dumps(questions), now_ms, now_ms),
    )
    conn.execute(
        "INSERT INTO quiz_answers (session_id, idx, served_ms) VALUES (?,0,?)",
        (sid, now_ms),
    )


def get_session(conn: sqlite3.Connection, sid: str) -> dict | None:
    return _session(
        conn.execute("SELECT * FROM quiz_sessions WHERE id = ?", (sid,)).fetchone()
    )


def latest_session(
    conn: sqlite3.Connection, user_id: str, mode: str, day: str, pack: str | None = None
) -> dict | None:
    sql = "SELECT * FROM quiz_sessions WHERE user_id = ? AND mode = ? AND day = ?"
    args: list = [user_id, mode, day]
    if pack is not None:
        sql += " AND pack = ?"
        args.append(pack)
    sql += " ORDER BY created_ms DESC LIMIT 1"
    return _session(conn.execute(sql, args).fetchone())


def answers(conn: sqlite3.Connection, sid: str) -> list[dict]:
    rows = conn.execute(
        "SELECT * FROM quiz_answers WHERE session_id = ? ORDER BY idx", (sid,)
    ).fetchall()
    return [dict(r) for r in rows]


def delete_session(conn: sqlite3.Connection, sid: str) -> None:
    conn.execute("DELETE FROM quiz_answers WHERE session_id = ?", (sid,))
    conn.execute("DELETE FROM quiz_sessions WHERE id = ?", (sid,))


def record_answer(
    conn: sqlite3.Connection,
    sid: str,
    idx: int,
    choice: str,
    correct: bool,
    points: int,
    elapsed_ms: int,
    now_ms: int,
) -> None:
    conn.execute(
        "UPDATE quiz_answers SET answered_ms = ?, choice = ?, correct = ?, points = ?,"
        " elapsed_ms = ? WHERE session_id = ? AND idx = ?",
        (now_ms, choice, int(correct), points, elapsed_ms, sid, idx),
    )
    conn.execute("UPDATE quiz_sessions SET updated_ms = ? WHERE id = ?", (now_ms, sid))


def serve_next(conn: sqlite3.Connection, sid: str, idx: int, now_ms: int) -> None:
    conn.execute(
        "INSERT OR IGNORE INTO quiz_answers (session_id, idx, served_ms) VALUES (?,?,?)",
        (sid, idx, now_ms),
    )


def finish(
    conn: sqlite3.Connection, sid: str, score: int, correct: int, now_ms: int
) -> None:
    conn.execute(
        "UPDATE quiz_sessions SET finished_ms = ?, score = ?, correct = ?,"
        " updated_ms = ? WHERE id = ?",
        (now_ms, score, correct, now_ms, sid),
    )


def save_rewards(
    conn: sqlite3.Connection, sid: str, xp: dict | None, streak: dict | None
) -> None:
    conn.execute(
        "UPDATE quiz_sessions SET xp_json = ?, streak_json = ? WHERE id = ?",
        (json.dumps(xp or {}), json.dumps(streak) if streak else None, sid),
    )


def history(conn: sqlite3.Connection, user_id: str, limit: int) -> list[dict]:
    rows = conn.execute(
        "SELECT id, mode, pack, score, correct, finished_ms FROM quiz_sessions"
        " WHERE user_id = ? AND finished_ms IS NOT NULL"
        " ORDER BY finished_ms DESC, id LIMIT ?",
        (user_id, limit),
    ).fetchall()
    return [dict(r) for r in rows]
