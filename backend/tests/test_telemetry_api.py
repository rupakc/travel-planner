"""POST /api/telemetry, the hourly maintenance and the admin summary."""

import gzip
import json
import sqlite3
import time
import uuid
from datetime import UTC, datetime, timedelta

import pytest

from app.core.config import settings
from app.core.rate_limit import _bucket_limit
from app.db import telemetry_db
from app.db.database import get_connection
from app.db.users_db import get_user_by_username
from app.telemetry import maintenance


@pytest.fixture(autouse=True)
def _isolated():
    # The shared test data dir (the `client` app's users live there too): start
    # every test from empty telemetry tables.
    telemetry_db.create_telemetry_tables()
    with telemetry_db._telemetry_connection() as tconn:
        tconn.execute("DELETE FROM telemetry_events")
    telemetry_db.reset_ingest_guard()
    with get_connection() as conn:
        conn.execute("DELETE FROM telemetry_daily")
        conn.execute("DELETE FROM telemetry_rollups")


def _client_block():
    return {
        "anon_id": str(uuid.uuid4()),
        "session_id": str(uuid.uuid4()),
        "platform": "web",
        "app_version": "1.0.0",
        "locale": "en",
    }


def _body(events=None, client=None):
    return {
        "client": client or _client_block(),
        "events": events
        if events is not None
        else [
            {
                "event": "screen_view",
                "ts": int(time.time() * 1000),
                "screen": "/search",
                "props": {"route": "/search"},
            }
        ],
    }


def _rows():
    with telemetry_db._telemetry_connection() as conn:
        return [dict(r) for r in conn.execute("SELECT * FROM telemetry_events")]


def _user_headers(client, admin_headers, name="teleuser"):
    client.post(
        "/api/admin/users",
        json={"username": name, "password": "pass1234-kv", "is_admin": False},
        headers=admin_headers,
    )
    r = client.post(
        "/api/auth/login", json={"username": name, "password": "pass1234-kv"}
    )
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def test_anonymous_post_stored_with_null_user(client):
    r = client.post("/api/telemetry", json=_body())
    assert r.status_code == 204
    rows = _rows()
    assert len(rows) == 1
    assert rows[0]["user_id"] is None
    assert rows[0]["screen"] == "/search"
    assert rows[0]["platform"] == "web"
    assert rows[0]["received_at"] > 0


def test_signed_in_sets_user_id(client, admin_headers):
    h = _user_headers(client, admin_headers)
    uid = get_user_by_username("teleuser")["id"]
    assert client.post("/api/telemetry", json=_body(), headers=h).status_code == 204
    assert _rows()[0]["user_id"] == str(uid)


def test_pii_prop_and_bad_screen_not_stored(client):
    ev = {
        "event": "screen_view",
        "screen": "jane@x.com wrote this",
        "props": {"route": "jane@x.com", "referrer_route": "/ok", "email": "a@b.c"},
    }
    assert client.post("/api/telemetry", json=_body([ev])).status_code == 204
    row = _rows()[0]
    assert row["screen"] is None
    assert json.loads(row["props"]) == {"referrer_route": "/ok"}
    assert "jane" not in json.dumps(row)


def test_all_events_dropped_still_204(client):
    r = client.post("/api/telemetry", json=_body([{"event": "nope"}, 5]))
    assert r.status_code == 204
    assert _rows() == []


def test_too_many_events_422(client):
    ev = {"event": "app_open"}
    assert client.post("/api/telemetry", json=_body([ev] * 101)).status_code == 422
    assert client.post("/api/telemetry", json=_body([ev] * 100)).status_code == 204


@pytest.mark.parametrize(
    "payload",
    [
        {"events": []},
        {"client": {"anon_id": "x"}, "events": []},
        {"client": _client_block(), "events": "no"},
        [1, 2],
    ],
)
def test_malformed_envelope_422(client, payload):
    assert client.post("/api/telemetry", json=payload).status_code == 422


def test_non_json_422(client):
    r = client.post(
        "/api/telemetry",
        content=b"not json",
        headers={"Content-Type": "application/json"},
    )
    assert r.status_code == 422


def test_gzip_body_accepted(client):
    raw = gzip.compress(json.dumps(_body()).encode())
    r = client.post(
        "/api/telemetry",
        content=raw,
        headers={"Content-Type": "application/json", "Content-Encoding": "gzip"},
    )
    assert r.status_code == 204
    assert len(_rows()) == 1


