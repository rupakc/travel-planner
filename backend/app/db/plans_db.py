"""SQLite persistence for saved travel plans."""

import json

from .database import get_connection


def create_plans_table() -> None:
    with get_connection() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS plans (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                username    TEXT    NOT NULL,
                name        TEXT    NOT NULL,
                search_data TEXT    NOT NULL,
                selections  TEXT    NOT NULL DEFAULT '{}',
                created_at  TEXT    DEFAULT (datetime('now')),
                updated_at  TEXT    DEFAULT (datetime('now'))
            );
            CREATE INDEX IF NOT EXISTS idx_plans_username ON plans (username);
        """)
        # Migration: share_token for public read-only links (NULL = not shared)
        cols = {
            row["name"] for row in conn.execute("PRAGMA table_info(plans)").fetchall()
        }
        if "share_token" not in cols:
            conn.execute("ALTER TABLE plans ADD COLUMN share_token TEXT")
        conn.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_plans_share_token "
            "ON plans (share_token) WHERE share_token IS NOT NULL"
        )


def _row_to_dict(row) -> dict:
    d = dict(row)
    d["search_data"] = json.loads(d["search_data"])
    d["selections"] = json.loads(d["selections"])
    return d


def save_plan(username: str, name: str, search_data: dict, selections: dict) -> dict:
    with get_connection() as conn:
        cur = conn.execute(
            "INSERT INTO plans (username, name, search_data, selections) VALUES (?,?,?,?)",
            (username, name, json.dumps(search_data), json.dumps(selections)),
        )
        plan_id = cur.lastrowid
    return get_plan(plan_id)


def get_plan(plan_id: int) -> dict | None:
    with get_connection() as conn:
        row = conn.execute("SELECT * FROM plans WHERE id = ?", (plan_id,)).fetchone()
    return _row_to_dict(row) if row else None


def get_user_plans(username: str) -> list[dict]:
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM plans WHERE username = ? ORDER BY updated_at DESC",
            (username,),
        ).fetchall()
    return [_row_to_dict(r) for r in rows]


def update_plan(
    plan_id: int, username: str, name: str | None, selections: dict | None
) -> dict | None:
    sets, vals = ["updated_at = datetime('now')"], []
    if name is not None:
        sets.append("name = ?")
        vals.append(name)
    if selections is not None:
        sets.append("selections = ?")
        vals.append(json.dumps(selections))
    vals += [plan_id, username]
    with get_connection() as conn:
        sql = f"UPDATE plans SET {', '.join(sets)} WHERE id = ? AND username = ?"  # nosec B608
        conn.execute(sql, vals)
    return get_plan(plan_id)


def set_share_token(plan_id: int, username: str, token: str | None) -> dict | None:
    """Set (or clear with None) the public share token for a user's plan."""
    with get_connection() as conn:
        conn.execute(
            "UPDATE plans SET share_token = ? WHERE id = ? AND username = ?",
            (token, plan_id, username),
        )
    return get_plan(plan_id)


def get_plan_by_share_token(token: str) -> dict | None:
    if not token:
        return None
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM plans WHERE share_token = ?", (token,)
        ).fetchone()
    return _row_to_dict(row) if row else None


def delete_plan(plan_id: int, username: str) -> None:
    with get_connection() as conn:
        conn.execute(
            "DELETE FROM plans WHERE id = ? AND username = ?", (plan_id, username)
        )
