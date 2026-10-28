"""Tests for the walking-tour crawler (httpx.MockTransport, no network)."""

import json

import httpx
import pytest

from app.core.cache import get_cache
from app.services import walking_tours
from app.services.walking_tours import fetch_city_tours


@pytest.fixture(autouse=True)
def _clear_cache():
    get_cache().clear()
    yield
    get_cache().clear()


def _jsonld_page(domain: str, n: int = 2) -> str:
    events = [
        {
            "@type": "Event",
            "name": f"Tour {i}",
            "url": f"https://www.{domain}/walks/{i}-tour",
        }
        for i in range(n)
    ]
    return f'<script type="application/ld+json">{json.dumps(events)}</script>'


FWT_PAGE = (
    '<a class="relative block h-full" href="/lisbon/old-town/">'
    "Pay what you wish Old Town 4.9 116 reviews 2h 30m Book now</a>"
)
SANDEMANS_PAGE = '<a href="/sandemans-tours/lisbon/free-tour/">Lisbon Free Tour</a>'

PAGES = {
    "www.guruwalk.com": _jsonld_page("guruwalk.com", 3),
    "www.freetour.com": _jsonld_page("freetour.com", 2),
    "freewalkingtour.com": FWT_PAGE,
    "www.neweuropetours.eu": SANDEMANS_PAGE,
}


def _client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def _ok_handler(request: httpx.Request) -> httpx.Response:
    return httpx.Response(200, text=PAGES[request.url.host])


async def test_fetch_city_tours_all_ok():
    async with _client(_ok_handler) as client:
        tours, sources = await fetch_city_tours("Lisbon", client=client)
    assert [s["provider_key"] for s in sources] == [
        "guruwalk",
        "freetour",
        "freewalkingtour",
        "sandemans",
    ]
    assert [s["status"] for s in sources] == ["ok"] * 4
    assert [s["count"] for s in sources] == [3, 2, 1, 1]
    assert sources[0]["provider"] == "GuruWalk"
    assert sources[0]["city"] == "Lisbon"
    assert sources[0]["url"] == "https://www.guruwalk.com/lisbon"
    assert len(tours) == 7
    assert {t["provider_key"] for t in tours} == {
        "guruwalk",
        "freetour",
        "freewalkingtour",
        "sandemans",
    }


async def test_fetch_city_tours_partial_failure(monkeypatch):
    async def no_discovery(provider_key, city):
        return None

    monkeypatch.setattr(walking_tours, "_discover_city_url", no_discovery)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "www.guruwalk.com":
            raise httpx.ConnectTimeout("boom", request=request)
        if request.url.host == "freewalkingtour.com":
            return httpx.Response(500)
        return _ok_handler(request)

    async with _client(handler) as client:
        tours, sources = await fetch_city_tours("Lisbon", client=client)
    assert [s["status"] for s in sources] == ["error", "ok", "none", "ok"]
    assert [s["count"] for s in sources] == [0, 2, 0, 1]
    assert {t["provider_key"] for t in tours} == {"freetour", "sandemans"}


async def test_fetch_uses_cache():
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        return _ok_handler(request)

    async with _client(handler) as client:
        first = await fetch_city_tours("Lisbon", client=client)
        assert len(calls) == 4
        second = await fetch_city_tours("Lisbon", client=client)
    assert len(calls) == 4
    assert second == first
    assert [s["status"] for s in second[1]] == ["ok"] * 4


async def test_failures_are_not_cached():
    state = {"fail": True}

    def handler(request: httpx.Request) -> httpx.Response:
        if state["fail"]:
            raise httpx.ConnectError("down", request=request)
        return _ok_handler(request)

    async with _client(handler) as client:
        _, sources = await fetch_city_tours("Lisbon", client=client)
        assert [s["status"] for s in sources] == ["error"] * 4
        state["fail"] = False
        _, sources = await fetch_city_tours("Lisbon", client=client)
    assert [s["status"] for s in sources] == ["ok"] * 4


async def test_discovery_fallback_used_on_404(monkeypatch):
    discovered = []

    async def fake_discover(provider_key, city):
        discovered.append((provider_key, city))
        return "https://www.freetour.com/lisbon"

    monkeypatch.setattr(walking_tours, "_discover_city_url", fake_discover)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "www.freetour.com":
            if request.url.path == "/lisbon":
                return httpx.Response(200, text=PAGES["www.freetour.com"])
            return httpx.Response(404)
        return _ok_handler(request)

    async with _client(handler) as client:
        tours, sources = await fetch_city_tours("Lisboa X", client=client)
    freetour = next(s for s in sources if s["provider_key"] == "freetour")
    assert freetour["status"] == "ok"
    assert freetour["count"] == 2
    assert freetour["url"] == "https://www.freetour.com/lisbon"
    assert discovered == [("freetour", "Lisboa X")]
    assert sum(t["provider_key"] == "freetour" for t in tours) == 2


async def test_discovery_nothing_found_stays_none(monkeypatch):
    async def none_found(provider_key, city):
        return None

    monkeypatch.setattr(walking_tours, "_discover_city_url", none_found)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "www.guruwalk.com":
            return httpx.Response(404)
        return _ok_handler(request)

    async with _client(handler) as client:
        _, sources = await fetch_city_tours("Lisbon", client=client)
    assert sources[0]["status"] == "none"


async def test_discover_city_url_picks_first_matching_result(monkeypatch):
    queries = []

    def fake_search(query, max_results):
        queries.append(query)
        return [
            {"href": "https://www.guruwalk.com/walks/1-some-tour"},
            {"href": "https://evil.example/guruwalk.com/x"},
            {"href": "https://www.guruwalk.com/lisboa/"},
            {"href": "https://www.guruwalk.com/porto"},
        ]

    monkeypatch.setattr(walking_tours, "_ddgs_search", fake_search)
    url = await walking_tours._discover_city_url("guruwalk", "Lisbon")
    assert url == "https://www.guruwalk.com/lisboa/"
    assert queries == ["site:guruwalk.com Lisbon free walking tour"]


async def test_discover_city_url_swallows_search_errors(monkeypatch):
    def boom(query, max_results):
        raise RuntimeError("rate limited")

    monkeypatch.setattr(walking_tours, "_ddgs_search", boom)
    assert await walking_tours._discover_city_url("freetour", "Lisbon") is None


async def test_requests_send_honest_user_agent():
    agents = []

    def handler(request: httpx.Request) -> httpx.Response:
        agents.append(request.headers.get("user-agent"))
        return _ok_handler(request)

    async with _client(handler) as client:
        await fetch_city_tours("Lisbon", client=client)
    assert len(agents) == 4
    assert all(a.startswith("VoyagerTravelPlanner/1.0") for a in agents)
