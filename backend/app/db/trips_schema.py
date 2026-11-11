"""Additive schema for the Phase 2 trip journey (idempotent).

Trips are ``plans`` rows; this adds their lifecycle columns, the child tables
keyed by ``plan_id``, and a one-time backfill of dates from ``search_data``.
"""

from .database import get_connection

_PLAN_COLUMNS = {
    "title": "TEXT",
    "phase": "TEXT",
    "start_date": "TEXT",
    "end_date": "TEXT",
    "recap_completed_at": "TEXT",
}

BACKFILL_KEY = "trips_backfill_v1"

_DATE_GLOB = "[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]"

_TABLES = """
CREATE TABLE IF NOT EXISTS trip_expenses (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    plan_id      INTEGER NOT NULL,
    client_id    TEXT    NOT NULL,
    amount_minor INTEGER NOT NULL,
    currency     TEXT    NOT NULL,
    category     TEXT    NOT NULL,
    note         TEXT,
    spent_on     TEXT    NOT NULL,
    created_at   TEXT    NOT NULL,
    updated_at   TEXT    NOT NULL,
    UNIQUE(plan_id, client_id)
);
CREATE INDEX IF NOT EXISTS idx_trip_expenses_plan ON trip_expenses (plan_id);
CREATE TABLE IF NOT EXISTS trip_journal (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    plan_id    INTEGER NOT NULL,
    client_id  TEXT    NOT NULL,
    day        TEXT,
    body       TEXT    NOT NULL,
    mood       TEXT,
    created_at TEXT    NOT NULL,
    updated_at TEXT    NOT NULL,
    UNIQUE(plan_id, client_id)
);
CREATE INDEX IF NOT EXISTS idx_trip_journal_plan ON trip_journal (plan_id);
CREATE TABLE IF NOT EXISTS trip_ratings (
    plan_id    INTEGER NOT NULL,
    place_key  TEXT    NOT NULL,
    name       TEXT    NOT NULL,
    kind       TEXT    NOT NULL,
    visited    INTEGER NOT NULL DEFAULT 0,
    stars      INTEGER,
    note       TEXT,
    day        TEXT,
    lat        REAL,
    lng        REAL,
    visited_at TEXT,
    updated_at TEXT    NOT NULL,
    PRIMARY KEY(plan_id, place_key)
);
CREATE TABLE IF NOT EXISTS trip_prep (
    plan_id    INTEGER NOT NULL,
    item_id    TEXT    NOT NULL,
    done_at    TEXT,
    meta       TEXT,
    updated_at TEXT    NOT NULL,
    PRIMARY KEY(plan_id, item_id)
);
CREATE TABLE IF NOT EXISTS trip_snapshots (
    plan_id    INTEGER PRIMARY KEY,
    data       TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS trip_checkins (
    plan_id      INTEGER NOT NULL,
    day          TEXT    NOT NULL,
    city         TEXT,
    country_code TEXT,
    created_at   TEXT    NOT NULL,
    PRIMARY KEY(plan_id, day)
);
CREATE TABLE IF NOT EXISTS user_countries (
    user_id       TEXT    NOT NULL,
    country_code  TEXT    NOT NULL,
    first_plan_id INTEGER,
    source        TEXT    NOT NULL,
    visited_at    TEXT    NOT NULL,
    PRIMARY KEY(user_id, country_code)
);
"""


def _backfill(conn) -> None:
    done = conn.execute("SELECT 1 FROM meta WHERE key = ?", (BACKFILL_KEY,)).fetchone()
    if done:
        return
    for col, path in (("start_date", "departure_date"), ("end_date", "return_date")):
        conn.execute(
            f"UPDATE plans SET {col} = json_extract(search_data, '$.{path}') "  # nosec B608
            f"WHERE {col} IS NULL AND json_valid(search_data) "
            f"AND json_extract(search_data, '$.{path}') GLOB ?",
            (_DATE_GLOB,),
        )
    conn.execute(
        "INSERT OR IGNORE INTO meta (key, value) VALUES (?, '1')", (BACKFILL_KEY,)
    )


def create_trip_tables() -> None:
    """Add the trip columns and tables, then backfill dates once. Idempotent."""
    with get_connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        cols = {r["name"] for r in conn.execute("PRAGMA table_info(plans)")}
        for name, decl in _PLAN_COLUMNS.items():
            if name not in cols:
                conn.execute(f"ALTER TABLE plans ADD COLUMN {name} {decl}")
        for stmt in _TABLES.split(";"):
            if stmt.strip():
                conn.execute(stmt)
        _backfill(conn)
