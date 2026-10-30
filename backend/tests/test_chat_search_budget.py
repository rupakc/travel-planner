"""Chat-triggered full trip plans also count against the search rate-limit bucket."""

import json
from datetime import date
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agents.chat_agent import ChatAgent
from app.core import rate_limit
from app.core.config import settings
from app.core.rate_limit import SlidingWindowLimiter, try_consume
from app.schemas.request import TravelSearchRequest


class FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


@pytest.fixture
def limits(monkeypatch):
    """Enable limiting with a fresh limiter on a fake clock; chat is unlimited."""
    clock = FakeClock()
    monkeypatch.setattr(settings, "rate_limit_enabled", True)
    monkeypatch.setattr(settings, "rate_limit_chat", 99)
    monkeypatch.setattr(rate_limit, "limiter", SlidingWindowLimiter(clock=clock))
    return clock


_PARAMS = TravelSearchRequest(
    origin="New York",
    destination="Tokyo, Japan",
    departure_date=date(2026, 12, 1),
    return_date=date(2026, 12, 8),
    nationality="American",
)

_PLAN_MSG = "Help me plan a trip to Tokyo, Japan from New York in December"
_QUESTION = "What is the best time of year to visit Japan?"


def _events(response) -> list[dict]:
    return [
        json.loads(line[len("data: ") :])
        for line in response.text.splitlines()
        if line.startswith("data: ")
    ]


def _search_hits() -> int:
    return len(rate_limit.limiter._hits.get("search:user:admin", ()))


@pytest.fixture
def agents():
    """Stub every model call a chat turn can make; return the mocks to assert on."""
    itinerary = MagicMock()
    itinerary.return_value.run = AsyncMock(return_value={"days": []})

    async def knowledge(*_a, **_kw):
        yield json.dumps({"type": "delta", "text": "Spring and autumn are lovely."})
        yield json.dumps({"type": "done"})

    with (
        patch("app.agents.chat_agent.ChatItineraryAgent", itinerary),
        patch.object(
            ChatAgent, "_extract_travel_params", AsyncMock(return_value=_PARAMS)
        ),
        patch.object(ChatAgent, "_proactive_warnings", AsyncMock(return_value=[])),
        patch.object(ChatAgent, "_generate_suggestions", AsyncMock(return_value=[])),
        patch.object(ChatAgent, "_route_intent", AsyncMock(return_value="knowledge")),
        patch.object(ChatAgent, "_knowledge_chat", knowledge),
        patch.object(ChatAgent, "_regular_chat", knowledge),
    ):
        yield {"itinerary": itinerary}


def _chat(client, headers, text, session_context=None):
    r = client.post(
        "/api/chat",
        headers=headers,
        json={
            "messages": [{"role": "user", "content": text}],
            "session_context": session_context or {},
        },
    )
    assert r.status_code == 200
    return _events(r)


# ── try_consume ──────────────────────────────────────────────────────────────


def test_try_consume_is_a_no_op_when_disabled(monkeypatch):
    monkeypatch.setattr(settings, "rate_limit_enabled", False)
    monkeypatch.setattr(settings, "rate_limit_search", 0)
    monkeypatch.setattr(rate_limit, "limiter", SlidingWindowLimiter(clock=FakeClock()))
    assert try_consume("search", "user:a") is None
    assert rate_limit.limiter._hits == {}


def test_try_consume_returns_retry_after_once_over(limits, monkeypatch):
    monkeypatch.setattr(settings, "rate_limit_search", 1)
    assert try_consume("search", "user:a") is None
    limits.now += 60
    assert try_consume("search", "user:a") == settings.rate_limit_window_seconds - 60
    assert try_consume("search", "user:b") is None


# ── Chat full plans ──────────────────────────────────────────────────────────


def test_full_plan_under_limit_runs_and_uses_one_search_token(
    client, limits, monkeypatch, admin_headers, agents
):
    monkeypatch.setattr(settings, "rate_limit_search", 2)
    types = [e["type"] for e in _chat(client, admin_headers, _PLAN_MSG)]
    assert types[0] == "planning_start"
    assert "comprehensive_itinerary" in types
    assert types[-1] == "planning_done"
    assert agents["itinerary"].return_value.run.await_count == 1
    assert _search_hits() == 1


