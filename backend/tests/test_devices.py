"""Device registry for push notifications: register (upsert / move between
users), list (masked tokens, ids), delete by id (owner only), unregister by
token (sign-out) and the per-user cap. A token never travels in a URL."""

import uuid

import pytest

from app.core.auth import create_access_token
from app.db import devices_db
from app.db.users_db import create_user


@pytest.fixture(autouse=True)
def _fast_users(monkeypatch, client):
    # tokens are minted directly — skip bcrypt's deliberate slowness
    monkeypatch.setattr("app.db.users_db._hash", lambda pw: "unused")


def _user():
    u = create_user(f"dev-{uuid.uuid4().hex[:8]}", "pw-123456789")
    token = create_access_token({"sub": u["username"]})
    return u, {"Authorization": f"Bearer {token}"}


def _token() -> str:
    return f"fcm:{uuid.uuid4().hex}{uuid.uuid4().hex}"


def _register(client, headers, token, **over):
    body = {"token": token, "platform": "android", **over}
    return client.post("/api/devices", json=body, headers=headers)


def test_devices_require_auth(client):
    assert client.post("/api/devices", json={"token": "t"}).status_code == 401
    assert client.get("/api/devices").status_code == 401
    assert client.delete("/api/devices/1").status_code == 401
    assert (
        client.post("/api/devices/unregister", json={"token": "t"}).status_code == 401
    )


def test_register_and_list_masks_the_token(client):
    _, h = _user()
    tok = _token()
    r = _register(client, h, tok, locale="de-DE")
    assert r.status_code == 200
    body = r.json()
    assert isinstance(body["id"], int)
    assert body["token"] == "…" + tok[-6:]
    assert body["platform"] == "android"
    assert body["locale"] == "de-DE"
    assert body["created_at"] and body["last_seen_at"]

    items = client.get("/api/devices", headers=h).json()["items"]
    assert [d["token"] for d in items] == ["…" + tok[-6:]]
    assert items[0]["id"] == body["id"]
    assert tok not in str(items)


def test_reregistering_updates_the_row(client):
    u, h = _user()
    tok = _token()
    _register(client, h, tok, locale="en-GB")
    _register(client, h, tok, locale="fr-FR")
    items = client.get("/api/devices", headers=h).json()["items"]
    assert len(items) == 1
    assert items[0]["locale"] == "fr-FR"
    assert devices_db.tokens_for(u["username"]) == [tok]


def test_a_token_moves_to_the_user_who_registers_it(client):
    alice, ha = _user()
    bob, hb = _user()
    tok = _token()
    _register(client, ha, tok)
    _register(client, hb, tok)
    assert devices_db.tokens_for(alice["username"]) == []
    assert devices_db.tokens_for(bob["username"]) == [tok]


def test_delete_by_id_only_the_callers_device(client):
    alice, ha = _user()
    _, hb = _user()
    tok = _token()
    dev = _register(client, ha, tok).json()
    assert client.delete(f"/api/devices/{dev['id']}", headers=hb).status_code == 404
    assert devices_db.tokens_for(alice["username"]) == [tok]
    assert client.delete(f"/api/devices/{dev['id']}", headers=ha).status_code == 204
    assert devices_db.tokens_for(alice["username"]) == []
    assert client.delete(f"/api/devices/{dev['id']}", headers=ha).status_code == 404


def test_delete_needs_a_numeric_id(client):
    _, h = _user()
    assert client.delete("/api/devices/fcm:abc", headers=h).status_code == 422


def test_unregister_by_token_is_idempotent_and_owner_only(client):
    alice, ha = _user()
    _, hb = _user()
    tok = _token()
    _register(client, ha, tok)
    body = {"token": tok}
    # someone else's token: nothing changes, same answer
    assert (
        client.post("/api/devices/unregister", json=body, headers=hb).status_code == 204
    )
    assert devices_db.tokens_for(alice["username"]) == [tok]
    assert (
        client.post("/api/devices/unregister", json=body, headers=ha).status_code == 204
    )
    assert devices_db.tokens_for(alice["username"]) == []
    assert (
        client.post("/api/devices/unregister", json=body, headers=ha).status_code == 204
    )


def test_no_route_takes_a_token_in_the_path(client):
    from app.main import app

    paths = {getattr(r, "path", "") for r in app.routes}
    assert not any("{token}" in p for p in paths if p.startswith("/api/devices"))


def test_cap_evicts_the_oldest_device(client):
    u, h = _user()
    tokens = [_token() for _ in range(devices_db.MAX_DEVICES_PER_USER + 1)]
    for tok in tokens:
        assert _register(client, h, tok).status_code == 200
    kept = devices_db.tokens_for(u["username"])
    assert len(kept) == devices_db.MAX_DEVICES_PER_USER
    assert tokens[0] not in kept
    assert tokens[-1] in kept


@pytest.mark.parametrize(
    "body",
    [
        {"token": "", "platform": "android"},
        {"token": "x" * 4097, "platform": "android"},
        {"token": "abc", "platform": "web"},
        {"platform": "android"},
    ],
)
def test_register_validation(client, body):
    _, h = _user()
    assert client.post("/api/devices", json=body, headers=h).status_code == 422


def test_platform_defaults_to_android(client):
    u, h = _user()
    tok = _token()
    r = client.post("/api/devices", json={"token": tok}, headers=h)
    assert r.status_code == 200
    assert r.json()["platform"] == "android"
