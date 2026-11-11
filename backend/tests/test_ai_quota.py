"""Verified-only AI access and per-user daily quotas."""

import json
import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import pytest

from app.agents.chat_agent import ChatAgent
from app.core import ai_quota
from app.core.auth import create_access_token
from app.core.config import settings
from app.core.rate_limit import limiter
from app.db import users_db

_TRIP = {
    "origin": "New York",
    "destination": "Tokyo, Japan",
    "departure_date": "2026-09-01",
    "return_date": "2026-09-08",
    "nationality": "American",
}


@pytest.fixture(autouse=True)
def quotas(monkeypatch):
    monkeypatch.setattr(settings, "ai_daily_quota_enabled", True)
    monkeypatch.setattr(settings, "ai_daily_quota_light_ai", 3)
    monkeypatch.setattr(settings, "ai_daily_quota_search", 20)


def _make(signup_method, verified=False, admin=False):
    name = f"q{uuid.uuid4().hex[:10]}"
    user = users_db.create_user(
        name,
        "pw-long-enough-123",
        email=f"{name}@example.com",
        is_admin=admin,
        signup_method=signup_method,
        is_first_login=False,
    )
    if verified:
        users_db.mark_email_verified(user["id"], user["email"])
    headers = {"Authorization": f"Bearer {create_access_token({'sub': name})}"}
    return users_db.get_user_by_username(name), headers


def _visa(client, n, headers=None):
    with patch("app.api.routes.visa.VisaAgent") as cls:
        cls.return_value.run = AsyncMock(return_value={"requirement": {}})
        return [client.post("/api/visa", json=_TRIP, headers=headers) for _ in range(n)]


def _at(hour_day):
    return (
        datetime(2026, 11, 11, 18, 30, 0, tzinfo=UTC)
        if hour_day == 1
        else (datetime(2026, 11, 12, 0, 0, 5, tzinfo=UTC))
    )


def test_daily_limit_429_with_retry_after_until_utc_midnight(client, monkeypatch):
    _, headers = _make("admin")
    monkeypatch.setattr(ai_quota, "_now", lambda: _at(1))
    codes = [r.status_code for r in _visa(client, 4, headers)]
    assert codes == [200, 200, 200, 429]
    r = _visa(client, 1, headers)[0]
    body = r.json()
    assert body["error_code"] == "ai_daily_quota"
    assert body["bucket"] == "light_ai"
    assert body["resets_at"] == "2026-11-12T00:00:00Z"
    assert "quick AI tools" in body["detail"]
    assert r.headers["Retry-After"] == str(5 * 3600 + 30 * 60)


def test_next_utc_day_is_allowed(client, monkeypatch):
    _, headers = _make("admin")
    monkeypatch.setattr(ai_quota, "_now", lambda: _at(1))
    assert _visa(client, 4, headers)[-1].status_code == 429
    monkeypatch.setattr(ai_quota, "_now", lambda: _at(2))
    assert _visa(client, 1, headers)[0].status_code == 200


def test_search_21st_of_the_day_is_refused(monkeypatch):
    user, _ = _make("admin")
    for _i in range(20):
        ai_quota.consume_key("search", f"user:{user['id']}", user, _at(1))
    with pytest.raises(Exception) as exc:
        ai_quota.consume_key("search", f"user:{user['id']}", user, _at(1))
    assert exc.value.status == 429
    assert exc.value.extra["bucket"] == "search"
    assert "searches" in exc.value.detail


def test_window_refusal_does_not_burn_daily_quota(client, monkeypatch):
    user, headers = _make("admin")
    monkeypatch.setattr(settings, "rate_limit_enabled", True)
    monkeypatch.setattr(settings, "rate_limit_light_ai", 1)
    limiter._hits.clear()
    codes = [r.status_code for r in _visa(client, 3, headers)]
    assert codes == [200, 429, 429]
    used = ai_quota.usage(user)["buckets"]["light_ai"]["used"]
    assert used == 1
    limiter._hits.clear()


def test_admin_is_never_limited(client):
    _, headers = _make("admin", admin=True)
    assert all(r.status_code == 200 for r in _visa(client, 6, headers))


def test_limit_zero_and_disabled_skip(client, monkeypatch):
    _, headers = _make("admin")
    monkeypatch.setattr(settings, "ai_daily_quota_light_ai", 0)
    assert all(r.status_code == 200 for r in _visa(client, 5, headers))
    monkeypatch.setattr(settings, "ai_daily_quota_light_ai", 1)
    monkeypatch.setattr(settings, "ai_daily_quota_enabled", False)
    assert all(r.status_code == 200 for r in _visa(client, 3, headers))


def test_unverified_oauth_user_gets_403(client):
    _, headers = _make("google", verified=False)
    r = client.post("/api/search", json=_TRIP, headers=headers)
    assert r.status_code == 403
    assert r.json()["error_code"] == "email_unverified"
    assert r.json()["detail"] == "Confirm your email to use the AI planner."


def test_verified_oauth_user_is_allowed(client):
    _, headers = _make("google", verified=True)
    assert _visa(client, 1, headers)[0].status_code == 200


def test_admin_created_unverified_user_is_allowed(client):
    user, headers = _make("admin", verified=False)
    assert not user["email_verified"]
    assert _visa(client, 1, headers)[0].status_code == 200


def test_quota_endpoint_shape(client, monkeypatch):
    user, headers = _make("admin")
    monkeypatch.setattr(ai_quota, "_now", lambda: _at(1))
    _visa(client, 2, headers)
    body = client.get("/api/account/quota", headers=headers).json()
    assert body["day"] == "2026-11-11"
    assert body["resets_at"] == "2026-11-12T00:00:00Z"
    assert set(body["buckets"]) == {
        "search",
        "chat",
        "compare",
        "discover",
        "light_ai",
        "import",
    }
    assert body["buckets"]["light_ai"] == {"used": 2, "limit": 3}
    assert body["buckets"]["search"] == {"used": 0, "limit": 20}


def test_quota_endpoint_unlimited_for_admin_and_needs_auth(client, admin_headers):
    body = client.get("/api/account/quota", headers=admin_headers).json()
    assert all(b["limit"] is None for b in body["buckets"].values())
    assert client.get("/api/account/quota").status_code in (401, 403)


def test_chat_full_plan_over_quota_refuses_in_stream(monkeypatch):
    user, _ = _make("admin")
    monkeypatch.setattr(settings, "ai_daily_quota_search", 1)
    agent = ChatAgent.__new__(ChatAgent)
    agent._rate_limit_key = f"user:{user['username']}"
    assert agent._full_plan_refusal() is None
    events = [json.loads(e) for e in agent._full_plan_refusal()]
    assert events[0]["type"] == "delta"
    assert "today's AI allowance for searches" in events[0]["text"]
    assert events[1] == {"type": "done"}