def test_full_plan_over_limit_streams_friendly_message_and_runs_nothing(
    client, limits, monkeypatch, admin_headers, agents
):
    monkeypatch.setattr(settings, "rate_limit_search", 1)
    _chat(client, admin_headers, _PLAN_MSG)
    limits.now += 60  # 540 s until the slot frees -> "about 9 minutes"
    events = _chat(client, admin_headers, _PLAN_MSG)
    assert [e["type"] for e in events] == ["delta", "done"]
    assert events[0]["text"] == (
        "You've planned several full trips in the last few minutes — try again "
        "in about 9 minutes, or ask me a quick question meanwhile."
    )
    assert agents["itinerary"].return_value.run.await_count == 1  # first plan only


def test_over_limit_message_says_a_minute_when_under_one(
    client, limits, monkeypatch, admin_headers, agents
):
    monkeypatch.setattr(settings, "rate_limit_search", 1)
    _chat(client, admin_headers, _PLAN_MSG)
    limits.now += settings.rate_limit_window_seconds - 20
    events = _chat(client, admin_headers, _PLAN_MSG)
    assert "try again in about a minute," in events[0]["text"]


def test_plain_question_does_not_use_search_tokens(
    client, limits, monkeypatch, admin_headers, agents
):
    monkeypatch.setattr(settings, "rate_limit_search", 0)
    events = _chat(client, admin_headers, _QUESTION)
    assert events[0] == {"type": "delta", "text": "Spring and autumn are lovely."}
    assert events[-1]["type"] == "done"
    assert _search_hits() == 0


def test_refinement_needing_a_new_itinerary_is_checked_before_any_specialist(
    client, limits, monkeypatch, admin_headers, agents
):
    monkeypatch.setattr(settings, "rate_limit_search", 0)
    specialist = MagicMock()
    specialist.return_value.run = AsyncMock(return_value={"results": []})
    longer = _PARAMS.model_copy(update={"return_date": date(2026, 12, 10)})
    with (
        patch.object(ChatAgent, "_params_from_session_context", return_value=_PARAMS),
        patch.object(
            ChatAgent, "_apply_modification_hint", AsyncMock(return_value=longer)
        ),
        patch.object(
            ChatAgent,
            "_specialist_classes",
            return_value={n: specialist for n in ("flights", "hotels", "activities")},
        ),
    ):
        events = _chat(
            client,
            admin_headers,
            "Can you extend the trip by two days?",
            session_context={"destination": "Tokyo, Japan"},
        )
    assert [e["type"] for e in events] == ["delta", "done"]
    assert "planned several full trips" in events[0]["text"]
    specialist.return_value.run.assert_not_awaited()
    agents["itinerary"].return_value.run.assert_not_awaited()


def test_search_and_chat_plans_share_one_budget(
    client, limits, monkeypatch, admin_headers, agents
):
    monkeypatch.setattr(settings, "rate_limit_search", 1)
    with patch("app.api.routes.search.get_orchestrator") as factory:
        factory.return_value.run = AsyncMock(return_value={})
        r = client.post(
            "/api/search/sync",
            headers=admin_headers,
            json={
                "origin": "New York",
                "destination": "Tokyo, Japan",
                "departure_date": "2026-12-01",
                "return_date": "2026-12-08",
                "nationality": "American",
            },
        )
        assert r.status_code == 200
        events = _chat(client, admin_headers, _PLAN_MSG)
        assert [e["type"] for e in events] == ["delta", "done"]
        agents["itinerary"].return_value.run.assert_not_awaited()

        limits.now += settings.rate_limit_window_seconds
        assert _chat(client, admin_headers, _PLAN_MSG)[-1]["type"] == "planning_done"
        r = client.post("/api/search/sync", headers=admin_headers, json={})
        assert r.status_code == 429
