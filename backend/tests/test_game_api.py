import json
import uuid
from datetime import UTC, datetime

from app.core.config import settings
from app.db import users_db
from app.db.database import get_connection
from app.game import engine


def _login(client):
    name = f"ga{uuid.uuid4().hex[:8]}"
    u = users_db.create_user(name, "pw-long-enough-1", is_first_login=False)
    r = client.post(
        "/api/auth/login", json={"username": name, "password": "pw-long-enough-1"}
    )
    return u["id"], {"Authorization": f"Bearer {r.json()['access_token']}"}


def test_me_shape(client):
    uid, h = _login(client)
    engine.award(uid, "email_verified", "x")
    r = client.get("/api/game/me", headers=h)
    assert r.status_code == 200
    d = r.json()
    assert set(d) == {
        "xp", "level", "level_min_xp", "next_level_xp", "badges", "streaks", "recent", "hidden",
    }  # fmt: skip
    assert d["xp"] == 50 and d["hidden"] is False
    assert d["streaks"]["daily"]["current"] == 0
    assert d["recent"][0]["rule"] == "email_verified"


def test_me_hidden_from_settings(client):
    uid, h = _login(client)
    with get_connection() as c:
        c.execute(
            "INSERT INTO user_settings (user_id, data, updated_at) VALUES (?, ?, ?)",
            (uid, json.dumps({"hide_game": True}), datetime.now(UTC).isoformat()),
        )
    assert client.get("/api/game/me", headers=h).json()["hidden"] is True


def test_me_requires_auth(client):
    assert client.get("/api/game/me").status_code in (401, 403)


def test_catalog(client):
    r = client.get("/api/game/catalog")
    assert r.status_code == 200
    assert r.headers["cache-control"] == "max-age=300"
    d = r.json()
    assert d["version"] == 1 and len(d["levels"]) == 10
    assert {"verified", "first_steps", "traveller", "memory_keeper"} <= {
        b["id"] for b in d["badges"]
    }


def test_404_when_disabled(client, monkeypatch):
    _, h = _login(client)
    monkeypatch.setattr(settings, "game_enabled", False)
    assert client.get("/api/game/me", headers=h).status_code == 404
    assert client.get("/api/game/catalog").status_code == 404
