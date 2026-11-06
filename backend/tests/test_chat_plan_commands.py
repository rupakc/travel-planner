"""Chat plan commands see each flight / hotel / activity (E2E finding O8).

``_handle_plan_command`` used to send the model hotel *counts* only
("Hotels: 12 options"), so "add the cheapest hotel" was refused. The model
now gets one compact, bounded line per item with a ref (F1, H2, A3) and
answers with ``{"ref": ...}``; the server swaps in the full result item.
"""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from app.agents.chat_agent import ChatAgent
from app.core.config import settings

HOTELS = [
    {
        "name": "Palácio Grande",
        "star_rating": 5.0,
        "price_per_night_usd": 410.0,
        "total_price_usd": 1640.0,
        "review_score": 9.4,
        "tier": "luxury",
        "booking_url": "https://example.test/palacio",
    },
    {
        "name": "Casa Alfama",
        "star_rating": 3.0,
        "price_per_night_usd": 72.5,
        "total_price_usd": 290.0,
        "review_score": 8.6,
        "tier": "budget",
        "booking_url": "https://example.test/casa",
    },
    {"error": "enrichment failed"},
]
FLIGHTS = [
    {
        "price_usd": 612.0,
        "outbound": {
            "airline": "TAP Air Portugal",
            "flight_number": "TP555",
            "departure_time": "07:10",
            "duration_minutes": 170,
            "stops": 0,
        },
    },
    {"price_usd": None, "outbound": {"airline": "Lufthansa", "stops": 1}},
]
ACTIVITIES = [
    {
        "name": "Fado night in Alfama",
        "price_usd": 45,
        "rating": 4.8,
        "category": "music",
    }
]
RESULTS = {
    "flights": {"results": FLIGHTS},
    "hotels": {"results": HOTELS},
    "activities": {"results": ACTIVITIES},
}


def test_summary_lists_each_hotel_flight_and_activity_with_refs():
    summary = ChatAgent._summarize_search_results(RESULTS)
    assert "Hotels: 2 options" in summary  # the error entry is not an option
    assert (
        "H1: Palácio Grande, $410/night, $1,640 total, 5★, reviews 9.4, luxury"
        in summary
    )
    assert "H2: Casa Alfama, $72.50/night, $290 total, 3★, reviews 8.6, budget" in (
        summary
    )
    assert "F1: TAP Air Portugal, TP555, $612, non-stop, departs 07:10, 2h50" in (
        summary
    )
    assert "F2: Lufthansa, price ?, 1 stop(s)" in summary
    assert "A1: Fado night in Alfama, $45, rating 4.8, music" in summary
    assert "booking_url" not in summary and "example.test" not in summary


def test_summary_is_bounded():
    many = [
        {"name": f"Hotel {i} " + "x" * 300, "price_per_night_usd": 100 + i}
        for i in range(60)
    ]
    summary = ChatAgent._summarize_search_results({"hotels": {"results": many}})
    assert "Hotels: 60 options" in summary
    assert f"H{ChatAgent._RESULT_LIST_LIMIT}:" in summary
    assert f"H{ChatAgent._RESULT_LIST_LIMIT + 1}:" not in summary
    assert "(+40 more not listed)" in summary
    assert "x" * (ChatAgent._RESULT_NAME_CHARS + 1) not in summary
    assert len(summary) < 3000


def test_refs_resolve_to_the_full_items():
    actions = ChatAgent._resolve_plan_actions(
        [
            {"action": "set", "field": "hotel", "data": {"ref": "H2"}},
            {"action": "set", "field": "flight", "data": {"ref": "f1"}},
            {"action": "add", "field": "activities", "data": {"ref": "A1"}},
            {"action": "add", "field": "hotel", "data": {"ref": "H9"}},  # unknown
            {"action": "clear", "field": "all", "data": None},
            {"action": "remove", "field": "activities", "data": {"name": "x"}},
        ],
        RESULTS,
    )
    assert actions[0] == {"action": "set", "field": "hotel", "data": HOTELS[1]}
    assert actions[1] == {"action": "set", "field": "flight", "data": FLIGHTS[0]}
    assert actions[2]["data"] == ACTIVITIES[0]
    assert [a["action"] for a in actions[3:]] == ["clear", "remove"]


def test_a_bare_name_resolves_too():
    [action] = ChatAgent._resolve_plan_actions(
        [{"action": "set", "field": "hotel", "data": {"name": "casa alfama"}}],
        RESULTS,
    )
    assert action["data"] == HOTELS[1]


def _model_reply(payload: dict):
    client = SimpleNamespace(
        messages=SimpleNamespace(
            create=AsyncMock(
                return_value=SimpleNamespace(
                    content=[SimpleNamespace(text=json.dumps(payload))]
                )
            )
        )
    )
    return client


async def test_add_the_cheapest_hotel_resolves_to_the_real_hotel():
    agent = ChatAgent(agents_dir=settings.agents_dir)
    client = _model_reply(
        {
            "actions": [{"action": "set", "field": "hotel", "data": {"ref": "H2"}}],
            "message": "Added **Casa Alfama**, the cheapest hotel.",
        }
    )
    with patch("app.agents.chat_agent._get_client", return_value=client):
        events = [
            json.loads(e)
            async for e in agent._handle_plan_command(
                [{"role": "user", "content": "add the cheapest hotel to my plan"}],
                None,
                {},
                RESULTS,
            )
        ]
    prompt = client.messages.create.await_args.kwargs["messages"][0]["content"]
    assert "H2: Casa Alfama, $72.50/night, $290 total" in prompt
    assert '{"ref": "<ref>"}' in prompt
    [action] = [e for e in events if e["type"] == "plan_action"]
    assert action["field"] == "hotel" and action["data"] == HOTELS[1]
    assert events[-1] == {"type": "done"}
