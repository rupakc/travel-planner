"""Regression tests for chat robustness.

Covers the production bug where the chat stream silently died (no response
shown to the user) and session context / history was lost:

1. Empty-content assistant messages (produced by planning-only turns) were
   forwarded to the Anthropic API, which rejects empty content with a 400.
2. When the chat model call failed, only an ``error`` event was yielded —
   the frontend had no handler for it, so the user saw a blank bubble.
3. The specialist-agent path never emitted ``session_context_update``, so
   trip context was lost between requests (ChatAgent is per-request).
4. ``_summarize_search_results`` crashed on flights with ``price_usd: None``,
   killing the SSE stream mid-flight with no terminal event.
5. The ``/api/chat`` SSE generator had no exception guard, so any uncaught
   error truncated the stream without a ``done`` event.
"""

import json
from datetime import date
from unittest.mock import patch

import pytest

from app.agents.chat_agent import ChatAgent
from app.core.config import settings
from app.schemas.request import TravelSearchRequest


@pytest.fixture()
def chat_agent():
    return ChatAgent(agents_dir=settings.agents_dir)


def _request():
    return TravelSearchRequest(
        origin="London",
        destination="Tokyo",
        departure_date=date(2026, 9, 1),
        return_date=date(2026, 9, 8),
        interests=["food"],
        nationality="British",
        residence_permits=[],
        existing_visas=[],
        budget_usd=3000,
        num_travelers=1,
    )


async def _collect(agen):
    return [json.loads(chunk) async for chunk in agen]


# ─── 1. History sanitisation ──────────────────────────────────────────────


class TestToApiMessages:
    def test_drops_empty_assistant_messages(self):
        msgs = ChatAgent._to_api_messages(
            [
                {"role": "user", "content": "plan a trip to Tokyo"},
                {"role": "assistant", "content": ""},  # planning-only turn
                {"role": "user", "content": "what about the food there?"},
            ]
        )
        assert all(m["content"].strip() for m in msgs)
        assert msgs[0]["role"] == "user"
        assert msgs[-1]["role"] == "user"

    def test_drops_whitespace_only_messages(self):
        msgs = ChatAgent._to_api_messages(
            [
                {"role": "user", "content": "   \n"},
                {"role": "assistant", "content": "\t"},
                {"role": "user", "content": "hello"},
            ]
        )
        assert msgs == [{"role": "user", "content": "hello"}]

    def test_all_empty_yields_fallback(self):
        msgs = ChatAgent._to_api_messages([{"role": "assistant", "content": ""}])
        assert msgs == [{"role": "user", "content": "Hello"}]

    def test_first_message_is_user(self):
        msgs = ChatAgent._to_api_messages(
            [
                {"role": "assistant", "content": "Hi, where do you want to go?"},
                {"role": "user", "content": "Paris"},
            ]
        )
        assert msgs[0]["role"] == "user"

    def test_no_trailing_assistant_prefill(self):
        # A trailing assistant message is treated as a prefill by the API and
        # rejected with a 400 on current models.
        msgs = ChatAgent._to_api_messages(
            [
                {"role": "user", "content": "hello"},
                {"role": "assistant", "content": "Hi there!"},
            ]
        )
        assert msgs[-1]["role"] == "user"

    def test_merges_consecutive_same_role(self):
        msgs = ChatAgent._to_api_messages(
            [
                {"role": "user", "content": "one"},
                {"role": "user", "content": "two"},
            ]
        )
        assert msgs == [{"role": "user", "content": "one\n\ntwo"}]


# ─── 2. Model-call failure must still produce a visible reply ─────────────


class TestRegularChatErrorFallback:
    @pytest.mark.anyio
    async def test_yields_friendly_delta_and_done_on_failure(self, chat_agent):
        def _boom():
            raise RuntimeError("api exploded")

        with patch("app.agents.chat_agent._get_client", _boom):
            events = await _collect(
                chat_agent._regular_chat([{"role": "user", "content": "hi"}])
            )

        types = [e["type"] for e in events]
        assert "done" in types, "stream must always terminate with done"
        deltas = [e for e in events if e["type"] == "delta"]
        assert deltas and deltas[0]["text"].strip(), (
            "user must always see a visible reply, even on API failure"
        )


# ─── 3. Specialist path must emit session context ─────────────────────────


