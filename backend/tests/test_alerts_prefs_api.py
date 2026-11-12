import uuid

import pytest

from app.core.auth import create_access_token
from app.db import alerts_db, user_settings_db
from app.db.users_db import create_user


@pytest.fixture(autouse=True)
def _fast(monkeypatch, client):
    monkeypatch.setattr("app.db.users_db._hash", lambda pw: "unused")
    alerts_db.create_alert_tables()


def _user():
    u = create_user(f"pf-{uuid.uuid4().hex[:8]}", "pw-123456789")
    return u, {"Authorization": f"Bearer {create_access_token({'sub': u['username']})}"}


def test_prefs_requires_auth(client):
    assert client.get("/api/alerts/preferences").status_code == 401


def test_prefs_put_partial_and_422(client):
    _, h = _user()
    r = client.get("/api/alerts/preferences", headers=h).json()
    assert r["digest_push"] is False and r["quiet_hours_active"] is False
    r = client.put(
        "/api/alerts/preferences",
        headers=h,
        json={"daily_cap": {"hotel": 5}, "quiet_hours": {"start": "23:00"}},
    ).json()
    assert r["daily_cap"] == {"flight": 3, "hotel": 5, "activity": 3, "trip": 3}
    assert r["quiet_hours"] == {"enabled": True, "start": "23:00", "end": "07:00"}
    assert (
        client.get("/api/alerts/preferences", headers=h).json()["daily_cap"]["hotel"]
        == 5
    )
    bad = client.put("/api/alerts/preferences", headers=h, json={"digest_day": 9})
    assert bad.status_code == 422 and bad.json()["error_code"] == "alert_prefs_invalid"


def test_prefs_timezone_mirrored_read_only(client):
    u, h = _user()
    user_settings_db.patch_settings(u["id"], {"timezone": "Asia/Kolkata"})
    r = client.put(
        "/api/alerts/preferences",
        headers=h,
        json={"timezone": "UTC", "digest_push": True},
    ).json()
    assert r["timezone"] == "Asia/Kolkata" and r["quiet_hours_active"] is True
    assert r["digest_push"] is True
    off = client.put(
        "/api/alerts/preferences", headers=h, json={"quiet_hours": {"enabled": False}}
    ).json()
    assert off["quiet_hours_active"] is False
