"""Per-user / per-IP rate limits on the AI endpoints."""

from unittest.mock import AsyncMock, patch

import pytest

from app.core import rate_limit
from app.core.config import settings
from app.core.rate_limit import SlidingWindowLimiter


class FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


# ── Limiter ──────────────────────────────────────────────────────────────────


def test_allows_limit_then_blocks_with_retry_after():
    clock = FakeClock()
    limiter = SlidingWindowLimiter(clock=clock)
    for _ in range(3):
        assert limiter.hit("user:a", limit=3, window=600) is None
    clock.now += 100
    assert limiter.hit("user:a", limit=3, window=600) == 500


def test_window_expiry_frees_slots_one_by_one():
    clock = FakeClock()
    limiter = SlidingWindowLimiter(clock=clock)
    limiter.hit("k", limit=2, window=60)
    clock.now += 30
    limiter.hit("k", limit=2, window=60)
    assert limiter.hit("k", limit=2, window=60) == 30
    clock.now += 30  # first hit has left the window
    assert limiter.hit("k", limit=2, window=60) is None
    assert limiter.hit("k", limit=2, window=60) == 30


def test_blocked_attempts_do_not_extend_the_wait():
    clock = FakeClock()
    limiter = SlidingWindowLimiter(clock=clock)
    limiter.hit("k", limit=1, window=60)
    for _ in range(5):
        limiter.hit("k", limit=1, window=60)
    clock.now += 60
    assert limiter.hit("k", limit=1, window=60) is None


def test_zero_limit_blocks_for_a_full_window():
    limiter = SlidingWindowLimiter(clock=FakeClock())
    assert limiter.hit("k", limit=0, window=60) == 60


def test_keys_do_not_share_buckets():
    limiter = SlidingWindowLimiter(clock=FakeClock())
    assert limiter.hit("user:a", limit=1, window=60) is None
    assert limiter.hit("user:a", limit=1, window=60) is not None
    assert limiter.hit("user:b", limit=1, window=60) is None
    assert limiter.hit("ip:1.2.3.4", limit=1, window=60) is None


def test_stale_keys_are_pruned():
    clock = FakeClock()
    limiter = SlidingWindowLimiter(clock=clock)
    limiter.hit("old", limit=5, window=60)
    clock.now += 61
    limiter.prune(window=60)
    assert "old" not in limiter._hits


# ── Endpoints ────────────────────────────────────────────────────────────────


@pytest.fixture
def limits(monkeypatch):
    """Enable limiting with a fresh limiter on a fake clock."""
    clock = FakeClock()
    monkeypatch.setattr(settings, "rate_limit_enabled", True)
    monkeypatch.setattr(rate_limit, "limiter", SlidingWindowLimiter(clock=clock))
    return clock


_TRIP = {
    "origin": "New York",
    "destination": "Tokyo, Japan",
    "departure_date": "2026-09-01",
    "return_date": "2026-09-08",
    "nationality": "American",
}


def _visa_calls(client, n, headers=None):
    with patch("app.api.routes.visa.VisaAgent") as agent_cls:
        agent_cls.return_value.run = AsyncMock(return_value={"requirement": {}})
        return [client.post("/api/visa", json=_TRIP, headers=headers) for _ in range(n)]


def test_light_ai_limit_returns_429_with_retry_after(client, limits, monkeypatch):
    monkeypatch.setattr(settings, "rate_limit_light_ai", 2)
    responses = _visa_calls(client, 3)
    assert [r.status_code for r in responses] == [200, 200, 429]
    blocked = responses[-1]
    assert blocked.headers["Retry-After"] == "600"
    assert blocked.json() == {
        "detail": "Too many requests — please wait 600 seconds and try again."
    }


def test_limit_resets_after_window(client, limits, monkeypatch):
    monkeypatch.setattr(settings, "rate_limit_light_ai", 1)
    assert [r.status_code for r in _visa_calls(client, 2)] == [200, 429]
    limits.now += settings.rate_limit_window_seconds
    assert _visa_calls(client, 1)[0].status_code == 200


