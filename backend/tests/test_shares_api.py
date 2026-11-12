"""Share links 2.0: /api/shares, the public fallback and the privacy options."""

import uuid

import pytest

from app.core.auth import create_access_token
from app.core.config import settings
from app.db import users_db
from app.db.users_db import create_user

_PW = "correct-horse-battery"
HOSTILE = '<script>alert("x")</script> & "q"'


@pytest.fixture(autouse=True)
def _on(monkeypatch):
    monkeypatch.setattr(settings, "sharing_v2_enabled", True)
    monkeypatch.setattr(users_db, "_hash", lambda pw: f"plain:{pw}")


def _user(display_name=None):
    name = f"shr_{uuid.uuid4().hex[:10]}"
    u = create_user(name, _PW, email=f"{name}@example.com", display_name=display_name)
    return u, {"Authorization": f"Bearer {create_access_token({'sub': name})}"}


def _plan(client, h, name="Lisbon", **extra):
    search = {
        "origin": "NYC",
        "destination": "Lisbon",
        "departure_date": "2026-04-01",
        "return_date": "2026-04-07",
        "nationality": "American",
        **extra,
    }
    r = client.post(
        "/api/plans",
        json={
            "name": name,
            "search_data": search,
            "selections": {"activities": [{"name": "Tram 28"}]},
        },
        headers=h,
    )
    assert r.status_code == 200, r.text
    return r.json()


def _share(client, h, plan_id, **opts):
    r = client.post(
        "/api/shares",
        json={"kind": "plan", "plan_id": plan_id, "options": opts},
        headers=h,
    )
    assert r.status_code == 200, r.text
    return r.json()


def test_create_list_revoke(client):
    _, h = _user()
    plan = _plan(client, h)
    s = _share(client, h, plan["id"])
    assert s["kind"] == "plan"
    assert s["options"] == {"dates": "hidden", "show_origin": False, "show_name": False}
    assert s["url"].endswith(f"/share/{s['token']}")
    assert s["card_url"]["link"].endswith(f"/api/share/{s['token']}/card.png?size=link")
    assert s["card_url"]["story"].endswith("size=story")
    lst = client.get("/api/shares", headers=h).json()["shares"]
    assert [x["token"] for x in lst] == [s["token"]]
    assert lst[0]["title"] == "Lisbon"
    assert client.get(f"/api/share/{s['token']}").status_code == 200
    assert client.delete(f"/api/shares/{s['token']}", headers=h).status_code == 204
    assert client.get(f"/api/share/{s['token']}").status_code == 404
    assert client.get("/api/shares", headers=h).json()["shares"] == []


def test_idempotent_and_updates_options(client):
    _, h = _user()
    plan = _plan(client, h)
    a = _share(client, h, plan["id"])
    b = _share(client, h, plan["id"], dates="exact")
    assert a["token"] == b["token"]
    assert b["options"]["dates"] == "exact"
    assert len(client.get("/api/shares", headers=h).json()["shares"]) == 1


def test_not_yours_and_validation(client):
    _, h1 = _user()
    _, h2 = _user()
    plan = _plan(client, h1)
    r = client.post(
        "/api/shares", json={"kind": "plan", "plan_id": plan["id"]}, headers=h2
    )
    assert r.status_code == 404 and r.json()["error_code"] == "plan_not_found"
    r = client.post("/api/shares", json={"kind": "plan"}, headers=h1)
    assert r.status_code == 404
    r = client.post("/api/shares", json={"kind": "quiz"}, headers=h1)
    assert r.status_code == 422 and r.json()["error_code"] == "invalid_kind"
    token = _share(client, h1, plan["id"])["token"]
    r = client.delete(f"/api/shares/{token}", headers=h2)
    assert r.status_code == 404 and r.json()["error_code"] == "share_not_found"
    assert client.get(f"/api/share/{token}").status_code == 200
    assert client.get("/api/shares").status_code in (401, 403)


def test_flag_off(client, monkeypatch):
    _, h = _user()
    plan = _plan(client, h)
    token = _share(client, h, plan["id"])["token"]
    monkeypatch.setattr(settings, "sharing_v2_enabled", False)
    r = client.post("/api/shares", json={"kind": "savings"}, headers=h)
    assert r.status_code == 404 and r.json()["error_code"] == "sharing_disabled"
    assert client.get("/api/shares", headers=h).status_code == 404
    assert client.delete(f"/api/shares/{token}", headers=h).status_code == 404
    assert client.get(f"/api/share/{token}").status_code == 404
    assert client.get("/api/config").json()["features"]["sharing"] == 0
    monkeypatch.setattr(settings, "sharing_v2_enabled", True)
    assert client.get("/api/config").json()["features"]["sharing"] == 1


