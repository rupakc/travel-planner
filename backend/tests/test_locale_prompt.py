"""AI output in the user's language: the system-prompt suffix, cache keys
and request validation. English / absent locale must stay byte-identical."""

import asyncio
from datetime import date

import pytest

from app.agents.base_agent import BaseAgent, language_instruction
from app.agents.loader import AgentDefinition
from app.agents.tips_agent import TipsAgent
from app.core import llm
from app.core.cache import request_digest
from app.schemas.request import TravelSearchRequest


def _req(**kw):
    return TravelSearchRequest(
        origin="JFK",
        destination="Tokyo",
        departure_date=date(2027, 4, 1),
        return_date=date(2027, 4, 8),
        nationality="American",
        **kw,
    )


@pytest.mark.parametrize("loc", [None, "en", "", "xx"])
def test_instruction_absent_for_english(loc):
    assert language_instruction(loc) == ""


def test_instruction_present_for_german():
    assert language_instruction("de") == (
        "Write every human-readable text value in German. Keep JSON keys, enum "
        "values, codes, URLs, prices, currency codes, dates and names of places, "
        "venues, hotels, restaurants, tours, events and airlines exactly as you "
        "would in English output."
    )


@pytest.mark.parametrize(
    "loc,name",
    [
        ("es", "Spanish"),
        ("fr", "French"),
        ("hi", "Hindi"),
        ("zh", "Simplified Chinese"),
        ("bn", "Bengali"),
    ],
)
def test_language_names(loc, name):
    assert f"text value in {name}." in language_instruction(loc)


def _capture(monkeypatch):
    seen = []

    async def fake_generate(messages, **kw):
        seen.append(kw["system"])
        return llm.LLMResponse(text='{"ok": 1}', truncated=False)

    monkeypatch.setattr(llm, "generate", fake_generate)
    return seen


def test_execute_suffix_only_when_locale_given(monkeypatch):
    seen = _capture(monkeypatch)
    agent = BaseAgent(AgentDefinition(name="x", description="", system_prompt="SYS"))
    asyncio.run(agent.execute("p"))
    asyncio.run(agent.execute("p", locale="en"))
    asyncio.run(agent.execute("p", locale="de"))
    assert seen[0] == seen[1]
    assert "German" not in seen[0]
    assert seen[2].startswith(seen[0])
    assert seen[2].endswith(language_instruction("de"))


def test_specialist_run_threads_request_locale(monkeypatch):
    seen = _capture(monkeypatch)
    agent = TipsAgent("../.agents")
    asyncio.run(agent.run(_req(locale="fr")))
    asyncio.run(agent.run(_req()))
    assert "in French" in seen[0]
    assert "Write every human-readable" not in seen[1]


# MD5 of _req().model_dump_json() computed with the pre-locale schema
# (backend/app/schemas/request.py at b5b023d): a deploy must not change it.
PRE_LOCALE_DIGEST = "d2c0790f0474b8bb6e8705066d274967"


def test_cache_key_english_unchanged_and_locales_differ():
    assert request_digest(_req()) == PRE_LOCALE_DIGEST
    assert request_digest(_req(locale="en")) == PRE_LOCALE_DIGEST
    assert request_digest(_req(locale="de")) != PRE_LOCALE_DIGEST
    assert request_digest(_req(locale="de")) != request_digest(_req(locale="fr"))


def test_unknown_locale_is_422(client):
    body = {
        "origin": "JFK",
        "destination": "Tokyo",
        "departure_date": "2027-04-01",
        "nationality": "American",
        "locale": "xx",
    }
    assert client.post("/api/search", json=body).status_code == 422