class TestSpecialistSessionContext:
    @pytest.mark.anyio
    async def test_emits_session_context_update(self, chat_agent):
        async def fake_run(self, request, **kwargs):
            return {"requirement": {"visa_type": "visa-free"}}

        with patch("app.agents.visa_agent.VisaAgent.run", fake_run):
            events = await _collect(
                chat_agent._run_specialist_agents(_request(), [], None, None, ["visa"])
            )

        types = [e["type"] for e in events]
        assert "session_result" not in types  # sanity
        assert "section_result" in types
        assert "planning_done" in types
        ctx_events = [e for e in events if e["type"] == "session_context_update"]
        assert ctx_events, "specialist path must persist session context"
        assert ctx_events[0]["context"]["destination"] == "Tokyo"


# ─── 4. Summaries must tolerate missing prices ────────────────────────────


class TestSummaries:
    def test_search_results_with_none_prices(self):
        results = {
            "flights": {
                "results": [
                    {"price_usd": None, "airline": "JAL"},
                    {"airline": "ANA"},
                    {"price_usd": 850, "airline": "BA"},
                ]
            }
        }
        summary = ChatAgent._summarize_search_results(results)
        assert "Flights" in summary

    def test_selections_with_non_dict_values(self):
        # Malformed client payloads must not crash the stream.
        summary = ChatAgent._summarize_selections({"activities": [{}], "flight": {}})
        assert isinstance(summary, str)


# ─── 5. Route-level: SSE generator never dies silently ────────────────────


class TestChatRouteRobustness:
    def test_stream_failure_ends_with_done(self, client, admin_headers):
        class ExplodingAgent:
            def __init__(self, *a, **kw):
                pass

            async def stream(self, *a, **kw):
                yield json.dumps({"type": "delta", "text": "partial"})
                raise RuntimeError("mid-stream failure")

        with patch("app.api.routes.chat.ChatAgent", ExplodingAgent):
            r = client.post(
                "/api/chat",
                headers=admin_headers,
                json={"messages": [{"role": "user", "content": "hi"}]},
            )

        assert r.status_code == 200
        events = [
            json.loads(line[len("data: ") :])
            for line in r.text.splitlines()
            if line.startswith("data: ")
        ]
        types = [e["type"] for e in events]
        assert types[-1] == "done", f"stream must terminate with done, got {types}"
        assert "error" in types


class TestChatImprovements:
    def _agent(self):
        from app.agents.chat_agent import ChatAgent

        agent = ChatAgent.__new__(ChatAgent)
        agent.agents_dir = "../.agents"
        agent._session_context = {}
        agent._taste_context = None
        return agent

    def test_diff_affected_maps_fields_to_sections(self):
        from app.schemas.request import TravelSearchRequest

        agent = self._agent()
        base = TravelSearchRequest(
            origin="NYC",
            destination="Tokyo, Japan",
            departure_date="2026-09-01",
            return_date="2026-09-08",
            nationality="American",
            budget_usd=3000,
        )
        cheaper = base.model_copy(update={"budget_usd": 1500})
        affected = agent._diff_affected(base, cheaper)
        assert affected == {"flights", "hotels"}
        assert agent._refinement_needs_itinerary is False

        longer = base.model_copy(
            update={"return_date": base.return_date.replace(day=12)}
        )
        affected = agent._diff_affected(base, longer)
        assert "flights" in affected and "hotels" in affected
        assert agent._refinement_needs_itinerary is True

    def test_clarify_missing_emits_question_and_chips(self):
        import json

        agent = self._agent()
        events = [json.loads(c) for c in agent._clarify_missing({})]
        types = [e["type"] for e in events]
        assert types == ["delta", "suggestions", "done"]
        assert "Where would you like to go" in events[0]["text"]
        assert len(events[1]["chips"]) >= 3

    @pytest.mark.anyio
    async def test_planning_intent_without_destination_asks_clarifying_question(self):
        import json
        from unittest.mock import AsyncMock

        agent = self._agent()
        agent._extract_travel_params = AsyncMock(return_value=None)
        events = []
        async for chunk in agent.stream(
            [{"role": "user", "content": "help me plan a trip"}]
        ):
            events.append(json.loads(chunk))
        types = [e["type"] for e in events]
        assert "suggestions" in types
        assert any("Where would you like to go" in e.get("text", "") for e in events)

    def test_taste_context_lands_in_system_prompt(self):
        from app.agents.loader import load_agent_definition

        agent = self._agent()
        agent.definition = load_agent_definition("../.agents", "chat")
        agent._taste_context = "usually books luxury hotels"
        prompt = agent._build_system_prompt(None, None)
        assert "Learned Traveler Taste" in prompt
        assert "luxury hotels" in prompt

    def test_itinerary_keeps_user_city_order(self):
        # The chat itinerary must not reorder the user's requested cities
        import inspect

        from app.agents import chat_itinerary_agent as cia

        source = inspect.getsource(cia)
        assert "optimize_city_order" not in source
