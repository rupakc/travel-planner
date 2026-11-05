"""``create_price_watch_tables`` upgrades a DB made by the first price-watch
schema (cba3943, before ``reference_looks``) in place: the new column is
added and every existing watch and history row survives."""

import sqlite3

import pytest

from app.db import database, price_watch_db

# The price_watches / price_watch_history DDL as first shipped (cba3943).
OLD_SCHEMA = """
CREATE TABLE price_watches (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id             TEXT    NOT NULL,
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
CREATE TABLE price_watch_history (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    watch_id    INTEGER NOT NULL REFERENCES price_watches(id),
    checked_at  TEXT    NOT NULL,
    price       REAL,
    breakdown   TEXT,
    observed    TEXT
);
INSERT INTO price_watches (user_id, kind, title, subject, match_key,
    baseline_price, last_price, lowest_price, last_observation, check_count,
    expires_on, created_at, updated_at)
VALUES
    ('u1', 'hotel', 'Lumen Hotel', '{"name": "Lumen Hotel"}', 'lumen',
     398, 380, 380, '{"status": "ok"}', 3,
     '2099-12-10', '2026-11-01T00:00:00+00:00', '2026-11-02T00:00:00+00:00'),
    ('u1', 'trip', 'Lisbon trip', '{"plan_id": 7}', 'plan:7',
     2100, 2050, 2050, NULL, 2,
     '2099-12-10', '2026-11-01T00:00:00+00:00', '2026-11-02T00:00:00+00:00');
INSERT INTO price_watch_history (watch_id, checked_at, price)
VALUES (1, '2026-11-01T00:00:00+00:00', 398),
       (1, '2026-11-02T00:00:00+00:00', 380),
       (2, '2026-11-02T00:00:00+00:00', 2050);
"""


@pytest.fixture
def old_db(tmp_path, monkeypatch):
    path = tmp_path / "airports.db"
    with sqlite3.connect(path) as conn:
        conn.executescript(OLD_SCHEMA)
    monkeypatch.setattr(database, "_db_path", lambda: path)
    return path


def _columns(path) -> set[str]:
    with sqlite3.connect(path) as conn:
        return {r[1] for r in conn.execute("PRAGMA table_info(price_watches)")}


def test_old_schema_gains_new_columns_and_keeps_rows(old_db, tmp_path, monkeypatch):
    assert "reference_looks" not in _columns(old_db)

    price_watch_db.create_price_watch_tables()
    price_watch_db.create_price_watch_tables()  # and again: idempotent

    assert "reference_looks" in _columns(old_db)
    # … and the upgraded table has exactly the columns a fresh one gets
    fresh = tmp_path / "fresh.db"
    monkeypatch.setattr(database, "_db_path", lambda: fresh)
    price_watch_db.create_price_watch_tables()
    assert _columns(old_db) == _columns(fresh)
    monkeypatch.setattr(database, "_db_path", lambda: old_db)

    hotel = price_watch_db.get_watch(1)
    trip = price_watch_db.get_watch(2)
    assert (hotel["title"], hotel["kind"], hotel["subject"]) == (
        "Lumen Hotel",
        "hotel",
        {"name": "Lumen Hotel"},
    )
    assert (hotel["baseline_price"], hotel["last_price"], hotel["check_count"]) == (
        398,
        380,
        3,
    )
    assert hotel["last_observation"] == {"status": "ok"}
    assert hotel["reference_looks"] is None
    assert trip["match_key"] == "plan:7" and trip["subject"] == {"plan_id": 7}
    assert [h["price"] for h in price_watch_db.get_history(1)] == [398, 380]
    assert [h["price"] for h in price_watch_db.get_history(2)] == [2050]

    # The new column is usable on an upgraded row
    looks = {"drop": {"total": 2050, "rows": []}}
    price_watch_db.update_watch(2, reference_looks=looks)
    assert price_watch_db.get_watch(2)["reference_looks"] == looks