def test_signed_in_user_and_anonymous_ip_have_separate_buckets(
    client, limits, monkeypatch, admin_headers
):
    monkeypatch.setattr(settings, "rate_limit_light_ai", 1)
    assert _visa_calls(client, 1)[0].status_code == 200  # ip:testclient
    assert _visa_calls(client, 1)[0].status_code == 429
    assert _visa_calls(client, 1, admin_headers)[0].status_code == 200  # user:admin
    assert _visa_calls(client, 1, admin_headers)[0].status_code == 429


def test_buckets_are_independent(client, limits, monkeypatch):
    monkeypatch.setattr(settings, "rate_limit_light_ai", 1)
    monkeypatch.setattr(settings, "rate_limit_discover", 1)
    assert _visa_calls(client, 2)[1].status_code == 429
    with patch("app.api.routes.discover.get_discovery_agent") as factory:
        factory.return_value.run = AsyncMock(return_value={"destinations": []})
        r = client.post(
            "/api/discover",
            json={
                "origin": "New York",
                "nationality": "American",
                "departure_date": "2026-08-01",
                "return_date": "2026-08-08",
                "budget_usd": 3000,
                "interests": ["food"],
            },
        )
    assert r.status_code == 200


def test_disabled_by_default_in_tests(client):
    assert settings.rate_limit_enabled is False
    assert all(r.status_code == 200 for r in _visa_calls(client, 5))


def test_default_limits(monkeypatch):
    from app.core.config import Settings

    monkeypatch.delenv("RATE_LIMIT_ENABLED", raising=False)
    s = Settings(_env_file=None)
    assert s.rate_limit_enabled is True
    assert s.rate_limit_window_seconds == 600
    assert (
        s.rate_limit_search,
        s.rate_limit_chat,
        s.rate_limit_compare,
        s.rate_limit_discover,
        s.rate_limit_light_ai,
    ) == (10, 30, 30, 10, 60)


# ── Wiring: every expensive route is limited in the right bucket ────────────


EXPECTED_BUCKETS = {
    ("POST", "/api/search"): "search",
    ("POST", "/api/search/sync"): "search",
    ("POST", "/api/chat"): "chat",
    ("POST", "/api/compare/destination"): "compare",
    ("POST", "/api/discover"): "discover",
    ("POST", "/api/stress-test"): "light_ai",
    ("POST", "/api/flights"): "light_ai",
    ("POST", "/api/flights/filtered"): "light_ai",
    ("POST", "/api/hotels"): "light_ai",
    ("POST", "/api/hotels/filtered"): "light_ai",
    ("POST", "/api/activities"): "light_ai",
    ("POST", "/api/activities/filtered"): "light_ai",
    ("POST", "/api/visa"): "light_ai",
    ("POST", "/api/sim"): "light_ai",
    ("POST", "/api/tips"): "light_ai",
    ("POST", "/api/getting-around"): "light_ai",
    ("POST", "/api/forex"): "light_ai",
    ("POST", "/api/itinerary"): "light_ai",
    ("POST", "/api/events"): "light_ai",
    ("POST", "/api/walking-tours"): "light_ai",
    ("POST", "/api/layover"): "light_ai",
}


def _write_operations():
    from app.main import app

    for path, ops in app.openapi()["paths"].items():
        for method in ops:
            if method.upper() in {"POST", "PUT", "PATCH", "DELETE"}:
                yield method.upper(), path


@pytest.mark.parametrize("bucket", sorted(set(EXPECTED_BUCKETS.values())))
def test_route_buckets(client, limits, monkeypatch, bucket):
    """With one bucket's limit at 0, exactly that bucket's routes return 429.

    Bodies are empty, so routes that are not blocked fail validation/auth
    before reaching any agent.
    """
    for name in set(EXPECTED_BUCKETS.values()):
        monkeypatch.setattr(settings, f"rate_limit_{name}", 0 if name == bucket else 99)
    blocked = set()
    for method, path in _write_operations():
        url = path.replace("{plan_id}", "1").replace("{username}", "nobody")
        if client.request(method, url, json={}).status_code == 429:
            blocked.add((method, path))
    assert blocked == {route for route, b in EXPECTED_BUCKETS.items() if b == bucket}
