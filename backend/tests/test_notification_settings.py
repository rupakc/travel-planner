import uuid

import pytest

from app.core.auth import create_access_token
from app.db import alerts_db, devices_db, notify_db, user_settings_db
from app.db.users_db import create_user
from app.services import notify_text


@pytest.fixture(autouse=True)
def _tables(monkeypatch, client):
    monkeypatch.setattr("app.db.users_db._hash", lambda pw: "unused")
    alerts_db.create_alert_tables()
    notify_db.create_notify_tables()


def _user():
    u = create_user(f"ns-{uuid.uuid4().hex[:8]}", "pw-123456789")
    return u, {"Authorization": f"Bearer {create_access_token({'sub': u['username']})}"}


CATS = {"price_drops", "trip_reminders", "morning_brief", "weather", "nearby", "social", "quiz"}


def test_requires_auth(client):
    assert client.get("/api/notification-settings").status_code == 401
    assert client.put("/api/notification-settings", json={}).status_code == 401
    assert client.get("/api/notifications/catalog").status_code == 401


def test_defaults(client):
    _, h = _user()
    body = client.get("/api/notification-settings", headers=h).json()
    assert set(body["categories"]) == CATS
    assert all(c == {"enabled": True} for c in body["categories"].values())
    assert body["daily_cap"] == 3
    assert body["quiet_hours"] == {"enabled": True, "start": "22:00", "end": "07:00"}
    assert body["timezone"] is None and body["quiet_hours_active"] is False
    assert body["push"] == {"fcm": False, "apns": False}
    assert body["devices"] == 0


def test_partial_put_and_isolation(client):
    _, h = _user()
    _, h2 = _user()
    r = client.put(
        "/api/notification-settings",
        json={"categories": {"weather": {"enabled": False}}, "daily_cap": 5},
        headers=h,
    )
    assert r.status_code == 200
    b = r.json()
    assert b["categories"]["weather"]["enabled"] is False
    assert b["categories"]["price_drops"]["enabled"] is True and b["daily_cap"] == 5
    again = client.put(
        "/api/notification-settings",
        json={"categories": {"nearby": {"enabled": False}}},
        headers=h,
    ).json()
    assert again["categories"]["weather"]["enabled"] is False and again["daily_cap"] == 5
    other = client.get("/api/notification-settings", headers=h2).json()
    assert other["categories"]["weather"]["enabled"] is True and other["daily_cap"] == 3


@pytest.mark.parametrize(
    "body",
    [
        {"categories": {"bogus": {"enabled": True}}},
        {"categories": {"weather": {"enabled": "yes"}}},
        {"categories": {"weather": True}},
        {"daily_cap": 0},
        {"daily_cap": 11},
        {"daily_cap": True},
        {"quiet_hours": {"start": "25:00"}},
        {"mystery": 1},
    ],
)
def test_invalid(client, body):
    _, h = _user()
    r = client.put("/api/notification-settings", json=body, headers=h)
    assert r.status_code == 422 and r.json()["error_code"] == "notification_settings_invalid"


def test_read_only_ignored(client):
    _, h = _user()
    r = client.put(
        "/api/notification-settings",
        json={"timezone": "X", "devices": 9, "push": {"fcm": True}, "quiet_hours_active": True},
        headers=h,
    )
    assert r.status_code == 200 and r.json()["devices"] == 0


def test_quiet_hours_shared_with_alert_prefs(client):
    u, h = _user()
    user_settings_db.patch_settings(u["id"], {"timezone": "Asia/Kolkata"})
    r = client.put(
        "/api/notification-settings",
        json={"quiet_hours": {"start": "21:30", "enabled": True}},
        headers=h,
    )
    assert r.json()["quiet_hours"] == {"enabled": True, "start": "21:30", "end": "07:00"}
    assert r.json()["timezone"] == "Asia/Kolkata"
    assert client.get("/api/alerts/preferences", headers=h).json()["quiet_hours"]["start"] == "21:30"
    client.put("/api/alerts/preferences", json={"quiet_hours": {"end": "06:00"}}, headers=h)
    assert client.get("/api/notification-settings", headers=h).json()["quiet_hours"]["end"] == "06:00"


def test_devices_count(client):
    u, h = _user()
    devices_db.upsert_device(u["username"], "tok-123456", "android", None, now=__import__("datetime").datetime.utcnow())
    assert client.get("/api/notification-settings", headers=h).json()["devices"] == 1


def test_catalog(client):
    _, h = _user()
    b = client.get("/api/notifications/catalog?locale=xx", headers=h).json()
    assert b["locale"] == "en"
    for k in ("trip_t30", "trip_t7", "trip_t1", "trip_morning", "nearby_arrival"):
        assert k in b["templates"]
    assert notify_text.render("trip_t7", "en", destination="Lisbon").count("Lisbon") == 1
    assert notify_text.render("nearby_arrival", "en", place="A", item="B", minutes=4) == (
        "You're near A: B is 4 min away"
    )


def test_config_features(client):
    f = client.get("/api/config").json()["features"]
    assert f["notifications_api"] == 1
    assert f["notifications_v2"] is False and f["apns"] is False
