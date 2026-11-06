"""Chat hands a pasted trip link to the import flow (no fetching in chat)."""

import json
from unittest.mock import patch

import pytest

from app.agents.chat_agent import ChatAgent, import_link_request
from app.core.config import settings


@pytest.mark.parametrize(
    ("message", "url"),
    [
        (
            "https://wander.example/48-hours-lisbon",
            "https://wander.example/48-hours-lisbon",
        ),
        ("  https://youtu.be/abc123  ", "https://youtu.be/abc123"),
        (
            "plan a trip from this https://blog.example/rome?x=1.",
            "https://blog.example/rome?x=1",
        ),
        (
            "Can you plan my itinerary around www.lonelyplanet.com/japan/tokyo",
            "https://www.lonelyplanet.com/japan/tokyo",
        ),
    ],
)
def test_detects_trip_links(message, url):
    assert import_link_request(message) == url


@pytest.mark.parametrize(
    "message",
    [
        "What's the weather in Lisbon?",
        "Is https://visa.example/apply the official visa site?",  # a URL, no planning ask
        "plan a trip to Tokyo",
        "javascript:alert(1)",
    ],
)
def test_ignores_other_messages(message):
    assert import_link_request(message) is None


async def test_stream_replies_with_an_import_action_and_never_fetches():
    agent = ChatAgent(agents_dir=settings.agents_dir)
    with (
        patch("app.core.llm.generate") as generate,
        patch("app.core.llm.stream") as stream,
    ):
        events = [
            json.loads(e)
            async for e in agent.stream(
                [{"role": "user", "content": "https://wander.example/48-hours-lisbon"}]
            )
        ]
    generate.assert_not_called()
    stream.assert_not_called()
    types = [e["type"] for e in events]
    assert types == ["delta", "import_link", "done"]
    assert events[1]["url"] == "https://wander.example/48-hours-lisbon"
    assert (
        events[1]["href"] == "/?import=https%3A%2F%2Fwander.example%2F48-hours-lisbon"
    )
    assert "link" in events[0]["text"].lower()
