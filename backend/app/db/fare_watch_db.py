"""SQLite persistence for fare watches, their price history and the daily
SerpAPI call budget the fare-watch scheduler spends."""

from datetime import UTC, datetime

from .database import get_connection

HISTORY_KEEP = 120  # rows of price history kept per watch

# Columns a caller may set on create (everything else is scheduler state)
_CREATE_FIELDS = (
    "plan_id",
    "origin_code",
    "destination_code",
    "origin_label",
    "destination_label",
    "departure_date",
    "return_date",
    "num_travelers",
    "cabin",
    "flexible_days",
    "alert_mode",
    "target_price",
    "email_enabled",
)

_BOOL_FIELDS = ("email_enabled",)


def create_fare_watch_tables() -> None:
    with get_connection() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS fare_watches (
                id                  INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id             TEXT    NOT NULL REFERENCES users(id),
                plan_id             INTEGER,
                origin_code         TEXT    NOT NULL,
                destination_code    TEXT    NOT NULL,
                origin_label        TEXT    NOT NULL,
                destination_label   TEXT    NOT NULL,
                departure_date      TEXT    NOT NULL,
                return_date         TEXT,
                num_travelers       INTEGER NOT NULL DEFAULT 1,
                cabin               TEXT    NOT NULL DEFAULT 'economy',
                flexible_days       INTEGER NOT NULL DEFAULT 0,
                alert_mode          TEXT    NOT NULL DEFAULT 'any_drop',
                target_price        REAL,
                email_enabled       INTEGER NOT NULL DEFAULT 0,
                status              TEXT    NOT NULL DEFAULT 'active',
                baseline_price      REAL,
                last_price          REAL,
                lowest_price        REAL,
                lowest_price_date   TEXT,
                last_notified_price REAL,
                last_notified_at    TEXT,
                google_price_level  TEXT,
                google_typical_low  REAL,
                google_typical_high REAL,
                check_count         INTEGER NOT NULL DEFAULT 0,
                failure_count       INTEGER NOT NULL DEFAULT 0,
                last_checked_at     TEXT,
                next_check_at       TEXT,
                lease_until         TEXT,
                last_error          TEXT,
                created_at          TEXT    NOT NULL,
                updated_at          TEXT    NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_fare_watches_user
                ON fare_watches (user_id);
            CREATE INDEX IF NOT EXISTS idx_fare_watches_due
                ON fare_watches (status, next_check_at);

            CREATE TABLE IF NOT EXISTS fare_watch_history (
                id                      INTEGER PRIMARY KEY AUTOINCREMENT,
                watch_id                INTEGER NOT NULL REFERENCES fare_watches(id),
                checked_at              TEXT    NOT NULL,
                price                   REAL,
                cheapest_price          REAL,
                cheapest_departure_date TEXT,
                cheapest_return_date    TEXT,
                price_level             TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_fare_watch_history_watch
                ON fare_watch_history (watch_id, checked_at);

            CREATE TABLE IF NOT EXISTS fare_watch_quota (
                day   TEXT    PRIMARY KEY,
                calls INTEGER NOT NULL DEFAULT 0
            );
        """)


def _row(row) -> dict | None:
    if row is None:
        return None
    d = dict(row)
    for f in _BOOL_FIELDS:
        d[f] = bool(d[f])
    return d


# ── Watches ───────────────────────────────────────────────────────────────────


def create_watch(user_id: str, fields: dict, *, now: datetime) -> dict:
    """Insert an active watch, due for its first (baseline) check at ``now``."""
    values = {k: fields[k] for k in _CREATE_FIELDS if fields.get(k) is not None}
    if "email_enabled" in values:
        values["email_enabled"] = int(bool(values["email_enabled"]))
    stamp = now.isoformat()
    values.update(
        user_id=user_id, next_check_at=stamp, created_at=stamp, updated_at=stamp
    )
    cols = ", ".join(values)
    marks = ", ".join("?" * len(values))
    with get_connection() as conn:
        cur = conn.execute(
            f"INSERT INTO fare_watches ({cols}) VALUES ({marks})",  # nosec B608
            list(values.values()),
        )
        wid = cur.lastrowid
    return get_watch(wid)


def get_watch(watch_id: int) -> dict | None:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM fare_watches WHERE id = ?", (watch_id,)
        ).fetchone()
    return _row(row)


def get_watch_for_user(watch_id: int, user_id: str) -> dict | None:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM fare_watches WHERE id = ? AND user_id = ?",
            (watch_id, user_id),
        ).fetchone()
    return _row(row)


def list_watches(user_id: str) -> list[dict]:
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM fare_watches WHERE user_id = ? "
            "ORDER BY departure_date ASC, id ASC",
            (user_id,),
        ).fetchall()
    return [_row(r) for r in rows]


def find_watch(
    user_id: str,
    origin_code: str,
    destination_code: str,
    departure_date: str,
    return_date: str | None,
    num_travelers: int,
) -> dict | None:
    """The user's newest watch for exactly this trip, if any."""
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM fare_watches WHERE user_id = ? AND origin_code = ? "
            "AND destination_code = ? AND departure_date = ? "
            "AND return_date IS ? AND num_travelers = ? "
            "ORDER BY id DESC LIMIT 1",
            (
                user_id,
                origin_code,
                destination_code,
                departure_date,
                return_date,
                num_travelers,
            ),
        ).fetchone()
    return _row(row)


def count_active(user_id: str) -> int:
    with get_connection() as conn:
        return conn.execute(
            "SELECT COUNT(*) FROM fare_watches WHERE user_id = ? AND status = 'active'",
            (user_id,),
        ).fetchone()[0]


def update_watch(watch_id: int, **fields) -> dict | None:
    """Set the given columns (names come from code, never from requests)."""
    if fields:
        for f in _BOOL_FIELDS:
            if f in fields:
                fields[f] = int(bool(fields[f]))
        if "updated_at" not in fields:
            fields["updated_at"] = datetime.now(UTC).isoformat()
        sets = ", ".join(f"{k} = ?" for k in fields)
        with get_connection() as conn:
            conn.execute(
                f"UPDATE fare_watches SET {sets} WHERE id = ?",  # nosec B608
                [*fields.values(), watch_id],
            )
    return get_watch(watch_id)


def delete_watch(watch_id: int, user_id: str) -> bool:
    with get_connection() as conn:
        cur = conn.execute(
            "DELETE FROM fare_watches WHERE id = ? AND user_id = ?",
            (watch_id, user_id),
        )
        if not cur.rowcount:
            return False
        conn.execute("DELETE FROM fare_watch_history WHERE watch_id = ?", (watch_id,))
    return True


def claim_due(now: datetime, lease_until: datetime, limit: int) -> list[int]:
    """Atomically lease up to ``limit`` due active watches; returns their ids.

    One UPDATE … RETURNING, so two schedulers (several workers) can never
    claim the same watch while its lease is live.
    """
    stamp = now.isoformat()
    with get_connection() as conn:
        rows = conn.execute(
            "UPDATE fare_watches SET lease_until = ? WHERE id IN ("
            " SELECT id FROM fare_watches WHERE status = 'active'"
            " AND next_check_at <= ?"
            " AND (lease_until IS NULL OR lease_until < ?)"
            " ORDER BY next_check_at LIMIT ?) RETURNING id",
            (lease_until.isoformat(), stamp, stamp, limit),
        ).fetchall()
    return sorted(r[0] for r in rows)


# ── History ───────────────────────────────────────────────────────────────────


def add_history(watch_id: int, entry: dict) -> None:
    """Append one check's prices, keeping the newest HISTORY_KEEP rows."""
    with get_connection() as conn:
        conn.execute(
            "INSERT INTO fare_watch_history (watch_id, checked_at, price, "
            "cheapest_price, cheapest_departure_date, cheapest_return_date, "
            "price_level) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                watch_id,
                entry["checked_at"],
                entry.get("price"),
                entry.get("cheapest_price"),
                entry.get("cheapest_departure_date"),
                entry.get("cheapest_return_date"),
                entry.get("price_level"),
            ),
        )
        conn.execute(
            "DELETE FROM fare_watch_history WHERE watch_id = ? AND id NOT IN ("
            " SELECT id FROM fare_watch_history WHERE watch_id = ?"
            " ORDER BY id DESC LIMIT ?)",
            (watch_id, watch_id, HISTORY_KEEP),
        )


def get_history(watch_id: int) -> list[dict]:
    """Oldest first."""
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT checked_at, price, cheapest_price, cheapest_departure_date, "
            "cheapest_return_date, price_level FROM fare_watch_history "
            "WHERE watch_id = ? ORDER BY id ASC",
            (watch_id,),
        ).fetchall()
    return [dict(r) for r in rows]


# ── Daily SerpAPI budget ──────────────────────────────────────────────────────


def reserve_calls(day: str, n: int, budget: int) -> bool:
    """Take ``n`` calls from ``day``'s budget, all or nothing."""
    with get_connection() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO fare_watch_quota (day, calls) VALUES (?, 0)", (day,)
        )
        cur = conn.execute(
            "UPDATE fare_watch_quota SET calls = calls + ? "
            "WHERE day = ? AND calls + ? <= ?",
            (n, day, n, budget),
        )
        return cur.rowcount == 1


def calls_used(day: str) -> int:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT calls FROM fare_watch_quota WHERE day = ?", (day,)
        ).fetchone()
    return row[0] if row else 0
