"""SQLite persistence for price watches (hotel, activity and whole-trip
prices) and their price history.

Additive next to the fare-watch tables (``fare_watch_db``), which stay
untouched; the daily SerpAPI budget (``fare_watch_db.reserve_calls``) is
shared by both kinds of watch.
"""

import json
from datetime import UTC, datetime

from .database import get_connection

HISTORY_KEEP = 120  # rows of price history kept per watch

# Columns a caller may set on create (everything else is scheduler state or
# defaults): the matched subject, the baseline look and its schedule.
_CREATE_FIELDS = (
    "kind",
    "plan_id",
    "title",
    "subtitle",
    "subject",
    "match_key",
    "currency",
    "alert_mode",
    "target_price",
    "email_enabled",
    "expires_on",
    "baseline_price",
    "last_price",
    "lowest_price",
    "check_count",
    "last_checked_at",
    "next_check_at",
    "last_observation",
    "lease_until",
)

_BOOL_FIELDS = ("email_enabled",)
_JSON_FIELDS = ("subject", "last_observation")


def create_price_watch_tables() -> None:
    with get_connection() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS price_watches (
                id                  INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id             TEXT    NOT NULL REFERENCES users(id),
                kind                TEXT    NOT NULL,
                plan_id             INTEGER,
                title               TEXT    NOT NULL,
                subtitle            TEXT,
                subject             TEXT    NOT NULL DEFAULT '{}',
                match_key           TEXT,
                currency            TEXT    NOT NULL DEFAULT 'USD',
                alert_mode          TEXT    NOT NULL DEFAULT 'any_drop',
                target_price        REAL,
                email_enabled       INTEGER NOT NULL DEFAULT 0,
                status              TEXT    NOT NULL DEFAULT 'active',
                baseline_price      REAL,
                last_price          REAL,
                lowest_price        REAL,
                last_notified_price REAL,
                last_notified_at    TEXT,
                own_peak_price      REAL,
                failure_count       INTEGER NOT NULL DEFAULT 0,
                unavailable_count   INTEGER NOT NULL DEFAULT 0,
                last_error          TEXT,
                last_observation    TEXT,
                check_count         INTEGER NOT NULL DEFAULT 0,
                last_checked_at     TEXT,
                next_check_at       TEXT,
                lease_until         TEXT,
                expires_on          TEXT    NOT NULL,
                created_at          TEXT    NOT NULL,
                updated_at          TEXT    NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_price_watches_user
                ON price_watches (user_id, kind);
            CREATE INDEX IF NOT EXISTS idx_price_watches_due
                ON price_watches (status, next_check_at);

            CREATE TABLE IF NOT EXISTS price_watch_history (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                watch_id    INTEGER NOT NULL REFERENCES price_watches(id),
                checked_at  TEXT    NOT NULL,
                price       REAL,
                breakdown   TEXT,
                observed    TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_price_watch_history_watch
                ON price_watch_history (watch_id, checked_at);
        """)


def _row(row) -> dict | None:
    if row is None:
        return None
    d = dict(row)
    for f in _BOOL_FIELDS:
        d[f] = bool(d[f])
    for f in _JSON_FIELDS:
        d[f] = json.loads(d[f]) if d[f] else None
    if d["subject"] is None:
        d["subject"] = {}
    return d


def _encode(fields: dict) -> dict:
    for f in _BOOL_FIELDS:
        if f in fields:
            fields[f] = int(bool(fields[f]))
    for f in _JSON_FIELDS:
        if f in fields and fields[f] is not None:
            fields[f] = json.dumps(fields[f])
    return fields


# ── Watches ───────────────────────────────────────────────────────────────────


def create_watch(user_id: str, fields: dict, *, now: datetime) -> dict:
    """Insert an active watch. Only ``_CREATE_FIELDS`` are taken from
    ``fields``; status, failures and alert state start fresh."""
    values = _encode(
        {k: fields[k] for k in _CREATE_FIELDS if fields.get(k) is not None}
    )
    stamp = now.isoformat()
    values.setdefault("next_check_at", stamp)
    values.update(user_id=user_id, created_at=stamp, updated_at=stamp)
    cols = ", ".join(values)
    marks = ", ".join("?" * len(values))
    with get_connection() as conn:
        cur = conn.execute(
            f"INSERT INTO price_watches ({cols}) VALUES ({marks})",  # nosec B608
            list(values.values()),
        )
        wid = cur.lastrowid
    return get_watch(wid)


def get_watch(watch_id: int) -> dict | None:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM price_watches WHERE id = ?", (watch_id,)
        ).fetchone()
    return _row(row)


def get_watch_for_user(watch_id: int, user_id: str) -> dict | None:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM price_watches WHERE id = ? AND user_id = ?",
            (watch_id, user_id),
        ).fetchone()
    return _row(row)


def list_watches(user_id: str, kind: str | None = None) -> list[dict]:
    sql = "SELECT * FROM price_watches WHERE user_id = ?"
    params: list = [user_id]
    if kind is not None:
        sql += " AND kind = ?"
        params.append(kind)
    sql += " ORDER BY expires_on ASC, id ASC"
    with get_connection() as conn:
        rows = conn.execute(sql, params).fetchall()
    return [_row(r) for r in rows]


def find_watch(user_id: str, kind: str, match_key: str) -> dict | None:
    """The user's newest watch of ``kind`` for this subject, if any."""
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM price_watches WHERE user_id = ? AND kind = ? "
            "AND match_key = ? ORDER BY id DESC LIMIT 1",
            (user_id, kind, match_key),
        ).fetchone()
    return _row(row)


def count_active(user_id: str) -> int:
    with get_connection() as conn:
        return conn.execute(
            "SELECT COUNT(*) FROM price_watches WHERE user_id = ? "
            "AND status = 'active'",
            (user_id,),
        ).fetchone()[0]


def update_watch(watch_id: int, **fields) -> dict | None:
    """Set the given columns (names come from code, never from requests)."""
    if fields:
        _encode(fields)
        if "updated_at" not in fields:
            fields["updated_at"] = datetime.now(UTC).isoformat()
        sets = ", ".join(f"{k} = ?" for k in fields)
        with get_connection() as conn:
            conn.execute(
                f"UPDATE price_watches SET {sets} WHERE id = ?",  # nosec B608
                [*fields.values(), watch_id],
            )
    return get_watch(watch_id)


def disable_email_for_user(user_id: str) -> None:
    with get_connection() as conn:
        conn.execute(
            "UPDATE price_watches SET email_enabled = 0 WHERE user_id = ?",
            (user_id,),
        )


def delete_watch(watch_id: int, user_id: str) -> bool:
    with get_connection() as conn:
        cur = conn.execute(
            "DELETE FROM price_watches WHERE id = ? AND user_id = ?",
            (watch_id, user_id),
        )
        if not cur.rowcount:
            return False
        conn.execute("DELETE FROM price_watch_history WHERE watch_id = ?", (watch_id,))
    return True


def expire_inactive_past(today: str, *, now: datetime) -> int:
    """End paused / errored watches whose day has come (no notice: nobody
    is waiting on them). Active ones expire through their own check."""
    with get_connection() as conn:
        return conn.execute(
            "UPDATE price_watches SET status = 'expired', updated_at = ? "
            "WHERE status IN ('paused', 'error') AND expires_on <= ?",
            (now.isoformat(), today),
        ).rowcount


def due_watch_ids(now: datetime, limit: int) -> list[int]:
    """Active watches due for a check and not leased, oldest due first
    (read-only: ``claim_watch`` leases each one when its turn comes)."""
    stamp = now.isoformat()
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT id FROM price_watches WHERE status = 'active'"
            " AND next_check_at <= ? AND (lease_until IS NULL OR lease_until < ?)"
            " ORDER BY next_check_at, id LIMIT ?",
            (stamp, stamp, limit),
        ).fetchall()
    return [r[0] for r in rows]


