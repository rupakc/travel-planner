"""Telemetry store: separate raw-event DB plus daily rollups in the main DB."""

import sqlite3
from datetime import UTC, datetime

import pytest

from app.core.config import settings
from app.db import telemetry_db
from app.db.database import get_connection

DAY = "2026-11-09"


def _ms(day: str, hour: int = 12) -> int:
    d = datetime.fromisoformat(day).replace(hour=hour, tzinfo=UTC)
    return int(d.timestamp() * 1000)


def _row(ts, anon="a1", session="s1", user_id=None, event="app_open"):
    return {
        "ts": ts,
        "received_at": ts,
        "event": event,
        "session_id": session,
        "anon_id": anon,
        "user_id": user_id,
        "platform": "web",
        "app_version": "1.0",
        "locale": "en",
        "screen": None,
        "props": "{}",
    }


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", str(tmp_path))
    telemetry_db.create_telemetry_tables()


def _daily():
    with get_connection() as conn:
        return [
            tuple(r)
            for r in conn.execute(
                "SELECT day, event, platform, events, users, sessions "
                "FROM telemetry_daily ORDER BY event"
            )
        ]


def test_insert_and_rollup():
    rows = [
        _row(_ms(DAY, 1), anon="a1", session="s1"),
        _row(_ms(DAY, 2), anon="a1", session="s1"),
        _row(_ms(DAY, 3), anon="a2", session="s2", user_id="bob"),
    ]
    assert telemetry_db.insert_events(rows) == 3
    telemetry_db.rollup_day(DAY)
    first = _daily()
    assert first == [(DAY, "app_open", "web", 3, 2, 2)]
    telemetry_db.rollup_day(DAY)
    assert _daily() == first
    with get_connection() as conn:
        assert conn.execute("SELECT COUNT(*) FROM telemetry_rollups").fetchone()[0] == 1


def test_rollup_ignores_other_days():
    telemetry_db.insert_events([_row(_ms("2026-11-08")), _row(_ms(DAY))])
    assert telemetry_db.rollup_day(DAY) == 1


def test_prune_removes_only_older():
    telemetry_db.insert_events([_row(1000), _row(5000)])
    assert telemetry_db.prune(2000) == 1
    with sqlite3.connect(str(telemetry_db.telemetry_db_path())) as conn:
        assert conn.execute("SELECT ts FROM telemetry_events").fetchall() == [(5000,)]


def test_telemetry_db_is_separate_file():
    telemetry_db.insert_events([_row(_ms(DAY))])
    assert telemetry_db.telemetry_db_path().name == "telemetry.db"
    with get_connection() as conn:
        names = {
            r[0]
            for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
    assert "telemetry_events" not in names
    assert {"telemetry_daily", "telemetry_rollups"} <= names
