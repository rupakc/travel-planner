import re
import threading
import uuid
from datetime import UTC, datetime, timedelta

import pytest

from app.core.auth import create_access_token
from app.db import invites_db
from app.db.database import get_connection
from app.db.users_db import create_user


@pytest.fixture(autouse=True)
def _app(client):
    return client


def test_create_and_consume():
    inv = invites_db.create_invite("admin", 2, 14, "n")
    assert re.fullmatch(r"VOY-[A-HJKMNP-Z2-9]{4}-[A-HJKMNP-Z2-9]{4}", inv["code"])
    assert inv["code_prefix"] == inv["code"][:8]
    assert invites_db.check_invite(inv["code"]) == inv["id"]
    assert invites_db.consume_invite(inv["code"]) == inv["id"]
    row = [r for r in invites_db.list_invites() if r["id"] == inv["id"]][0]
    assert row["uses"] == 1
    assert "code" not in row and "code_hash" not in row
    assert invites_db.consume_invite(inv["code"]) == inv["id"]
    assert invites_db.consume_invite(inv["code"]) is None
    assert invites_db.check_invite(inv["code"]) is None


def test_last_use_cannot_be_redeemed_twice():
    inv = invites_db.create_invite("admin", 1, 14, None)
    results = []
    barrier = threading.Barrier(8)

    def go():
        barrier.wait()
        results.append(invites_db.consume_invite(inv["code"]))

    ts = [threading.Thread(target=go) for _ in range(8)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert sorted(r for r in results if r is not None) == [inv["id"]]


def test_expired_and_revoked():
    a = invites_db.create_invite("admin", 1, 1, None)
    past = (datetime.now(UTC) - timedelta(days=1)).isoformat()
    with get_connection() as c:
        c.execute("UPDATE invite_codes SET expires_at=? WHERE id=?", (past, a["id"]))
    assert invites_db.consume_invite(a["code"]) is None
    b = invites_db.create_invite("admin", 1, 14, None)
    assert invites_db.revoke_invite(b["id"]) is True
    assert invites_db.consume_invite(b["code"]) is None
    assert invites_db.revoke_invite(999999) is False


def test_normalisation_and_hash_only():
    inv = invites_db.create_invite("admin", 1, 14, None)
    g = inv["code"].split("-")
    messy = f"voy {g[1].lower()} {g[2].lower()}"
    assert invites_db.check_invite(messy) == inv["id"]
    with get_connection() as c:
        stored = c.execute(
            "SELECT code_hash FROM invite_codes WHERE id=?", (inv["id"],)
        ).fetchone()[0]
    assert stored != inv["code"] and len(stored) == 64
    assert invites_db.consume_invite(messy) == inv["id"]
    assert invites_db.check_invite("") is None


@pytest.fixture
def user_headers(monkeypatch):
    monkeypatch.setattr("app.db.users_db._hash", lambda pw: "unused")
    u = create_user(f"inv-{uuid.uuid4().hex[:8]}", "pw-123456789")
    return {"Authorization": f"Bearer {create_access_token({'sub': u['username']})}"}


def test_admin_only(client, user_headers):
    assert client.post("/api/admin/invites", json={}).status_code == 401
    assert (
        client.post("/api/admin/invites", json={}, headers=user_headers).status_code
        == 403
    )
    assert client.get("/api/admin/invites", headers=user_headers).status_code == 403
    assert (
        client.delete("/api/admin/invites/1", headers=user_headers).status_code == 403
    )


def test_routes(client, admin_headers):
    r = client.post(
        "/api/admin/invites", json={"max_uses": 3, "note": "hi"}, headers=admin_headers
    )
    assert r.status_code == 201
    body = r.json()
    assert body["max_uses"] == 3 and body["uses"] == 0 and body["note"] == "hi"
    assert re.fullmatch(r"VOY-\w{4}-\w{4}", body["code"])
    lst = client.get("/api/admin/invites", headers=admin_headers)
    assert lst.status_code == 200
    assert body["code"] not in lst.text
    assert any(i["id"] == body["id"] for i in lst.json())
    assert (
        client.delete(
            f"/api/admin/invites/{body['id']}", headers=admin_headers
        ).status_code
        == 204
    )
    assert (
        client.delete("/api/admin/invites/999999", headers=admin_headers).status_code
        == 404
    )
    for bad in (
        {"max_uses": 0},
        {"max_uses": 1001},
        {"expires_in_days": 366},
        {"note": "x" * 81},
    ):
        assert (
            client.post(
                "/api/admin/invites", json=bad, headers=admin_headers
            ).status_code
            == 422
        )