def claim_watch(
    watch_id: int, now: datetime, lease_until: datetime, *, due_only: bool = False
) -> bool:
    """Lease one watch; False while someone else holds it. ``due_only``
    (the scheduler) also requires it to be active and still due."""
    sql = (
        "UPDATE price_watches SET lease_until = ? WHERE id = ? "
        "AND (lease_until IS NULL OR lease_until < ?)"
    )
    params: list = [lease_until.isoformat(), watch_id, now.isoformat()]
    if due_only:
        sql += " AND status = 'active' AND next_check_at <= ?"
        params.append(now.isoformat())
    with get_connection() as conn:
        return conn.execute(sql, params).rowcount == 1


# ── History ───────────────────────────────────────────────────────────────────


def add_history(watch_id: int, entry: dict) -> None:
    """Append one look (price, trip breakdown, raw observed details),
    keeping the newest HISTORY_KEEP rows."""
    breakdown, observed = entry.get("breakdown"), entry.get("observed")
    with get_connection() as conn:
        conn.execute(
            "INSERT INTO price_watch_history (watch_id, checked_at, price, "
            "breakdown, observed) VALUES (?, ?, ?, ?, ?)",
            (
                watch_id,
                entry["checked_at"],
                entry.get("price"),
                json.dumps(breakdown) if breakdown is not None else None,
                json.dumps(observed) if observed is not None else None,
            ),
        )
        conn.execute(
            "DELETE FROM price_watch_history WHERE watch_id = ? AND id NOT IN ("
            " SELECT id FROM price_watch_history WHERE watch_id = ?"
            " ORDER BY id DESC LIMIT ?)",
            (watch_id, watch_id, HISTORY_KEEP),
        )


def get_history(watch_id: int) -> list[dict]:
    """Oldest first."""
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT checked_at, price, breakdown, observed FROM price_watch_history "
            "WHERE watch_id = ? ORDER BY id ASC",
            (watch_id,),
        ).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        for f in ("breakdown", "observed"):
            d[f] = json.loads(d[f]) if d[f] else None
        out.append(d)
    return out
