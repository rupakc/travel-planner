"""SQLite persistence for push-notification devices (FCM registration tokens).

A token belongs to one user at a time: registering it again from another
account moves it (a shared phone signs in as someone else).
"""

from datetime import datetime

from .database import get_connection

MAX_DEVICES_PER_USER = 20  # oldest (by last_seen_at) evicted beyond this


def create_devices_table() -> None:
    with get_connection() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS devices (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                username      TEXT    NOT NULL,
                token         TEXT    NOT NULL UNIQUE,
                platform      TEXT    NOT NULL DEFAULT 'android',
                locale        TEXT,
                created_at    TEXT    NOT NULL,
                last_seen_at  TEXT    NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_devices_username
                ON devices (username, last_seen_at);
        """)


def masked(token: str) -> str:
    """What the API shows of a token: its last 6 characters."""
    return "…" + token[-6:]


def _public(row) -> dict:
    d = dict(row)
    d["token"] = masked(d["token"])
    return {k: v for k, v in d.items() if k != "username"}


def upsert_device(
    username: str, token: str, platform: str, locale: str | None, *, now: datetime
) -> dict:
    """Register (or refresh) a token for ``username`` and evict the user's
    oldest devices beyond the cap. Returns the device, token masked."""
    stamp = now.isoformat()
    with get_connection() as conn:
        conn.execute(
            "INSERT INTO devices (username, token, platform, locale, created_at,"
            " last_seen_at) VALUES (?, ?, ?, ?, ?, ?)"
            " ON CONFLICT(token) DO UPDATE SET"
            "  created_at = CASE WHEN devices.username = excluded.username"
            "               THEN devices.created_at ELSE excluded.created_at END,"
            "  username = excluded.username, platform = excluded.platform,"
            "  locale = excluded.locale, last_seen_at = excluded.last_seen_at",
            (username, token, platform, locale, stamp, stamp),
        )
        conn.execute(
            "DELETE FROM devices WHERE username = ? AND id NOT IN ("
            " SELECT id FROM devices WHERE username = ?"
            " ORDER BY last_seen_at DESC, id DESC LIMIT ?)",
            (username, username, MAX_DEVICES_PER_USER),
        )
        row = conn.execute("SELECT * FROM devices WHERE token = ?", (token,)).fetchone()
    return _public(row)


def list_devices(username: str) -> list[dict]:
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM devices WHERE username = ?"
            " ORDER BY last_seen_at DESC, id DESC",
            (username,),
        ).fetchall()
    return [_public(r) for r in rows]


def tokens_for(username: str) -> list[str]:
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT token FROM devices WHERE username = ? ORDER BY id",
            (username,),
        ).fetchall()
    return [r["token"] for r in rows]


def delete_device(username: str, device_id: int) -> bool:
    """Delete one of the user's devices by id; False when they don't own it."""
    with get_connection() as conn:
        return (
            conn.execute(
                "DELETE FROM devices WHERE username = ? AND id = ?",
                (username, device_id),
            ).rowcount
            > 0
        )


def unregister(username: str, token: str) -> None:
    """Sign-out: drop the token if the user owns it (anyone else's stays)."""
    with get_connection() as conn:
        conn.execute(
            "DELETE FROM devices WHERE username = ? AND token = ?", (username, token)
        )


def delete_token(token: str) -> None:
    """Prune a token FCM reports as no longer registered."""
    with get_connection() as conn:
        conn.execute("DELETE FROM devices WHERE token = ?", (token,))
