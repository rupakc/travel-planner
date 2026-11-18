"""Crawler read API → Results sections (docs/Crawler-Data.md).

The crawler is always an httpx.MockTransport here (conftest refuses real
network). Covers: the client (off, breaker, timeouts, cache, pinned TLS),
forex rates, the emergency card (no unverified phone shown as fact),
visa/entry facts (Wikipedia only as a cross-check), public holidays, typical
fares, /config, /health, and that flag-off / crawler-down runs are
identical to today's."""

import asyncio
import copy
import json
from datetime import date

import httpx
import pytest

from app.agents.emergency_card_agent import EmergencyCardAgent
from app.agents.events_agent import EventsAgent
from app.agents.forex_agent import ForexAgent
from app.agents.pricing_advisor_agent import PricingAdvisorAgent
from app.agents.visa_agent import VisaAgent
from app.core.config import settings
from app.schemas.request import TravelSearchRequest
from app.services import crawler_client, crawler_facts
from app.services.verification import attach_verification

AGENTS_DIR = settings.agents_dir

OGL = {
    "class": "open",
    "spdx": "OGL-UK-3.0",
    "attribution": "Contains public sector information licensed under the Open Government Licence v3.0",
    "url": "https://www.nationalarchives.gov.uk/doc/open-government-licence/version/3/",
}
CC_BY_SA = {
    "class": "share_alike",
    "spdx": "CC-BY-SA-4.0",
    "attribution": "Wikipedia contributors",
    "url": "https://creativecommons.org/licenses/by-sa/4.0/",
}
ECB_LICENCE = {
    "class": "open",
    "spdx": None,
    "attribution": "Source: European Central Bank",
    "url": "https://www.ecb.europa.eu/services/disclaimer/html/index.en.html",
}
SOURCES = {
    "govuk-world-orgs": "GOV.UK worldwide organisations",
    "govuk-medical-lists": "FCDO doctors and medical facilities worldwide list",
    "fcdo-content-api": "FCDO travel advice",
    "enwiki-dump": "English Wikipedia",
    "ecb-eurofxref": "European Central Bank reference rates",
    "openholidays": "OpenHolidays API",
    "travelpayouts": "Travelpayouts",
}


def item(kind, data, *, source, licence=OGL, conflict=False, url=None):
    return {
        "id": str(abs(hash(json.dumps(data, sort_keys=True))) % 10**9),
        "kind": kind,
        "schema": f"{kind}@1",
        "title": data.get("name") or kind,
        "excerpt": None,
        "data": data,
        "place_ids": [],
        "licence": licence,
        "provenance": [
            {
                "source_id": source,
                "url": url or f"https://example.org/{source}",
                "captured_at": "2026-11-10T08:00:00Z",
                "extractor": {
                    "version": "1",
                    "method": "adapter",
                    "model": None,
                    "prompt_hash": None,
                    "run_id": None,
                },
            }
        ],
        "conflict": conflict,
        "use_policy": {"index": "full", "serve": "full"},
        "updated_at": "2026-11-10T08:00:00Z",
        "score": 1.0,
    }


def fx_point(base, quote, rate, day="2026-11-17"):
    return {
        "series_key": f"fx:{base}:{quote}",
        "observed_at": f"{day}T16:00:00Z",
        "value": {
            "base_currency": base,
            "quote_currency": quote,
            "rate": rate,
            "rate_date": day,
            "publisher": "European Central Bank",
            "source_url": "https://www.ecb.europa.eu/stats/eurofxref/",
        },
        "source_id": "ecb-eurofxref",
        "licence": ECB_LICENCE,
    }


