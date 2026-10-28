"""Tests for the walking-tour crawler (httpx.MockTransport, no network)."""

import asyncio
import json
import logging

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


def _jsonld_page(domain: str, n: int = 2, locality: str | None = None) -> str:
    events = [
        {
            "@type": "Event",
            "name": f"Tour {i}",
            "url": f"https://www.{domain}/walks/{i}-tour",
        }
        for i in range(n)
    ]
    if locality is not None:
        for ev in events:
            ev["location"] = {
                "@type": "Place",
                "address": {"@type": "PostalAddress", "addressLocality": locality},
            }
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
        return "https://www.freetour.com/lisbon-portugal"

    monkeypatch.setattr(walking_tours, "_discover_city_url", fake_discover)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "www.freetour.com":
            if request.url.path == "/lisbon-portugal":
                return httpx.Response(200, text=PAGES["www.freetour.com"])
            return httpx.Response(404)
        return _ok_handler(request)

    async with _client(handler) as client:
        tours, sources = await fetch_city_tours("Lisbon", client=client)
    freetour = next(s for s in sources if s["provider_key"] == "freetour")
    assert freetour["status"] == "ok"
    assert freetour["count"] == 2
    assert freetour["url"] == "https://www.freetour.com/lisbon-portugal"
    assert discovered == [("freetour", "Lisbon")]
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
            {"href": "https://www.guruwalk.com/search"},
            {"href": "https://www.guruwalk.com/en"},
            {"href": "https://www.guruwalk.com/porto"},
            {"href": "https://www.guruwalk.com/lisboa/"},
            {"href": "https://www.guruwalk.com/lisbon-city/"},
            {"href": "https://www.guruwalk.com/lisbon"},
        ]

    monkeypatch.setattr(walking_tours, "_ddgs_search", fake_search)
    url = await walking_tours._discover_city_url("guruwalk", "Lisbon")
    assert url == "https://www.guruwalk.com/lisbon-city/"
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


async def test_empty_slug_never_requests_provider_root(monkeypatch):
    discovered = []

    async def fake_discover(provider_key, city):
        discovered.append(provider_key)
        return None

    monkeypatch.setattr(walking_tours, "_discover_city_url", fake_discover)
    requested = []

    def handler(request: httpx.Request) -> httpx.Response:
        requested.append(str(request.url))
        return httpx.Response(200, text="<html></html>")

    async with _client(handler) as client:
        tours, sources = await fetch_city_tours("東京", client=client)
    assert requested == []
    assert tours == []
    assert [s["status"] for s in sources] == ["none"] * 4
    assert discovered == ["guruwalk", "freetour"]
    assert not any(k.endswith(":") for k in get_cache())


async def test_empty_slug_uses_discovered_city_page(monkeypatch):
    async def fake_discover(provider_key, city):
        if provider_key == "freetour":
            return "https://www.freetour.com/tokyo"
        return None

    monkeypatch.setattr(walking_tours, "_discover_city_url", fake_discover)
    requested = []

    def handler(request: httpx.Request) -> httpx.Response:
        requested.append(str(request.url))
        return httpx.Response(200, text=_jsonld_page("freetour.com", 2, "東京"))

    async with _client(handler) as client:
        tours, sources = await fetch_city_tours("東京", client=client)
    assert requested == ["https://www.freetour.com/tokyo"]
    assert sources[1]["status"] == "ok"
    assert len(tours) == 2


async def test_cached_tours_are_copy_safe():
    async with _client(_ok_handler) as client:
        first, _ = await fetch_city_tours("Lisbon", client=client)
        first[0]["reason"] = "mutated"
        first[0]["top_pick"] = True
        second, _ = await fetch_city_tours("Lisbon", client=client)
        assert second[0]["reason"] is None
        assert second[0]["top_pick"] is False
        second[0]["reason"] = "again"
        third, _ = await fetch_city_tours("Lisbon", client=client)
    assert third[0]["reason"] is None


async def test_empty_page_is_none_and_not_cached(monkeypatch):
    async def no_discovery(provider_key, city):
        return None

    monkeypatch.setattr(walking_tours, "_discover_city_url", no_discovery)
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.host)
        return httpx.Response(200, text="<html><body>nothing</body></html>")

    async with _client(handler) as client:
        _, sources = await fetch_city_tours("Lisbon", client=client)
        assert [s["status"] for s in sources] == ["none"] * 4
        assert [s["count"] for s in sources] == [0] * 4
        await fetch_city_tours("Lisbon", client=client)
    assert len(calls) == 8


# --- I1: discovery must not label another city's page with the user's city ---


def _discovery_handler(path_ok: str):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "www.guruwalk.com":
            if request.url.path == path_ok:
                return httpx.Response(200, text=PAGES["www.guruwalk.com"])
            return httpx.Response(404)
        return httpx.Response(404)

    return handler


async def test_discovery_of_other_city_is_rejected(monkeypatch):
    async def fake_discover(provider_key, city):
        return "https://www.guruwalk.com/lisbon"

    monkeypatch.setattr(walking_tours, "_discover_city_url", fake_discover)
    async with _client(_discovery_handler("/lisbon")) as client:
        tours, sources = await fetch_city_tours("Springfield", client=client)
    assert sources[0]["status"] == "none"
    assert tours == []
    assert not any("lisbon" in k for k in get_cache())