def test_bad_gzip_422(client):
    r = client.post(
        "/api/telemetry",
        content=b"garbage",
        headers={"Content-Type": "application/json", "Content-Encoding": "gzip"},
    )
    assert r.status_code == 422


def test_gzip_bomb_413(client):
    raw = gzip.compress(b" " * (300 * 1024))
    assert len(raw) < 64 * 1024
    r = client.post(
        "/api/telemetry",
        content=raw,
        headers={"Content-Type": "application/json", "Content-Encoding": "gzip"},
    )
    assert r.status_code == 413


def test_raw_body_over_64kb_413(client):
    big = _body([{"event": "app_open", "props": {"pad": "x" * 70000}}])
    assert client.post("/api/telemetry", json=big).status_code == 413


def test_disabled_404(client, monkeypatch):
    monkeypatch.setattr(settings, "telemetry_enabled", False)
    assert client.post("/api/telemetry", json=_body()).status_code == 404
    assert _rows() == []


def test_unusable_telemetry_db_never_blocks_startup(monkeypatch, caplog):
    # telemetry.db is disposable: if it can't be opened, the app still starts
    # with telemetry off (ingest 404, /api/config reports it off).
    from fastapi.testclient import TestClient

    from app.main import app

    def boom():
        raise sqlite3.DatabaseError("file is not a database")

    monkeypatch.setattr(telemetry_db, "create_telemetry_tables", boom)
    try:
        with TestClient(app) as c:
            assert c.get("/health").status_code == 200
            assert c.post("/api/telemetry", json=_body()).status_code == 404
            cfg = c.get("/api/config").json()
            assert cfg["telemetry"]["enabled"] is False
            assert cfg["features"]["telemetry"] is False
        assert any(
            r.levelname == "ERROR" and "telemetry" in r.getMessage().lower()
            for r in caplog.records
        )
    finally:
        telemetry_db.set_available(True)


def test_not_behind_ai_access(client, monkeypatch):
    monkeypatch.setattr(settings, "allow_anonymous_ai", False)
    assert client.post("/api/telemetry", json=_body()).status_code == 204


# --- global disk guard ------------------------------------------------------


def _guard_warnings(caplog):
    return [r for r in caplog.records if "telemetry ingest paused" in r.getMessage()]


def test_size_cap_drops_batch_but_answers_204(client, monkeypatch, caplog):
    monkeypatch.setattr(settings, "telemetry_max_db_mb", 0)  # any file is over
    assert client.post("/api/telemetry", json=_body()).status_code == 204
    assert client.post("/api/telemetry", json=_body()).status_code == 204
    assert _rows() == []
    assert len(_guard_warnings(caplog)) == 1  # at most one warning per hour


def test_size_cap_counts_the_wal(monkeypatch):
    db = telemetry_db.telemetry_db_path()
    wal = db.with_name(db.name + "-wal")
    monkeypatch.setattr(settings, "telemetry_max_db_mb", 1)
    main = db.stat().st_size
    wal_size = wal.stat().st_size if wal.exists() else 0
    assert main + wal_size < 1024 * 1024
    real_size = telemetry_db._file_bytes
    monkeypatch.setattr(
        telemetry_db,
        "_file_bytes",
        lambda p: real_size(p) + (1024 * 1024 if str(p).endswith("-wal") else 0),
    )
    telemetry_db.reset_ingest_guard()
    assert telemetry_db.insert_events_guarded([_row(int(time.time() * 1000))]) == 0


def test_daily_cap_counts_todays_rows(client, monkeypatch, caplog):
    monkeypatch.setattr(settings, "telemetry_max_events_per_day", 3)
    now = int(time.time() * 1000)
    # two rows already stored today (e.g. before a restart), one yesterday
    telemetry_db.insert_events(
        [
            {**_row(now), "received_at": now},
            {**_row(now), "received_at": now},
            {**_row(now), "received_at": now - 86_400_000 * 2},
        ]
    )
    telemetry_db.reset_ingest_guard()
    assert client.post("/api/telemetry", json=_body()).status_code == 204
    assert len(_rows()) == 4  # 2 today + 1 new < cap before insert
    # today's count is now 3 = the cap: further batches are dropped
    assert client.post("/api/telemetry", json=_body()).status_code == 204
    assert client.post("/api/telemetry", json=_body()).status_code == 204
    assert len(_rows()) == 4
    assert len(_guard_warnings(caplog)) == 1