class FakeCrawler:
    """A tiny /v1 server: search filters by kind and all query words."""

    def __init__(self, items=(), observations=None):
        self.items = list(items)
        self.observations = observations or {}
        self.calls: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.calls.append(request)
        assert (
            request.headers["Authorization"] == "Bearer voyager.test-secret-0123456789"
        )
        path, params = request.url.path, request.url.params
        if path == "/v1/sources":
            return httpx.Response(
                200,
                json={
                    "items": [
                        {
                            "source_id": k,
                            "name": v,
                            "category": "x",
                            "source_class": "official",
                            "licence": OGL,
                            "method": "api",
                            "enabled": True,
                        }
                        for k, v in SOURCES.items()
                    ]
                },
            )
        if path == "/v1/stats":
            return httpx.Response(
                200,
                json={
                    "sources_enabled": 3,
                    "records_active": 10,
                    "entities_active": 0,
                    "changes_seq_max": 1,
                    "generated_at": "2026-11-18T00:00:00Z",
                },
            )
        if path == "/v1/observations":
            return httpx.Response(
                200, json={"items": self.observations.get(params["series"], [])}
            )
        if path == "/v1/search":
            kind = params.get("kind")
            words = [w.lower() for w in (params.get("q") or "").split()]
            found = [
                i
                for i in self.items
                if i["kind"] == kind
                and all(w in json.dumps(i["data"]).lower() for w in words)
            ]
            return httpx.Response(200, json={"items": found, "next_cursor": None})
        return httpx.Response(404, json={"error": "not_found", "message": "x"})

    def paths(self):
        return [c.url.path for c in self.calls]


@pytest.fixture
def crawler_on(monkeypatch):
    monkeypatch.setattr(settings, "crawler_enabled", True)
    monkeypatch.setattr(settings, "crawler_api_url", "https://10.142.0.3:8443")
    monkeypatch.setattr(settings, "crawler_api_token", "voyager.test-secret-0123456789")
    monkeypatch.setattr(settings, "crawler_ca_pem", "")
    monkeypatch.setattr(settings, "crawler_ca_file", "")
    crawler_client.reset()

    def install(handler):
        monkeypatch.setattr(crawler_client, "_transport", httpx.MockTransport(handler))
        return handler

    return install


@pytest.fixture(scope="module", autouse=True)
def _nationalities():
    from app.db.seed_nationalities import seed

    seed()


def run(coro):
    return asyncio.run(coro)


def req(**kw):
    base = {
        "origin": "London, United Kingdom",
        "destination": "Tokyo, Japan",
        "departure_date": "2026-12-28",
        "return_date": "2027-01-04",
        "nationality": "British",
    }
    base.update(kw)
    return TravelSearchRequest(**base)


def stub_execute(agent, reply, prompts):
    async def execute(prompt, locale=None):
        prompts.append(prompt)
        return copy.deepcopy(reply)

    agent.execute = execute


def down(request):
    raise httpx.ConnectError("no route to host")


# ── client ───────────────────────────────────────────────────────────────


class TestClient:
    def test_off_by_default_sends_nothing(self):
        assert not crawler_client.configured()
        assert run(crawler_client.get_json("/v1/stats")) is None
        assert run(crawler_client.health()) == {"configured": False, "ok": False}

    def test_flag_alone_is_not_enough(self, monkeypatch):
        monkeypatch.setattr(settings, "crawler_enabled", True)
        monkeypatch.setattr(settings, "crawler_api_url", "")
        assert not crawler_client.configured()

    def test_error_opens_the_breaker(self, crawler_on):
        calls = []

        def boom(request):
            calls.append(request)
            return httpx.Response(503, json={"error": "unavailable"})

        crawler_on(boom)
        assert run(crawler_client.get_json("/v1/stats")) is None
        assert crawler_client.breaker_open()
        # Fails fast: no second request while the breaker is open
        assert run(crawler_client.get_json("/v1/sources")) is None
        assert len(calls) == 1

    def test_timeout_and_connection_errors_never_raise(self, crawler_on):
        def slow(request):
            raise httpx.ReadTimeout("slow", request=request)

        crawler_on(slow)
        assert run(crawler_client.search("embassy", "Japan")) is None
        crawler_client.reset()
        crawler_on(down)
        assert run(crawler_client.observations("fx:EUR:USD")) is None
        assert run(crawler_client.health()) == {"configured": True, "ok": False}

    def test_rate_limit_backs_off_for_retry_after(self, crawler_on):
        crawler_on(lambda r: httpx.Response(429, headers={"Retry-After": "7"}, json={}))
        assert run(crawler_client.get_json("/v1/stats")) is None
        assert crawler_client.breaker_open()

    def test_404_is_an_answer_not_an_outage(self, crawler_on):
        crawler_on(lambda r: httpx.Response(404, json={"error": "not_found"}))
        assert run(crawler_client.get_json("/v1/entities/x")) is None
        assert not crawler_client.breaker_open()

    def test_answers_are_cached(self, crawler_on):
        fake = crawler_on(FakeCrawler())
        run(crawler_client.get_json("/v1/stats"))
        run(crawler_client.get_json("/v1/stats"))
        assert fake.paths() == ["/v1/stats"]

    def test_bad_pinned_certificate_fails_closed(self, crawler_on, monkeypatch):
        monkeypatch.setattr(
            settings, "crawler_ca_pem", "-----BEGIN CERTIFICATE-----\nnope\n"
        )
        fake = crawler_on(FakeCrawler())
        assert run(crawler_client.get_json("/v1/stats")) is None
        assert fake.calls == []  # never sent without a usable pin

    def test_health_ok_when_answering(self, crawler_on):
        crawler_on(FakeCrawler())
        assert run(crawler_client.health()) == {"configured": True, "ok": True}


