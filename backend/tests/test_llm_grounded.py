"""``llm.generate_grounded``: Gemini with Google Search / Google Maps
grounding, text output. The SDK is faked at the client boundary — no
network, no credentials."""

import logging
import time

import pytest

from app.core import llm
from app.core.config import settings

from .grounding_fakes import chunk as _chunk
from .grounding_fakes import grounded_reply
from .grounding_fakes import maps as _maps
from .grounding_fakes import support as _support
from .grounding_fakes import web as _web
from .test_llm import FakeGemini, _api_error


@pytest.fixture
def gemini(monkeypatch):
    monkeypatch.setattr(settings, "llm_provider", "gemini")
    fake = FakeGemini()
    monkeypatch.setattr(llm, "_gemini_client", lambda: fake)
    return fake


async def test_search_grounding_sends_the_search_tool_and_text_output(gemini):
    gemini.replies = [
        grounded_reply(
            "Rooms from EUR 412.",
            chunks=[_chunk(web=_web("https://g.co/a", "booking.com", "booking.com"))],
            queries=["memmo alfama price"],
            supports=[_support("Rooms from EUR 412.", [0], 0, 19)],
        )
    ]

    out = await llm.generate_grounded(
        "What does it cost?", tool="search", system="Today is 2026-11-06.", label="t"
    )

    [call] = gemini.calls
    config = call["config"]
    assert call["model"] == settings.gemini_model_agent
    [tool] = config.tools
    assert tool.google_search is not None and tool.google_maps is None
    # JSON mode is never combined with grounding
    assert config.response_mime_type is None
    assert config.system_instruction == "Today is 2026-11-06."
    assert out.text == "Rooms from EUR 412."
    assert out.chunks == [
        {
            "kind": "web",
            "uri": "https://g.co/a",
            "title": "booking.com",
            "place_id": None,
        }
    ]
    assert out.search_queries == ["memmo alfama price"]
    assert out.supports == [
        {"text": "Rooms from EUR 412.", "start": 0, "end": 19, "chunks": [0]}
    ]
    assert out.usage["input_tokens"] == 40


async def test_maps_grounding_carries_location_and_language(gemini):
    gemini.replies = [
        grounded_reply(
            "EAT|Time Out Market|Food hall",
            chunks=[
                _chunk(
                    maps=_maps(
                        "https://maps.google.com/?cid=1", "Time Out Market", "places/X"
                    )
                )
            ],
        )
    ]

    out = await llm.generate_grounded(
        "near me", tool="maps", lat=38.72, lng=-9.14, language="pt"
    )

    config = gemini.calls[0]["config"]
    [tool] = config.tools
    assert tool.google_maps is not None and tool.google_search is None
    rc = config.tool_config.retrieval_config
    assert (rc.lat_lng.latitude, rc.lat_lng.longitude) == (38.72, -9.14)
    assert rc.language_code == "pt"
    assert out.chunks == [
        {
            "kind": "maps",
            "uri": "https://maps.google.com/?cid=1",
            "title": "Time Out Market",
            "place_id": "places/X",
        }
    ]


async def test_missing_grounding_metadata_is_an_empty_result(gemini):
    reply = grounded_reply("I don't know.")
    reply.candidates[0].grounding_metadata = None
    gemini.replies = [reply]

    out = await llm.generate_grounded("q", tool="search")

    assert out.text == "I don't know."
    assert (out.chunks, out.search_queries, out.supports) == ([], [], [])


async def test_anthropic_provider_has_no_grounding(monkeypatch):
    monkeypatch.setattr(settings, "llm_provider", "anthropic")

    with pytest.raises(llm.LLMError) as err:
        await llm.generate_grounded("q", tool="search")

    assert err.value.user_code == llm.GROUNDING_UNAVAILABLE_CODE
    assert str(err.value) == llm.GROUNDING_UNAVAILABLE_MESSAGE
    assert not err.value.retryable


async def test_spend_cap_hold_fails_fast(gemini, monkeypatch):
    monkeypatch.setattr(llm, "_spend_cap_until", time.monotonic() + 60)
    monkeypatch.setattr(llm, "_pause_code", llm.SPEND_CAP_CODE)

    with pytest.raises(llm.LLMError) as err:
        await llm.generate_grounded("q", tool="maps", lat=1, lng=2)

    assert err.value.spend_cap
    assert gemini.calls == []


async def test_budget_rejection_becomes_the_spend_cap(gemini):
    gemini.replies = [_api_error(429, "RESOURCE_EXHAUSTED", "Budget exceeded")]

    with pytest.raises(llm.LLMError) as err:
        await llm.generate_grounded("q", tool="search")

    assert err.value.user_code == llm.SPEND_CAP_CODE


async def test_billing_disabled_has_its_own_code(gemini):
    gemini.replies = [
        _api_error(403, "PERMISSION_DENIED", "Billing is disabled for project x")
    ]

    with pytest.raises(llm.LLMError) as err:
        await llm.generate_grounded("q", tool="search")

    assert err.value.user_code == llm.BILLING_CODE


async def test_grounded_usage_is_logged_without_content(gemini, caplog):
    gemini.replies = [
        grounded_reply(
            "secret answer",
            chunks=[_chunk(web=_web("https://g.co/a", "a"))],
            queries=["private query one", "two"],
        )
    ]

    with caplog.at_level(logging.INFO, logger="app.core.llm"):
        await llm.generate_grounded("my secret prompt", tool="search", label="lc")

    [line] = [r.getMessage() for r in caplog.records if "llm_usage" in r.getMessage()]
    assert "label=lc" in line and "input_tokens=40" in line
    assert "search_queries=2" in line and "grounding_chunks=1" in line
    assert "secret" not in line and "private query" not in line


async def test_rejects_an_unknown_tool(gemini):
    with pytest.raises(ValueError):
        await llm.generate_grounded("q", tool="bing")