def test_guard_caches_its_checks(monkeypatch):
    calls = []
    real = telemetry_db._count_today

    def counting(*a, **k):
        calls.append(1)
        return real(*a, **k)

    monkeypatch.setattr(telemetry_db, "_count_today", counting)
    now = int(time.time() * 1000)
    for _ in range(5):
        telemetry_db.insert_events_guarded([_row(now)])
    assert len(calls) == 1  # refreshed at most once a minute, counted in between


def test_guard_defaults():
    assert settings.telemetry_max_db_mb == 1024
    assert settings.telemetry_max_events_per_day == 200_000


def test_rate_limit_bucket_resolves_to_setting():
    assert _bucket_limit("telemetry") == settings.rate_limit_telemetry == 120


# --- maintenance -----------------------------------------------------------


def _ms(day: datetime) -> int:
    return int(day.timestamp() * 1000)


def _row(ts, event="app_open", anon="a", session="s"):
    return {
        "ts": ts,
        "received_at": ts,
        "event": event,
        "session_id": session,
        "anon_id": anon,
        "user_id": None,
        "platform": "web",
        "app_version": "1",
        "locale": "en",
        "screen": None,
        "props": "{}",
    }


def test_maintenance_rolls_up_missed_days_and_prunes():
    now = datetime(2026, 11, 10, 3, tzinfo=UTC)
    telemetry_db.insert_events(
        [
            _row(_ms(now - timedelta(days=3)), anon="a", session="s1"),
            _row(_ms(now - timedelta(days=1)), anon="b", session="s2"),
            _row(_ms(now)),  # today: not rolled up
            _row(_ms(now - timedelta(days=100))),  # past retention
        ]
    )
    with get_connection() as conn:
        conn.execute(
            "INSERT INTO telemetry_rollups (day, done_at) VALUES ('2026-11-06', 'x')"
        )
    maintenance.maintain_once(now)
    with get_connection() as conn:
        days = {r[0] for r in conn.execute("SELECT day FROM telemetry_rollups")}
        daily = {r[0] for r in conn.execute("SELECT day FROM telemetry_daily")}
    # the trailing 7 complete days (11-03 .. 11-09) are (re-)rolled
    assert days == {f"2026-11-{d:02d}" for d in range(3, 10)}
    assert daily == {"2026-11-07", "2026-11-09"}  # the days that had events
    assert len(_rows()) == 3  # the 100-day-old row pruned


def test_maintenance_rerolls_late_events_for_rolled_up_day():
    now = datetime(2026, 11, 10, 3, tzinfo=UTC)
    two_days_ago = now - timedelta(days=2)  # 2026-11-08
    telemetry_db.insert_events([_row(_ms(two_days_ago), anon="a", session="s1")])
    maintenance.maintain_once(now)
    with get_connection() as conn:
        n = conn.execute(
            "SELECT events FROM telemetry_daily_totals "
            "WHERE day = '2026-11-08' AND platform = '*'"
        ).fetchone()[0]
    assert n == 1
    # an offline client delivers a late event for the already-rolled-up day
    telemetry_db.insert_events([_row(_ms(two_days_ago), anon="b", session="s2")])
    maintenance.maintain_once(now)
    with get_connection() as conn:
        row = conn.execute(
            "SELECT users, sessions, events FROM telemetry_daily_totals "
            "WHERE day = '2026-11-08' AND platform = '*'"
        ).fetchone()
        ev = conn.execute(
            "SELECT events FROM telemetry_daily WHERE day = '2026-11-08'"
        ).fetchone()[0]
    assert tuple(row) == (2, 2, 2)
    assert ev == 2


def _rollup_tables():
    with get_connection() as conn:
        return {
            t: sorted(tuple(r) for r in conn.execute(f"SELECT * FROM {t}"))  # nosec B608
            for t in ("telemetry_daily", "telemetry_daily_totals", "telemetry_rollups")
        }