# ── forex ────────────────────────────────────────────────────────────────

AI_FOREX = {
    "local_currency": {"name": "Japanese Yen", "code": "JPY", "symbol": "¥"},
    "exchange_rates": [
        {
            "from_currency": "USD",
            "to_currency": "JPY",
            "rate": 99.9,
            "description": "1 USD = 99.9 JPY",
            "trend": "t",
        },
        {
            "from_currency": "EUR",
            "to_currency": "JPY",
            "rate": 111.1,
            "description": "1 EUR = 111.1 JPY",
            "trend": "t",
        },
        {
            "from_currency": "GBP",
            "to_currency": "JPY",
            "rate": 123.4,
            "description": "1 GBP = 123.4 JPY",
            "trend": "t",
        },
    ],
    "money_tips": [],
}

FX = {
    "fx:EUR:JPY": [
        fx_point("EUR", "JPY", 160.0, "2026-11-16"),
        fx_point("EUR", "JPY", 161.5),
    ],
    "fx:EUR:USD": [fx_point("EUR", "USD", 1.08)],
    "fx:EUR:GBP": [fx_point("EUR", "GBP", 0.85)],
}


def forex_run(monkeypatch, request):
    searches, prompts = [], []

    async def fake_tool(name, args):
        searches.append(args["query"])
        return "snippet"

    monkeypatch.setattr("app.agents.forex_agent.execute_tool", fake_tool)
    agent = ForexAgent(AGENTS_DIR)
    stub_execute(agent, AI_FOREX, prompts)
    result = run(agent.run(request))
    return result, prompts[0], searches


class TestForex:
    def test_published_rates_replace_the_models_numbers(self, crawler_on, monkeypatch):
        crawler_on(FakeCrawler(observations=FX))
        result, prompt, _ = forex_run(monkeypatch, req())
        rates = {r["from_currency"]: r for r in result["exchange_rates"]}
        assert rates["EUR"]["rate"] == 161.5  # the latest point
        assert rates["USD"]["rate"] == round(161.5 / 1.08, 2)  # crossed via EUR
        assert rates["GBP"]["rate"] == round(161.5 / 0.85, 2)
        src = rates["EUR"]["rate_source"]
        assert src["name"] == "European Central Bank reference rates"
        assert src["as_of"] == "2026-11-17"
        assert src["attribution"] == "Source: European Central Bank"
        assert src["url"] == "https://www.ecb.europa.eu/stats/eurofxref/"
        assert result["crawler_sources"]
        assert "REFERENCE DATA" in prompt and "1 EUR = 161.5 JPY" in prompt

    def test_verification_names_the_publisher(self, crawler_on, monkeypatch):
        crawler_on(FakeCrawler(observations=FX))
        result, _, _ = forex_run(monkeypatch, req())
        v = attach_verification("forex", result, req())["verification"]
        assert v["level"] == "partial"
        assert "European Central Bank" in v["checks"][0]["detail"]

    def test_flag_off_and_crawler_down_are_identical_to_today(
        self, crawler_on, monkeypatch
    ):
        off_result, off_prompt, off_searches = forex_run(monkeypatch, req())
        assert off_result == AI_FOREX
        crawler_on(down)
        down_result, down_prompt, down_searches = forex_run(monkeypatch, req())
        assert down_result == off_result
        assert down_prompt == off_prompt
        assert down_searches == off_searches

    def test_crawler_without_the_pair_changes_nothing(self, crawler_on, monkeypatch):
        crawler_on(FakeCrawler(observations={}))
        result, prompt, _ = forex_run(monkeypatch, req())
        assert result == AI_FOREX
        assert "REFERENCE DATA" not in prompt

    def test_inverse_series(self, crawler_on):
        crawler_on(
            FakeCrawler(observations={"fx:CAD:USD": [fx_point("CAD", "USD", 0.5)]})
        )
        got = run(crawler_facts.fx_rate("USD", "CAD"))
        assert got["rate"] == 2.0


