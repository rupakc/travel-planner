"""I-2: the Phase 1 account routes and the chat daily-quota check never run
blocking SQLite or bcrypt on the event loop (one uvicorn worker serves every
SSE stream). Each spy records whether it was called with a running loop in
its thread, which is true only on the loop itself."""

import asyncio
import json
import uuid
from types import SimpleNamespace

import pytest

from app.agents.chat_agent import ChatAgent
from app.core import ai_quota
from app.core.auth import create_access_token
from app.core.errors import ApiError
from app.db import user_settings_db, users_db
from app.services import account_data
from app.services import avatar as avatar_svc

_PW = "correct-horse-battery"


def _on_loop() -> bool:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return False
    return True


def _spy(monkeypatch, owner, name, calls):
    real = getattr(owner, name)

    def wrapper(*args, **kwargs):
        calls.append((name, _on_loop()))
        return real(*args, **kwargs)

    monkeypatch.setattr(owner, name, wrapper)


@pytest.fixture(autouse=True)
def _cheap_hash(client, monkeypatch):
    monkeypatch.setattr(users_db, "_hash", lambda pw: f"plain:{pw}")
    monkeypatch.setattr(users_db, "_verify", lambda pw, h: h == f"plain:{pw}")


def _user():
    name = f"l{uuid.uuid4().hex[:10]}"
    u = users_db.create_user(
        name, _PW, email=f"{name}@example.com", is_first_login=False
    )
    tok = create_access_token({"sub": name, "uid": u["id"]})
    return u, {"Authorization": f"Bearer {tok}"}


def test_account_routes_run_off_the_loop(client, monkeypatch):
    calls: list = []
    for name in ("get_settings", "patch_settings", "get_onboarding", "put_onboarding"):
        _spy(monkeypatch, user_settings_db, name, calls)
    _spy(monkeypatch, users_db, "set_display_name", calls)
    _spy(monkeypatch, account_data, "export_user", calls)
    _spy(monkeypatch, avatar_svc, "remove_avatar", calls)
    _, h = _user()
    assert client.get("/api/account", headers=h).status_code == 200
    assert client.get("/api/account/settings", headers=h).status_code == 200
    r = client.patch("/api/account/settings", json={"units": "imperial"}, headers=h)
    assert r.status_code == 200
    r = client.patch("/api/account", json={"display_name": "Lo"}, headers=h)
    assert r.status_code == 200
    r = client.put(
        "/api/account/onboarding", json={"step": 1, "done": False}, headers=h
    )
    assert r.status_code == 200
    assert client.get("/api/account/export", headers=h).status_code == 200
    assert client.delete("/api/account/avatar", headers=h).status_code == 200
    r = client.delete("/api/account/identities/github", headers=h)
    assert r.status_code == 404
    names = {n for n, _ in calls}
    assert {"get_settings", "patch_settings", "put_onboarding", "set_display_name",
            "export_user", "remove_avatar"} <= names  # fmt: skip
    assert [c for c in calls if c[1]] == []


def test_delete_account_runs_bcrypt_and_sqlite_off_the_loop(client, monkeypatch):
    calls: list = []
    _spy(monkeypatch, users_db, "authenticate_user", calls)
    _spy(monkeypatch, users_db, "count_active_admins", calls)
    _spy(monkeypatch, account_data, "delete_rows", calls)
    u, h = _user()
    r = client.request(
        "DELETE", "/api/account", json={"password": "wrong-pw"}, headers=h
    )
    assert r.status_code == 403
    r = client.request("DELETE", "/api/account", json={"password": _PW}, headers=h)
    assert r.status_code == 204
    assert users_db.get_user_by_id(u["id"]) is None
    assert {n for n, _ in calls} >= {"authenticate_user", "delete_rows"}
    assert [c for c in calls if c[1]] == []


def test_chat_full_plan_quota_check_runs_off_the_loop(monkeypatch):
    calls: list = []

    def over(bucket, key, user):
        calls.append(("consume_key", _on_loop()))
        raise ApiError(429, "ai_daily_quota", "Over today's allowance.")

    monkeypatch.setattr(ai_quota, "consume_key", over)
    u, _ = _user()
    agent = ChatAgent.__new__(ChatAgent)
    agent._rate_limit_key = f"user:{u['username']}"
    request = SimpleNamespace(
        destination="Lisbon", destinations=None, departure_date=None, return_date=None
    )

    async def run():
        gen = agent._run_comprehensive_planning(request, [], None)
        return [json.loads(chunk) async for chunk in gen]

    out = asyncio.run(run())
    assert out == [{"type": "delta", "text": "Over today's allowance."},
                   {"type": "done"}]  # fmt: skip
    assert calls == [("consume_key", False)]