async def test_discovery_of_search_page_is_rejected(monkeypatch):
    async def fake_discover(provider_key, city):
        return "https://www.guruwalk.com/search"

    monkeypatch.setattr(walking_tours, "_discover_city_url", fake_discover)
    requested = []
    inner = _discovery_handler("/search")

    def handler(request):
        requested.append(request.url.path)
        return inner(request)

    async with _client(handler) as client:
        tours, sources = await fetch_city_tours("Lisbon", client=client)
    assert "/search" not in requested
    assert sources[0]["status"] == "none"


async def test_discover_city_url_rejects_denied_and_language_slugs(monkeypatch):
    def fake_search(query, max_results):
        return [
            {"href": "https://www.guruwalk.com/search"},
            {"href": "https://www.guruwalk.com/blog"},
            {"href": "https://www.guruwalk.com/es"},
            {"href": "https://www.guruwalk.com/xy"},
            {"href": "https://www.freetour.com/free-tours"},
        ]

    monkeypatch.setattr(walking_tours, "_ddgs_search", fake_search)
    assert await walking_tours._discover_city_url("guruwalk", "Search") is None


async def test_discovery_alternate_slug_sharing_a_token_is_accepted(monkeypatch):
    async def fake_discover(provider_key, city):
        return "https://www.guruwalk.com/new-york-city"

    monkeypatch.setattr(walking_tours, "_discover_city_url", fake_discover)
    async with _client(_discovery_handler("/new-york-city")) as client:
        tours, sources = await fetch_city_tours("New York", client=client)
    assert sources[0]["status"] == "ok"
    assert sources[0]["url"] == "https://www.guruwalk.com/new-york-city"
    assert all(t["city"] == "New York" for t in tours)


async def test_empty_slug_rejects_page_for_other_locality(monkeypatch):
    async def fake_discover(provider_key, city):
        if provider_key == "freetour":
            return "https://www.freetour.com/osaka"
        return None

    monkeypatch.setattr(walking_tours, "_discover_city_url", fake_discover)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=_jsonld_page("freetour.com", 2, "大阪"))

    async with _client(handler) as client:
        tours, sources = await fetch_city_tours("東京", client=client)
    assert sources[1]["status"] == "none"
    assert tours == []
    assert len(get_cache()) == 0


async def test_empty_slug_without_locality_is_rejected(monkeypatch):
    async def fake_discover(provider_key, city):
        if provider_key == "freetour":
            return "https://www.freetour.com/tokyo"
        return None

    monkeypatch.setattr(walking_tours, "_discover_city_url", fake_discover)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=PAGES["www.freetour.com"])

    async with _client(handler) as client:
        tours, sources = await fetch_city_tours("東京", client=client)
    assert sources[1]["status"] == "none"
    assert tours == []


# --- I2: per-city crawl cap ---


async def test_city_crawl_is_capped_and_slow_providers_error(monkeypatch):
    monkeypatch.setattr(walking_tours, "_CITY_CRAWL_CAP", 0.2)

    async def no_discovery(provider_key, city):
        return None

    monkeypatch.setattr(walking_tours, "_discover_city_url", no_discovery)

    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host in ("www.guruwalk.com", "freewalkingtour.com"):
            await asyncio.sleep(5)
        return _ok_handler(request)

    loop = asyncio.get_running_loop()
    start = loop.time()
    async with _client(handler) as client:
        tours, sources = await fetch_city_tours("Lisbon", client=client)
    assert loop.time() - start < 2
    assert [s["status"] for s in sources] == ["error", "ok", "error", "ok"]
    assert {t["provider_key"] for t in tours} == {"freetour", "sandemans"}
    assert not any(
        k.startswith(("walking_tours:guruwalk:", "walking_tours:freewalkingtour:"))
        for k in get_cache()
    )


async def test_city_crawl_cap_includes_discovery(monkeypatch):
    monkeypatch.setattr(walking_tours, "_CITY_CRAWL_CAP", 0.2)

    async def slow_discovery(provider_key, city):
        await asyncio.sleep(5)
        return None

    monkeypatch.setattr(walking_tours, "_discover_city_url", slow_discovery)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404)

    loop = asyncio.get_running_loop()
    start = loop.time()
    async with _client(handler) as client:
        tours, sources = await fetch_city_tours("Lisbon", client=client)
    assert loop.time() - start < 2
    assert [s["status"] for s in sources] == ["error", "error", "none", "none"]
    assert tours == []
    assert len(get_cache()) == 0


# --- M2: cache hits are relabelled with the requested city ---


async def test_cache_hit_rewrites_city_label():
    async with _client(_ok_handler) as client:
        await fetch_city_tours("lisbon", client=client)
        tours, sources = await fetch_city_tours("Lisbon", client=client)
    assert tours and all(t["city"] == "Lisbon" for t in tours)
    assert all(s["city"] == "Lisbon" for s in sources)


# --- M7: blocking responses are visible in logs ---


async def test_blocking_statuses_log_warning(monkeypatch, caplog):
    async def no_discovery(provider_key, city):
        return None

    monkeypatch.setattr(walking_tours, "_discover_city_url", no_discovery)
    codes = {
        "www.guruwalk.com": 403,
        "www.freetour.com": 429,
        "freewalkingtour.com": 503,
        "www.neweuropetours.eu": 404,
    }

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(codes[request.url.host])

    caplog.set_level(logging.DEBUG, logger="app.services.walking_tours")
    async with _client(handler) as client:
        await fetch_city_tours("Lisbon", client=client)
    warnings = [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]
    for key, code in (("guruwalk", 403), ("freetour", 429), ("freewalkingtour", 503)):
        assert any(key in m and str(code) in m for m in warnings), warnings
    assert not any("sandemans" in m for m in warnings)