# ── emergency card ───────────────────────────────────────────────────────

AI_CARD = {
    "emergency_numbers": {
        "police": "110",
        "ambulance": "119",
        "fire": "119",
        "tourist_police": None,
    },
    "embassy": {
        "name": "British Embassy Tokyo",
        "address": "invented address",
        "phone": "+81-3-0000-0000",
        "emergency_after_hours": "+81-3-9999-9999",
        "website": "https://www.gov.uk/world/japan",
        "hours": "9-5",
    },
    "hospitals": [
        {"name": "St. Luke's", "phone": "+81-3-1111-1111", "address": "Tsukiji"}
    ],
    "local_phrases": [],
    "local_laws": [],
    "home_country_note": None,
}

UK_EMBASSY_TOKYO = item(
    "embassy",
    {
        "name": "British Embassy Tokyo",
        "mission_type": "embassy",
        "of_country": "United Kingdom",
        "of_country_code": "GB",
        "country": "Japan",
        "country_code": "JP",
        "city": "Tokyo",
        "address": "No 1 Ichiban-cho, Chiyoda-ku, Tokyo 102-8381",
        "phones": [
            {"type": "main", "number": "+81 (0)3 5211 1100"},
            {"type": "emergency", "number": "+44 20 7008 5000"},
        ],
        "website_url": "https://www.gov.uk/world/organisations/british-embassy-tokyo",
        "source_url": "https://www.gov.uk/world/organisations/british-embassy-tokyo",
        "as_of": "2026-11-01",
    },
    source="govuk-world-orgs",
)
JP_NUMBERS_OFFICIAL = item(
    "emergency_numbers",
    {
        "country": "Japan",
        "country_code": "JP",
        "applies_to": "country",
        "numbers": [
            {"service": "police", "number": "110"},
            {"service": "ambulance", "number": "119"},
            {"service": "fire", "number": "119"},
        ],
        "source_url": "https://www.gov.uk/foreign-travel-advice/japan/getting-help",
        "as_of": "2026-10-20",
    },
    source="fcdo-content-api",
)
JP_NUMBERS_WIKI = item(
    "emergency_numbers",
    {
        "country": "Japan",
        "country_code": "JP",
        "numbers": [
            {"service": "police", "number": "110"},
            {"service": "general", "number": "119"},
        ],
    },
    source="enwiki-dump",
    licence=CC_BY_SA,
)
JP_MEDICAL = [
    item(
        "medical_facility",
        {
            "name": "Tokyo Medical and Surgical Clinic",
            "country": "Japan",
            "country_code": "JP",
            "city": "Tokyo",
            "address": "Shiba-koen, Minato-ku",
            "phones": [{"number": "+81 3 3436 3028"}],
            "list_title": "List of medical facilities in Japan",
            "list_updated": "2024-05-02",
        },
        source="govuk-medical-lists",
    ),
    item(
        "medical_facility",
        {
            "name": "Osaka Clinic",
            "country": "Japan",
            "country_code": "JP",
            "city": "Osaka",
            "phones": [{"number": "+81 6 0000 0000"}],
            "list_updated": "2024-05-02",
        },
        source="govuk-medical-lists",
    ),
]


