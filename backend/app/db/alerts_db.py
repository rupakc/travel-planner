"""SQLite persistence for price alerts 2.0: preferences, caught-drop rows,
the push/email outbox, weekly digests and cached advice. Additive tables only."""

import json
from datetime import UTC, datetime

from .database import get_connection

DEFAULT_PREFS: dict = {
    "digest_weekly": False,
    "digest_push": False,
    "digest_day": 1,
    "instant": "all",
    "quiet_hours": {"enabled": True, "start": "22:00", "end": "07:00"},
    "daily_cap": {"flight": 3, "hotel": 3, "activity": 3, "trip": 3},
    "group_window_min": 15,
}


def create_alert_tables() -> None:
    with get_connection() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS alert_prefs (
                user_id     TEXT PRIMARY KEY,
                data        TEXT NOT NULL,
                updated_at  TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS alert_savings (
                id               INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id          TEXT    NOT NULL,
                watch_kind       TEXT    NOT NULL,
                watch_id         INTEGER NOT NULL,
                notification_id  INTEGER NOT NULL UNIQUE,
                from_price       REAL,
                to_price         REAL,
                baseline         REAL,
                currency         TEXT,
                target_hit       INTEGER NOT NULL DEFAULT 0,
                created_at       TEXT    NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_alert_savings_user
                ON alert_savings (user_id, created_at);
            CREATE TABLE IF NOT EXISTS alert_outbox (
                id               INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id          TEXT    NOT NULL,
                notification_id  INTEGER NOT NULL,
                channel          TEXT    NOT NULL
                                 CHECK (channel IN ('push', 'email')),
                watch_kind       TEXT    NOT NULL,
                due_at           TEXT    NOT NULL,
                sent_at          TEXT,
                dropped_reason   TEXT,
                UNIQUE (notification_id, channel)
            );
            CREATE INDEX IF NOT EXISTS idx_alert_outbox_due
                ON alert_outbox (sent_at, due_at);
            CREATE TABLE IF NOT EXISTS alert_digests (
                user_id  TEXT NOT NULL,
                week     TEXT NOT NULL,
                status   TEXT NOT NULL,
                sent_at  TEXT,
                PRIMARY KEY (user_id, week)
            );
            CREATE TABLE IF NOT EXISTS alert_advice (
                watch_kind    TEXT    NOT NULL,
                watch_id      INTEGER NOT NULL,
                tip           TEXT    NOT NULL,
                generated_at  TEXT    NOT NULL,
                PRIMARY KEY (watch_kind, watch_id)
            );
        """)
        cols = {r[1] for r in conn.execute("PRAGMA table_info(alert_advice)")}
        if "locale" not in cols:  # additive: the tip's language (cache key)
            conn.execute("ALTER TABLE alert_advice ADD COLUMN locale TEXT")


def _now() -> str:
    return datetime.now(UTC).replace(tzinfo=None).isoformat() + "Z"


# ── Preferences ───────────────────────────────────────────────────────────────


def get_prefs(user_id: str) -> dict:
    """Stored prefs merged over the defaults (new keys appear automatically)."""
    with get_connection() as conn:
        row = conn.execute(
            "SELECT data FROM alert_prefs WHERE user_id = ?", (user_id,)
        ).fetchone()
    out = json.loads(json.dumps(DEFAULT_PREFS))
    if row:
        try:
            stored = json.loads(row["data"])
        except ValueError:
            stored = {}
        for k, v in stored.items():
            if isinstance(v, dict) and isinstance(out.get(k), dict):
                out[k].update(v)
            else:
                out[k] = v
    return out


def put_prefs(user_id: str, data: dict) -> dict:
    with get_connection() as conn:
        conn.execute(
            "INSERT INTO alert_prefs (user_id, data, updated_at) VALUES (?, ?, ?)"
            " ON CONFLICT(user_id) DO UPDATE SET data = excluded.data,"
            " updated_at = excluded.updated_at",
            (user_id, json.dumps(data), _now()),
        )
    return get_prefs(user_id)


# ── Savings ───────────────────────────────────────────────────────────────────


def insert_saving(row: dict) -> bool:
    """Record one caught drop; ``False`` if the notification already has one."""
    with get_connection() as conn:
        cur = conn.execute(
            "INSERT OR IGNORE INTO alert_savings (user_id, watch_kind, watch_id,"
            " notification_id, from_price, to_price, baseline, currency,"
            " target_hit, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                row["user_id"],
                row["watch_kind"],
                row["watch_id"],
                row["notification_id"],
                row.get("from_price"),
                row.get("to_price"),
                row.get("baseline"),
                row.get("currency"),
                1 if row.get("target_hit") else 0,
                row.get("created_at") or _now(),
            ),
        )
        return cur.rowcount > 0


def savings_rows(user_id: str) -> list[dict]:
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM alert_savings WHERE user_id = ? ORDER BY created_at, id",
            (user_id,),
        ).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["target_hit"] = bool(d["target_hit"])
        out.append(d)
    return out


# ── Outbox ────────────────────────────────────────────────────────────────────


def enqueue(
    user_id: str, notification_id: int, channel: str, watch_kind: str, due_at: str
) -> bool:
    with get_connection() as conn:
        cur = conn.execute(
            "INSERT OR IGNORE INTO alert_outbox (user_id, notification_id, channel,"
            " watch_kind, due_at) VALUES (?, ?, ?, ?, ?)",
            (user_id, notification_id, channel, watch_kind, due_at),
        )
        return cur.rowcount > 0


def claim_due(now: str, limit: int) -> list[dict]:
    """Due, unsent, undropped items, each marked sent atomically so two
    concurrent passes never claim the same one."""
    claimed: list[dict] = []
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM alert_outbox WHERE sent_at IS NULL"
            " AND dropped_reason IS NULL AND due_at <= ?"
            " ORDER BY due_at, id LIMIT ?",
            (now, limit),
        ).fetchall()
        for r in rows:
            cur = conn.execute(
                "UPDATE alert_outbox SET sent_at = ? WHERE id = ? AND sent_at IS NULL",
                (now, r["id"]),
            )
            if cur.rowcount:
                claimed.append(dict(r) | {"sent_at": now})
    return claimed


def mark_dropped(item_id: int, reason: str) -> None:
    with get_connection() as conn:
        conn.execute(
            "UPDATE alert_outbox SET dropped_reason = ? WHERE id = ?",
            (reason, item_id),
        )


def sent_today(user_id: str, kind: str, day_start_utc: str, channel: str) -> int:
    with get_connection() as conn:
        return conn.execute(
            "SELECT COUNT(*) FROM alert_outbox WHERE user_id = ? AND watch_kind = ?"
            " AND channel = ? AND sent_at IS NOT NULL AND sent_at >= ?",
            (user_id, kind, channel, day_start_utc),
        ).fetchone()[0]


def prune(cutoff_iso: str) -> int:
    """Drop outbox and digest rows older than ``cutoff_iso`` (same retention
    as the notifications they point at); returns the rows removed."""
    with get_connection() as conn:
        a = conn.execute(
            "DELETE FROM alert_outbox WHERE due_at < ?", (cutoff_iso,)
        ).rowcount
        b = conn.execute(
            "DELETE FROM alert_digests WHERE sent_at IS NOT NULL AND sent_at < ?",
            (cutoff_iso,),
        ).rowcount
    return a + b


# ── Digests ───────────────────────────────────────────────────────────────────


def digest_claim(user_id: str, week: str) -> bool:
    """First caller for (user, week) wins; later ones (a restart) get ``False``."""
    with get_connection() as conn:
        cur = conn.execute(
            "INSERT OR IGNORE INTO alert_digests (user_id, week, status, sent_at)"
            " VALUES (?, ?, 'claimed', ?)",
            (user_id, week, _now()),
        )
        return cur.rowcount > 0


# ── Advice cache ──────────────────────────────────────────────────────────────


def get_advice(
    watch_kind: str, watch_id: int, locale: str | None = None
) -> dict | None:
    """The cached tip, only when it was written in ``locale`` (``None`` = English)."""
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM alert_advice WHERE watch_kind = ? AND watch_id = ?",
            (watch_kind, watch_id),
        ).fetchone()
    if not row or (row["locale"] or "en") != (locale or "en"):
        return None
    return dict(row)


def put_advice(
    watch_kind: str,
    watch_id: int,
    tip: str,
    generated_at: str,
    locale: str | None = None,
) -> None:
    with get_connection() as conn:
        conn.execute(
            "INSERT INTO alert_advice (watch_kind, watch_id, tip, generated_at, locale)"
            " VALUES (?, ?, ?, ?, ?) ON CONFLICT(watch_kind, watch_id)"
            " DO UPDATE SET tip = excluded.tip, generated_at = excluded.generated_at,"
            " locale = excluded.locale",
            (watch_kind, watch_id, tip, generated_at, locale or "en"),
        )