def test_default_privacy(client):
    _, h = _user(display_name="Ann")
    plan = _plan(client, h, email="x@y.z", existing_visas=["v"])
    token = _share(client, h, plan["id"])["token"]
    body = client.get(f"/api/share/{token}").json()
    assert body["kind"] == "plan"
    sd = body["search_data"]
    assert "departure_date" not in sd and "return_date" not in sd
    assert "origin" not in sd and "nationality" not in sd
    assert "owner_name" not in body
    assert body["selections"]["activities"][0]["name"] == "Tram 28"
    text = client.get(f"/api/share/{token}").text
    assert "@example.com" not in text and "Ann" not in text


def test_options_exact_origin_name(client):
    _, h = _user(display_name="Ann")
    plan = _plan(client, h)
    token = _share(
        client, h, plan["id"], dates="exact", show_origin=True, show_name=True
    )["token"]
    body = client.get(f"/api/share/{token}").json()
    assert body["search_data"]["departure_date"] == "2026-04-01"
    assert body["search_data"]["origin"] == "NYC"
    assert body["owner_name"] == "Ann"
    assert "nationality" not in body["search_data"]
    assert "@" not in body["owner_name"]


def test_show_name_falls_back_to_username_never_email(client):
    u, h = _user()
    plan = _plan(client, h)
    token = _share(client, h, plan["id"], show_name=True)["token"]
    body = client.get(f"/api/share/{token}").json()
    assert body["owner_name"] == u["username"]
    assert u["email"] not in client.get(f"/api/share/{token}").text


def test_month_dates(client):
    _, h = _user()
    plan = _plan(client, h)
    token = _share(client, h, plan["id"], dates="month")["token"]
    sd = client.get(f"/api/share/{token}").json()["search_data"]
    assert sd["departure_date"] == "2026-04"


def test_legacy_token_unchanged(client):
    _, h = _user(display_name="Ann")
    plan = _plan(client, h)
    r = client.post(f"/api/plans/{plan['id']}/share", headers=h)
    assert r.status_code == 200
    token = r.json()["share_token"]
    body = client.get(f"/api/share/{token}").json()
    assert set(body) == {
        "name",
        "created_at",
        "updated_at",
        "search_data",
        "selections",
    }
    assert body["search_data"]["departure_date"] == "2026-04-01"
    assert body["search_data"]["origin"] == "NYC"
    assert client.delete(f"/api/plans/{plan['id']}/share", headers=h).status_code == 200
    assert client.get(f"/api/share/{token}").status_code == 404


def test_hostile_names_json_safe(client):
    _, h = _user(display_name=HOSTILE)
    plan = _plan(client, h, name=HOSTILE)
    token = _share(client, h, plan["id"], show_name=True)["token"]
    body = client.get(f"/api/share/{token}").json()
    assert body["name"] == HOSTILE and body["owner_name"] == HOSTILE
    lst = client.get("/api/shares", headers=h).json()["shares"]
    assert lst[0]["title"] == HOSTILE


def test_recap_and_savings(client):
    _, h = _user()
    plan = _plan(client, h)
    r = client.post(
        "/api/shares", json={"kind": "recap", "plan_id": plan["id"]}, headers=h
    )
    token = r.json()["token"]
    body = client.get(f"/api/share/{token}").json()
    assert body["kind"] == "recap"
    assert body["card"]["headline"] == "My trip to Lisbon: recap"
    assert "period" not in body["card"]
    r = client.post("/api/shares", json={"kind": "savings"}, headers=h)
    assert r.status_code == 200
    again = client.post("/api/shares", json={"kind": "savings"}, headers=h).json()
    assert again["token"] == r.json()["token"]
    sb = client.get(f"/api/share/{r.json()['token']}").json()
    assert sb["kind"] == "savings" and sb["card"]["stats"][0]["key"] == "drops_caught"
    assert sb["selections"] == {}


def test_plan_delete_revokes_share(client):
    _, h = _user()
    plan = _plan(client, h)
    token = _share(client, h, plan["id"])["token"]
    assert client.delete(f"/api/plans/{plan['id']}", headers=h).status_code == 200
    assert client.get(f"/api/share/{token}").status_code == 404


def test_rate_limits(client, monkeypatch):
    from app.core import rate_limit

    _, h = _user()
    plan = _plan(client, h)
    token = _share(client, h, plan["id"])["token"]
    monkeypatch.setattr(settings, "rate_limit_enabled", True)
    monkeypatch.setattr(settings, "rate_limit_share_public", 2)
    monkeypatch.setattr(settings, "rate_limit_share_manage", 1)
    rate_limit.limiter = rate_limit.SlidingWindowLimiter()
    try:
        codes = [client.get(f"/api/share/{token}").status_code for _ in range(3)]
        assert codes == [200, 200, 429]
        assert client.get("/api/shares", headers=h).status_code == 200
        r = client.get("/api/shares", headers=h)
        assert r.status_code == 429 and "Retry-After" in r.headers
    finally:
        rate_limit.limiter = rate_limit.SlidingWindowLimiter()