def card_run(request, reply=AI_CARD):
    prompts = []
    agent = EmergencyCardAgent(AGENTS_DIR)
    stub_execute(agent, reply, prompts)
    return run(agent.run(request))


def phones_in(card) -> list[str]:
    out = []
    emb = card.get("embassy") or {}
    out += [emb.get("phone"), emb.get("emergency_after_hours")]
    out += [h.get("phone") for h in card.get("hospitals") or []]
    return [p for p in out if p]


class TestEmergencyCard:
    def test_official_embassy_replaces_the_models(self, crawler_on):
        crawler_on(FakeCrawler([UK_EMBASSY_TOKYO, JP_NUMBERS_OFFICIAL, *JP_MEDICAL]))
        card = card_run(req())
        emb = card["embassy"]
        assert emb["phone"] == "+81 (0)3 5211 1100"
        assert emb["emergency_after_hours"] == "+44 20 7008 5000"
        assert emb["address"].startswith("No 1 Ichiban-cho")
        assert emb["verified"] is True
        assert emb["source"]["name"] == "GOV.UK worldwide organisations"
        assert emb["source"]["attribution"] == OGL["attribution"]
        assert emb["source"]["as_of"] == "2026-11-01"
        # Numbers from the official, open-licence record (with its source)
        assert card["emergency_numbers_source"]["source_id"] == "fcdo-content-api"
        # Official medical list, in the trip's city first, with its age
        med = card["medical_facilities"]
        assert med[0]["name"] == "Tokyo Medical and Surgical Clinic"
        assert med[0]["list_updated"] == "2024-05-02"
        assert [m["name"] for m in med] == ["Tokyo Medical and Surgical Clinic"]
        assert card["medical_in_city"] is True

    def test_no_invented_phone_is_shown_as_fact(self, crawler_on):
        # Crawler answers but has no embassy of India in Japan: the model's
        # embassy and hospital phone numbers are dropped, not shown
        crawler_on(FakeCrawler([UK_EMBASSY_TOKYO, JP_NUMBERS_OFFICIAL]))
        card = card_run(req(nationality="Indian"))
        assert phones_in(card) == []
        assert card["embassy"]["phone_unverified"] is True
        assert "not verified" in card["embassy"]["note"]
        assert card["embassy"]["website"] == AI_CARD["embassy"]["website"]
        assert card["hospitals"][0]["phone_unverified"] is True
        assert card["hospitals"][0]["name"] == "St. Luke's"
        assert "medical_facilities" not in card

    def test_share_alike_numbers_are_never_merged(self, crawler_on):
        crawler_on(FakeCrawler([JP_NUMBERS_WIKI]))
        card = card_run(req())
        assert card["emergency_numbers"] == AI_CARD["emergency_numbers"]
        assert "emergency_numbers_source" not in card
        official = card["official_numbers"]
        assert official["numbers"]["ambulance"] == "119"  # "general" fills it
        assert official["source"]["licence"] == "share_alike"
        assert official["source"]["attribution"] == "Wikipedia contributors"

    def test_conflicting_numbers_are_not_merged(self, crawler_on):
        conflicted = copy.deepcopy(JP_NUMBERS_OFFICIAL)
        conflicted["conflict"] = True
        crawler_on(FakeCrawler([conflicted]))
        card = card_run(req())
        assert card["emergency_numbers"] == AI_CARD["emergency_numbers"]
        assert card["official_numbers"]["source"]["conflict"] is True

    def test_flag_off_and_crawler_down_are_identical_to_today(self, crawler_on):
        assert card_run(req()) == AI_CARD
        crawler_on(down)
        assert card_run(req()) == AI_CARD

    def test_multi_city_per_stop(self, crawler_on):
        crawler_on(FakeCrawler([UK_EMBASSY_TOKYO, JP_NUMBERS_OFFICIAL, *JP_MEDICAL]))
        reply = {
            "cities": [
                {**copy.deepcopy(AI_CARD), "city": "Tokyo"},
                {**copy.deepcopy(AI_CARD), "city": "Osaka"},
            ]
        }
        card = card_run(
            req(
                destinations=["Tokyo, Japan", "Osaka, Japan"],
                destination="Osaka, Japan",
            ),
            reply,
        )
        tokyo, osaka = card["cities"]
        assert tokyo["embassy"]["verified"] and osaka["embassy"]["verified"]
        assert osaka["medical_facilities"][0]["name"] == "Osaka Clinic"

    def test_verification_credits_the_official_numbers(self, crawler_on):
        crawler_on(FakeCrawler([UK_EMBASSY_TOKYO, JP_NUMBERS_OFFICIAL]))
        card = card_run(req())
        v = attach_verification("emergency_card", card, req())["verification"]
        assert v["level"] == "verified"
        assert "official source" in v["checks"][0]["detail"]