def test_maintenance_idle_rerun_changes_nothing():
    # vm_backup uploads user tables when their digest changes: an idle hourly
    # re-roll of the trailing window must leave every row byte-identical.
    now = datetime(2026, 11, 10, 3, tzinfo=UTC)
    telemetry_db.insert_events(
        [
            _row(_ms(now - timedelta(days=2)), anon="a", session="s1"),
            _row(_ms(now - timedelta(days=1)), anon="b", session="s2"),
        ]
    )
    maintenance.maintain_once(now)
    first = _rollup_tables()
    assert first["telemetry_rollups"]
    time.sleep(0.01)
    maintenance.maintain_once(now + timedelta(hours=1))
    assert _rollup_tables() == first


def test_maintenance_never_raises(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("x")

    monkeypatch.setattr(telemetry_db, "rollup_day", boom)
    maintenance.maintain_once(datetime(2026, 11, 10, tzinfo=UTC))


# --- admin summary ---------------------------------------------------------


def test_summary_requires_admin(client, admin_headers):
    h = _user_headers(client, admin_headers)
    assert client.get("/api/admin/telemetry/summary", headers=h).status_code == 403
    assert client.get("/api/admin/telemetry/summary").status_code in (401, 403)


def test_summary_counts(client, admin_headers):
    now = datetime.now(UTC)
    yday = now - timedelta(days=1)
    telemetry_db.insert_events(
        [
            _row(_ms(yday), "app_open", "a", "s1"),
            _row(_ms(yday), "app_open", "b", "s2"),
            _row(_ms(yday), "screen_view", "a", "s1") | {"props": '{"route": "/x"}'},
            _row(_ms(now), "screen_view", "c", "s3") | {"props": '{"route": "/x"}'},
        ]
    )
    telemetry_db.rollup_day(yday.strftime("%Y-%m-%d"))
    r = client.get("/api/admin/telemetry/summary?days=30", headers=admin_headers)
    assert r.status_code == 200
    body = r.json()
    by_day = {d["day"]: d for d in body["days"]}
    y = by_day[yday.strftime("%Y-%m-%d")]
    assert (y["users"], y["sessions"], y["events"]) == (2, 2, 3)
    today = by_day[now.strftime("%Y-%m-%d")]
    assert (today["users"], today["sessions"], today["events"]) == (1, 1, 1)
    top = {e["event"]: e["events"] for e in body["top_events"]}
    assert top == {"app_open": 2, "screen_view": 2}
    assert body["top_screens"][0] == {"route": "/x", "views": 2}


def test_summary_users_sum_across_platforms_and_events(client, admin_headers):
    yday = datetime.now(UTC) - timedelta(days=1)
    ts = _ms(yday)
    rows = []
    for i in range(3):  # 3 web users firing app_open
        rows.append(_row(ts, "app_open", f"w{i}", f"ws{i}"))
    for i in range(2):  # 2 android users firing a different event
        rows.append(
            _row(ts, "screen_view", f"m{i}", f"ms{i}")
            | {"platform": "android", "props": '{"route": "/x"}'}
        )
    telemetry_db.insert_events(rows)
    telemetry_db.rollup_day(yday.strftime("%Y-%m-%d"))
    body = client.get("/api/admin/telemetry/summary", headers=admin_headers).json()
    y = {d["day"]: d for d in body["days"]}[yday.strftime("%Y-%m-%d")]
    assert (y["users"], y["sessions"], y["events"]) == (5, 5, 5)
    with get_connection() as conn:
        per = {
            r[0]: r[1]
            for r in conn.execute(
                "SELECT platform, users FROM telemetry_daily_totals WHERE day = ?",
                (yday.strftime("%Y-%m-%d"),),
            )
        }
    assert per == {"web": 3, "android": 2, "*": 5}


def test_summary_users_7d_is_distinct_across_days(client, admin_headers):
    now = datetime.now(UTC)
    telemetry_db.insert_events(
        [
            _row(_ms(now - timedelta(days=1)), "app_open", "a", "s1"),
            _row(_ms(now - timedelta(days=3)), "app_open", "a", "s2"),
            _row(_ms(now - timedelta(days=2)), "app_open", "b", "s3"),
            _row(_ms(now - timedelta(days=20)), "app_open", "c", "s4"),
        ]
    )
    body = client.get("/api/admin/telemetry/summary", headers=admin_headers).json()
    assert body["users_7d"] == 2


def test_summary_days_validated(client, admin_headers):
    r = client.get("/api/admin/telemetry/summary?days=0", headers=admin_headers)
    assert r.status_code == 422