# ── visa ─────────────────────────────────────────────────────────────────

AI_VISA = {
    "requirement": {"visa_type": "visa-required", "max_stay_days": 30},
    "vaccinations": {"required": [], "recommended": []},
    "customs": {},
}
JP_RULE = item(
    "visa_rule",
    {
        "destination_country": "Japan",
        "destination_country_code": "JP",
        "nationality": "United Kingdom",
        "nationality_code": "GB",
        "purpose": "tourism",
        "visa_type": "visa_free",
        "max_stay_days": 90,
        "source_url": "https://www.gov.uk/foreign-travel-advice/japan/entry-requirements",
        "as_of": "2026-10-01",
    },
    source="fcdo-content-api",
)
JP_ADVISORY = item(
    "advisory",
    {
        "country": "Japan",
        "country_code": "JP",
        "issuer": "UK Foreign, Commonwealth & Development Office",
        "issuer_country_code": "GB",
        "level_label": "See our travel advice before travelling",
        "summary": "Earthquakes and typhoons occur.",
        "updated_date": "2026-11-02",
        "source_url": "https://www.gov.uk/foreign-travel-advice/japan",
    },
    source="fcdo-content-api",
)
JP_WIKI = item(
    "visa_reference",
    {
        "nationality": "United Kingdom",
        "nationality_code": "GB",
        "destination_country": "Japan",
        "destination_country_code": "JP",
        "requirement": "visa_free",
        "allowed_stay_text": "90 days",
        "provenance": "wikipedia",
        "source_url": "https://en.wikipedia.org/wiki/Visa_requirements_for_British_citizens",
    },
    source="enwiki-dump",
    licence=CC_BY_SA,
)


def visa_run(request):
    prompts = []
    agent = VisaAgent(AGENTS_DIR)
    stub_execute(agent, AI_VISA, prompts)
    return run(agent.run(request)), prompts[0]


class TestVisa:
    def test_official_rules_and_advice_with_wikipedia_only_as_cross_check(
        self, crawler_on
    ):
        crawler_on(FakeCrawler([JP_RULE, JP_ADVISORY, JP_WIKI]))
        result, prompt = visa_run(req())
        # The requirement itself is never overwritten
        assert result["requirement"] == AI_VISA["requirement"]
        (entry,) = result["official_entry"]
        assert entry["country_code"] == "JP"
        assert entry["rules"][0]["visa_type"] == "visa_free"
        assert entry["rules"][0]["source"]["url"].startswith("https://www.gov.uk/")
        assert entry["advisories"][0]["updated"] == "2026-11-02"
        cc = entry["cross_check"]
        assert cc["agrees"] is False
        assert cc["source"]["licence"] == "share_alike"
        # Official facts reach the model; Wikipedia (share-alike) never does
        assert "visa_free" in prompt and "REFERENCE DATA" in prompt
        assert "wikipedia" not in prompt.lower()

    def test_verification_compares_with_the_official_rule(self, crawler_on):
        crawler_on(FakeCrawler([JP_RULE]))
        result, _ = visa_run(req())
        v = attach_verification("visa", result, req())["verification"]
        assert v["level"] == "conflict"
        assert "official source" in v["summary"]

    def test_flag_off_and_crawler_down_are_identical_to_today(self, crawler_on):
        off = visa_run(req())
        crawler_on(down)
        assert visa_run(req()) == off
        assert off[0] == AI_VISA


# ── events and holidays ──────────────────────────────────────────────────


def holiday(name, start, end=None, licence=OGL, source="openholidays"):
    return item(
        "public_holiday",
        {
            "name": name,
            "type": "public",
            "start_date": start,
            "end_date": end or start,
            "country": "Japan",
            "country_code": "JP",
            "nationwide": True,
        },
        source=source,
        licence=licence,
    )


class TestHolidays:
    def test_holidays_during_the_trip_only(self, crawler_on):
        crawler_on(
            FakeCrawler(
                [
                    holiday("New Year's Day", "2027-01-01", licence=CC_BY_SA),
                    holiday("Emperor's Birthday", "2026-02-23"),
                    holiday("Coming of Age Day", "2027-01-11"),
                ]
            )
        )
        got = run(
            crawler_facts.public_holidays("JP", date(2026, 12, 28), date(2027, 1, 4))
        )
        assert [h["name"] for h in got] == ["New Year's Day"]

    def test_events_section_carries_attributed_holidays(self, crawler_on):
        crawler_on(
            FakeCrawler(
                [
                    holiday("New Year's Day", "2027-01-01", licence=CC_BY_SA),
                    holiday("Bank Holiday", "2026-12-31", source="govuk-world-orgs"),
                ]
            )
        )
        prompts = []
        agent = EventsAgent(AGENTS_DIR)
        stub_execute(agent, {"results": []}, prompts)
        result = run(agent.run(req()))
        names = [h["name"] for h in result["public_holidays"]]
        assert names == ["Bank Holiday", "New Year's Day"]
        wiki = result["public_holidays"][1]["source"]
        assert wiki["name"] == "OpenHolidays API" and wiki["licence"] == "share_alike"
        # Share-alike holidays are shown, never handed to the model
        assert "Bank Holiday" in prompts[0]
        assert "New Year" not in prompts[0]

    def test_flag_off_identical(self):
        prompts = []
        agent = EventsAgent(AGENTS_DIR)
        stub_execute(agent, {"results": []}, prompts)
        assert run(agent.run(req())) == {"results": []}
        assert "REFERENCE DATA" not in prompts[0]


# ── pricing advisor ──────────────────────────────────────────────────────


class TestTypicalFares:
    def test_labelled_cached_fare(self, crawler_on):
        point = {
            "series_key": "fare:LHR:HND:2026-12",
            "observed_at": "2026-11-15T00:00:00Z",
            "value": {
                "origin_iata": "LHR",
                "destination_iata": "HND",
                "month": "2026-12",
                "price": 612,
                "currency": "GBP",
                "found_at": "2026-11-14T10:00:00Z",
            },
            "source_id": "travelpayouts",
            "licence": {
                "class": "api_terms",
                "spdx": None,
                "attribution": "Travelpayouts",
                "url": None,
            },
        }
        fake = FakeCrawler(observations={"fare:LHR:HND:2026-12": [point]})
        crawler_on(fake)
        prompts = []
        agent = PricingAdvisorAgent(AGENTS_DIR)
        stub_execute(agent, {"trend_data": [1]}, prompts)
        request = req(origin="LHR", destination="HND")
        result = run(agent.run(request))
        assert result["typical_fares"]["price"] == 612.0
        assert result["typical_fares"]["source"]["as_of"] == "2026-11-14"
        assert "not a live price" in prompts[0]


# ── /config and /health ──────────────────────────────────────────────────


class TestEndpoints:
    def test_config_reports_the_feature(self, client, crawler_on):
        assert client.get("/api/config").json()["features"]["crawler_data"] is True

    def test_config_off_by_default(self, client):
        assert client.get("/api/config").json()["features"]["crawler_data"] is False

    def test_health_reports_crawler(self, client, crawler_on):
        crawler_on(FakeCrawler())
        assert client.get("/health").json()["crawler"] == {
            "configured": True,
            "ok": True,
        }

    def test_health_off(self, client):
        assert client.get("/health").json()["crawler"] == {
            "configured": False,
            "ok": False,
        }
