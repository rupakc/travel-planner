"""Place facts section (docs/Place-Facts.md).

The crawler is always an httpx.MockTransport (conftest refuses real network)
and the model is a patched ``execute``. Covers: the client helper, place
resolution (city, region, country; multi-city), crawler facts with their
sources (our own sentences only, value_lang, country near-duplicates),
licence rules for the model prompt, AI facts only for empty groups (never
with a source or link; the fun group is always AI), the static-first fallback, the stream
(Phase 0 crawler yield, AI yield, flag off), the route, /config and the
verification chip."""

import asyncio
import copy
import json
from datetime import date
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest

from app.agents.place_facts_agent import PlaceFactsAgent, crawler_section
from app.core.config import settings
from app.schemas.request import TravelSearchRequest
from app.services import crawler_client
from app.services import place_facts as pf
from app.services.verification import verify_section

TOKEN = "voyager.test-secret-0123456789"
CC0 = {
    "class": "open",
    "spdx": "CC0-1.0",
    "attribution": "Wikidata (CC0 1.0)",
    "url": "https://creativecommons.org/publicdomain/zero/1.0/",
}
CC_BY_SA = {
    "class": "share_alike",
    "spdx": "CC-BY-SA-4.0",
    "attribution": "Wikipedia contributors (CC BY-SA 4.0)",
    "url": "https://creativecommons.org/licenses/by-sa/4.0/",
}
WIKIDATA = {
    "source_id": "od-wikidata-entitydata",
    "url": "https://www.wikidata.org/wiki/Q64#P571",
    "name": "Wikidata",
    "publisher": "Wikidata contributors (Wikimedia Foundation)",
    "source_class": "reference",
    "sourced": "yes",
}

BERLIN = {
    "geonames_id": 2950159,
    "wikidata_qid": "Q64",
    "admin_level": "admin1",
    "country": "DE",
    "name": "Berlin",
    "name_lang": "en",
}
GERMANY = {
    "geonames_id": 2921044,
    "wikidata_qid": "Q183",
    "admin_level": "country",
    "country": "DE",
    "name": "Germany",
    "name_lang": "en",
}
BAVARIA = {
    "geonames_id": 2951839,
    "wikidata_qid": "Q980",
    "admin_level": "admin1",
    "country": "DE",
    "name": "Bavaria",
    "name_lang": "en",
}


def fact(
    fid,
    place,
    fact_type,
    text,
    *,
    licence=CC0,
    llm_ok=True,
    origin="templated",
    lang="en",
    text_en=None,
    source=WIKIDATA,
    blocked=False,
    quantity=None,
    confidence="structured",
    **extra,
):
    return {
        "id": str(fid),
        "place": place,
        "fact_type": fact_type,
        "text": text,
        "lang": lang,
        "text_en": text_en,
        "text_origin": origin,
        "llm_ok": llm_ok,
        "date_ref": None,
        "quantity": quantity,
        "source": source,
        "licence": licence,
        "as_of": "2026-11-20",
        "confidence": confidence,
        "ai_bot_blocked": blocked,
        "updated_at": "2026-11-20T03:00:00Z",
        **extra,
    }


BERLIN_FACTS = [
    fact(1, BERLIN, "historical", "Berlin was founded in 1237."),
    fact(2, BERLIN, "little_known", "Berlin is twinned with Los Angeles."),
    fact(
        3,
        BERLIN,
        "popular",
        "Berlin's motto is \u201cBerlin bleibt doch Berlin\u201d.",
        value_lang="de",
    ),
]
COUNTRY_FACTS = [
    fact(10, GERMANY, "popular", "Germany has about 83 million people."),
    fact(11, BAVARIA, "unbelievable", "Bavaria's Zugspitze is Germany's highest peak."),
    fact(
        12,
        {"geonames_id": None, "wikidata_qid": None, "country": "DE", "name": None},
        "historical",
        "Germany was reunified in 1990.",
        source={"source_id": "factbook-json", "name": "CIA World Factbook"},
    ),
    fact(13, BERLIN, "popular", "Berlin is Germany's capital."),
]


class FakeCrawler:
    def __init__(self, by_geo=None, by_country=None, status=200):
        self.by_geo = by_geo or {}
        self.by_country = by_country or {}
        self.status = status
        self.calls: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.calls.append(request)
        assert request.headers["Authorization"] == f"Bearer {TOKEN}"
        if self.status != 200:
            return httpx.Response(self.status, json={"error": "x"})
        if request.url.path != "/v1/facts":
            return httpx.Response(404, json={"error": "not_found"})
        p = request.url.params
        if "geonames_id" in p:
            items = self.by_geo.get(int(p["geonames_id"]), [])
        elif "wikidata_qid" in p:
            items = []
        elif "country" in p:
            items = self.by_country.get(p["country"], [])
        else:
            return httpx.Response(400, json={"error": "bad_request"})
        return httpx.Response(200, json={"items": items, "next_cursor": None})

    def params(self):
        return [dict(c.url.params) for c in self.calls]


@pytest.fixture
def crawler_on(monkeypatch):
    monkeypatch.setattr(settings, "crawler_enabled", True)
    monkeypatch.setattr(settings, "crawler_api_url", "https://10.142.0.3:8443")
    monkeypatch.setattr(settings, "crawler_api_token", TOKEN)
    monkeypatch.setattr(settings, "crawler_ca_pem", "")
    monkeypatch.setattr(settings, "crawler_ca_file", "")
    crawler_client.reset()

    def install(handler):
        monkeypatch.setattr(crawler_client, "_transport", httpx.MockTransport(handler))
        return handler

    return install


@pytest.fixture
def berlin_crawler(crawler_on):
    return crawler_on(
        FakeCrawler({2950159: BERLIN_FACTS}, {"DE": BERLIN_FACTS + COUNTRY_FACTS})
    )


def req(**kw):
    base = {
        "origin": "London, United Kingdom",
        "destination": "Berlin, Germany",
        "departure_date": date(2027, 5, 1),
        "return_date": date(2027, 5, 6),
        "nationality": "British",
    }
    base.update(kw)
    return TravelSearchRequest(**base)


def run(coro):
    return asyncio.run(coro)


def facts_of(section, key):
    place = next(p for p in section["places"] if p["key"] == key)
    return place["groups"]


def all_facts(section):
    return [
        f for p in section["places"] for group in p["groups"].values() for f in group
    ]


def stub_model(monkeypatch, result):
    mock = AsyncMock(return_value=copy.deepcopy(result))
    monkeypatch.setattr(PlaceFactsAgent, "execute", mock)
    return mock


# ── client ────────────────────────────────────────────────────────────


class TestClient:
    def test_off_sends_nothing(self):
        assert run(crawler_client.place_facts(geonames_id=2950159)) is None

    def test_filters_and_validation(self, berlin_crawler):
        got = run(crawler_client.place_facts(geonames_id=2950159))
        assert [i["id"] for i in got] == ["1", "2", "3"]
        assert berlin_crawler.params()[0]["geonames_id"] == "2950159"
        # no filter, bad values: no request at all
        for kw in (
            {},
            {"geonames_id": 0},
            {"geonames_id": True},
            {"country": "Germany"},
            {"wikidata_qid": "64"},
            {"country": "DE", "fact_type": "boring"},
        ):
            assert run(crawler_client.place_facts(**kw)) is None
        assert len(berlin_crawler.calls) == 1
        assert run(crawler_client.place_facts(wikidata_qid="q64")) == []
        assert berlin_crawler.params()[-1]["wikidata_qid"] == "Q64"

    def test_down_is_none_and_opens_the_breaker(self, crawler_on):
        fake = crawler_on(FakeCrawler(status=503))
        assert run(crawler_client.place_facts(country="DE")) is None
        assert run(crawler_client.place_facts(country="FR")) is None
        assert len(fake.calls) == 1  # breaker open

    def test_older_crawler_without_the_endpoint(self, crawler_on):
        crawler_on(lambda r: httpx.Response(404, json={"error": "not_found"}))
        assert run(crawler_client.place_facts(country="DE")) is None


# ── places ────────────────────────────────────────────────────────────


class TestScopes:
    def test_city_region_country(self):
        scopes = pf.scopes_for(req(destination="Portland, Oregon"))
        assert [(s.scope, s.name, s.country) for s in scopes] == [
            ("city", "Portland", "US"),
            ("region", "Oregon", "US"),
            ("country", "United States", "US"),
        ]
        assert scopes[0].geonames_id == 5746545

    def test_multi_city_shares_the_country(self):
        r = req(
            destination="Paris, France", destinations=["Paris, France", "Lyon, France"]
        )
        keys = [s.key for s in pf.scopes_for(r)]
        assert keys.count("country:FR") == 1
        assert keys[0] == "city:2988507"
        assert any(k.startswith("city:") and k != "city:2988507" for k in keys)

    def test_region_with_the_city_name_is_one_place(self):
        keys = [s.key for s in pf.scopes_for(req())]
        assert keys == ["city:2950159", "country:DE"]

    def test_a_hint_destination_gets_its_geonames_id_and_region(self):
        # resolve_place answers Kyoto from hints.json without a GeoNames id
        scopes = pf.scopes_for(req(destination="Kyoto, Japan"))
        assert [(s.key, s.name) for s in scopes] == [
            ("city:1857910", "Kyoto"),
            ("region:JP.22", "Kyoto"),  # the prefecture is its own place
            ("country:JP", "Japan"),
        ]
        assert scopes[0].geonames_id == 1857910

    def test_a_hint_without_a_town_is_a_place(self):
        scopes = pf.scopes_for(req(destination="Bali"))
        assert [(s.scope, s.name, s.geonames_id) for s in scopes] == [
            ("place", "Bali", None),
            ("country", "Indonesia", None),
        ]

    def test_a_country_destination_is_only_the_country(self):
        for typed, cc in (
            ("Japan", "JP"),
            ("Singapore", "SG"),
            ("Hong Kong", "HK"),
            ("SIN — Singapore, Singapore", "SG"),
            ("Georgia", "GE"),
        ):
            scopes = pf.scopes_for(req(destination=typed))
            assert [s.key for s in scopes] == [f"country:{cc}"], typed

    def test_a_state_named_like_a_country_is_the_state(self):
        keys = [s.key for s in pf.scopes_for(req(destination="Georgia, USA"))]
        assert keys == ["region:US.GA", "country:US"]

    def test_an_airport_label_resolves(self):
        keys = [s.key for s in pf.scopes_for(req(destination="TYO — Tokyo, Japan"))]
        assert keys == ["city:1850147", "country:JP"]

    def test_city_states_are_one_place_same_named_states_are_two(self):
        def keys(d):
            return [s.key for s in pf.scopes_for(req(destination=d))]

        assert keys("Tokyo, Japan") == ["city:1850147", "country:JP"]
        assert keys("Prague") == ["city:3067696", "country:CZ"]
        assert keys("São Paulo, Brazil") == [
            "city:3448439",
            "region:BR.27",
            "country:BR",
        ]
        # a region named like the country ("Taiwan" for Taipei) is not repeated
        assert keys("Taipei") == ["city:1668341", "country:TW"]

    def test_a_division_is_a_region(self):
        scopes = pf.scopes_for(
            SimpleNamespace(destinations=None, destination="Florida")
        )
        assert [(s.scope, s.name) for s in scopes] == [
            ("region", "Florida"),
            ("country", "United States"),
        ]


# ── crawler facts ─────────────────────────────────────────────────────


class TestCrawlerFacts:
    def test_section_with_sources(self, berlin_crawler):
        section = run(crawler_section(req()))
        city = facts_of(section, "city:2950159")
        assert [f["text"] for f in city["historical"]] == [
            "Berlin was founded in 1237."
        ]
        f = city["historical"][0]
        assert f["origin"] == "crawler" and f["source"] == "crawler"
        assert f["citation"]["name"] == "Wikidata"
        assert f["citation"]["url"] == "https://www.wikidata.org/wiki/Q64#P571"
        assert f["citation"]["as_of"] == "2026-11-20"
        assert f["citation"]["licence"] == "open"
        assert f["citation"]["attribution"] == "Wikidata (CC0 1.0)"
        # the capital fact from the country page belongs to the city
        assert "Berlin is Germany's capital." in [f["text"] for f in city["popular"]]
        country = facts_of(section, "country:DE")
        assert [f["text"] for f in country["popular"]] == [
            "Germany has about 83 million people."
        ]
        assert [f["text"] for f in country["historical"]] == [
            "Germany was reunified in 1990."
        ]
        # Bavaria is neither the city, its region nor the country
        assert all("Zugspitze" not in f["text"] for f in all_facts(section))
        assert section["counts"] == {"crawler": 6, "ai": 0}

    def test_region_facts_by_name(self, crawler_on):
        crawler_on(FakeCrawler({}, {"DE": COUNTRY_FACTS}))
        section = run(crawler_section(req(destination="Munich, Germany")))
        keys = [p["key"] for p in section["places"]]
        assert any(k.startswith("region:DE.") for k in keys)
        region = next(p for p in section["places"] if p["scope"] == "region")
        assert region["name"] == "Bavaria"
        assert [f["text"] for f in region["groups"]["unbelievable"]] == [
            "Bavaria's Zugspitze is Germany's highest peak."
        ]

    def test_a_hint_destination_gets_city_facts(self, crawler_on):
        kyoto = {**BERLIN, "geonames_id": 1857910, "country": "JP", "name": "Kyoto"}
        fake = crawler_on(
            FakeCrawler(
                {1857910: [fact(1, kyoto, "historical", "Kyoto was the capital.")]},
                {"JP": []},
            )
        )
        section = run(crawler_section(req(destination="Kyoto, Japan")))
        assert [f["text"] for f in facts_of(section, "city:1857910")["historical"]] == [
            "Kyoto was the capital."
        ]
        assert {"geonames_id": "1857910"} in [
            {k: v for k, v in p.items() if k == "geonames_id"} for p in fake.params()
        ]

    def test_region_match_needs_the_same_name_or_a_division(self, crawler_on):
        def item(fid, name, level):
            return fact(
                fid,
                {
                    "geonames_id": 9000 + fid,
                    "admin_level": level,
                    "country": "DE",
                    "name": name,
                },
                "little_known",
                f"Fact {fid} about {name}.",
            )

        crawler_on(
            FakeCrawler(
                {},
                {
                    "DE": [
                        item(1, "Bavaria", None),
                        item(2, "Bavaria Park", None),
                        item(3, "Bavaria Film Studios", "feature"),
                        item(4, "Bavaria Region", "admin1"),
                    ]
                },
            )
        )
        section = run(crawler_section(req(destination="Munich, Germany")))
        region = next(p for p in section["places"] if p["scope"] == "region")
        texts = sorted(f["text"] for f in region["groups"]["little_known"])
        assert texts == ["Fact 1 about Bavaria.", "Fact 4 about Bavaria Region."]

    def test_ai_bot_blocked_sources_are_not_shown(self, crawler_on):
        crawler_on(
            FakeCrawler(
                {
                    2950159: [
                        fact(
                            1,
                            BERLIN,
                            "popular",
                            "Text from a blocked source.",
                            blocked=True,
                        ),
                        fact(2, BERLIN, "popular", "Open text about Berlin."),
                    ]
                },
                {"DE": []},
            )
        )
        section = run(crawler_section(req()))
        texts = [f["text"] for f in all_facts(section)]
        assert texts == ["Open text about Berlin."]
        assert "blocked source" not in json.dumps(section)

    def test_only_our_own_sentences_are_shown(self):
        for origin in ("templated", "rewritten"):
            f = pf.crawler_fact(fact(1, BERLIN, "popular", "Own words.", origin=origin))
            assert f and f["text"] == "Own words."
        # a source's text as written, or any origin this client does not know
        for origin in ("source_hook", "quoted", "", None):
            item = fact(1, BERLIN, "popular", "Not ours.", origin=origin)
            assert pf.crawler_fact(item) is None
        item = fact(1, BERLIN, "popular", "No origin.")
        del item["text_origin"]
        assert pf.crawler_fact(item) is None
        f = pf.crawler_fact(fact(1, BERLIN, "popular", "Own words."))
        assert "quote" not in f

    def test_value_lang_is_carried_and_optional(self, berlin_crawler):
        section = run(crawler_section(req()))
        motto = next(
            f
            for f in facts_of(section, "city:2950159")["popular"]
            if "motto" in f["text"]
        )
        assert motto["value_lang"] == "de" and motto["lang"] == "en"
        founded = facts_of(section, "city:2950159")["historical"][0]
        assert founded["value_lang"] is None  # absent in the item
        assert (
            pf.crawler_fact(fact(1, BERLIN, "popular", "Text x.", value_lang="und"))[
                "value_lang"
            ]
            == "und"
        )
        for bad in ("<script>", "d e", 7, "x" * 40):
            item = fact(1, BERLIN, "popular", "Text x.", value_lang=bad)
            assert pf.crawler_fact(item)["value_lang"] is None
        translated = pf.crawler_fact(
            fact(
                2,
                BERLIN,
                "popular",
                "Berlin hat 1.700 Brücken.",
                lang="de",
                text_en="Berlin has 1,700 bridges.",
            )
        )
        assert translated["lang"] == "en"

    def test_share_alike_is_never_for_the_model(self, crawler_on):
        crawler_on(
            FakeCrawler(
                {
                    2950159: [
                        fact(1, BERLIN, "historical", "Berlin was founded in 1237."),
                        fact(
                            2,
                            BERLIN,
                            "little_known",
                            "Berlin holds a Babylonian gate.",
                            licence=CC_BY_SA,
                            llm_ok=False,
                            origin="rewritten",
                        ),
                    ]
                },
                {"DE": []},
            )
        )
        section = run(crawler_section(req()))
        city = facts_of(section, "city:2950159")
        assert city["little_known"][0]["citation"]["licence"] == "share_alike"
        prompt = pf.reference_prompt(section)
        assert "Berlin was founded in 1237." in prompt
        assert "UNTRUSTED" in prompt.upper()
        assert "Babylonian" not in prompt

    def test_country_near_duplicates_prefer_wikidata(self, crawler_on):
        bare_de = {"admin_level": "country", "country": "DE", "name": "Germany"}
        factbook = {
            "source_id": "factbook_json",
            "url": "https://github.com/factbook/factbook.json",
            "name": "The World Factbook",
        }

        def fb(fid, ftype, text, value, unit, scope=None):
            return fact(
                fid,
                bare_de,
                ftype,
                text,
                source=factbook,
                quantity={"value": value, "unit": unit, "rank_scope": scope},
            )

        def wd(fid, ftype, text, value, unit, scope=None):
            return fact(
                fid,
                GERMANY,
                ftype,
                text,
                quantity={"value": value, "unit": unit, "rank_scope": scope},
            )

        items = [
            # Factbook first in the page; Wikidata still wins
            fb(
                1,
                "popular",
                "Germany covers a total area of 357,022 km².",
                357022,
                "km2",
            ),
            wd(2, "popular", "Germany covers an area of 357,588 km².", 357588, "km2"),
            fb(
                3,
                "unbelievable",
                "The highest point of Germany is Zugspitze (2,963 m).",
                2963,
                "m",
                "highest point of Germany",
            ),
            wd(
                4,
                "unbelievable",
                "The highest point of Federal Republic of Germany is Zugspitze (2,962 m).",
                2962,
                "m",
                "highest point of Federal Republic of Germany",
            ),
            # a figure that differs is kept
            fb(
                5,
                "unbelievable",
                "The lowest point of Germany is Neuendorf (-3.5 m).",
                -3.5,
                "m",
                "lowest point of Germany",
            ),
            wd(
                6,
                "unbelievable",
                "The lowest point of Germany is Freepsum Lake (-2 m).",
                -2,
                "m",
                "lowest point of Germany",
            ),
            # different quantities never collapse
            fb(
                7, "popular", "Germany has 55 UNESCO World Heritage Sites.", 55, "sites"
            ),
        ]
        crawler_on(FakeCrawler({}, {"DE": items}))
        section = run(crawler_section(req()))
        country = facts_of(section, "country:DE")
        assert [f["text"] for f in country["popular"]] == [
            "Germany covers an area of 357,588 km².",
            "Germany has 55 UNESCO World Heritage Sites.",
        ]
        texts = sorted(f["text"] for f in country["unbelievable"])
        assert texts == [
            "The highest point of Federal Republic of Germany is Zugspitze (2,962 m).",
            "The lowest point of Germany is Freepsum Lake (-2 m).",
            "The lowest point of Germany is Neuendorf (-3.5 m).",
        ]

    def test_near_duplicates_without_wikidata_keep_one(self):
        bare = {"admin_level": "country", "country": "DE"}
        q = {"value": 100.0, "unit": "km2", "rank_scope": None}
        src = {"source_id": "factbook_json", "name": "The World Factbook"}
        a = fact(
            1,
            bare,
            "popular",
            "Area one.",
            quantity=q,
            confidence="extracted",
            source=src,
        )
        b = fact(
            2, bare, "popular", "Area two.", quantity={**q, "value": 100.4}, source=src
        )
        pairs = [(i, pf.crawler_fact(i)) for i in (a, b)]
        kept = pf.dedupe_quantities(pairs)
        # the better-confidence one stays
        assert [f["text"] for _, f in kept] == ["Area two."]
        # facts without a quantity, or below country level, are left alone
        city = fact(3, BERLIN, "popular", "City area.", quantity=q)
        plain = fact(4, bare, "popular", "No figure.")
        pairs = [(i, pf.crawler_fact(i)) for i in (a, city, plain)]
        assert len(pf.dedupe_quantities(pairs)) == 3

    def test_share_alike_ai_blocked_and_not_llm_ok_stay_out_of_prompts(self):
        items = [
            fact(
                1,
                BERLIN,
                "little_known",
                "Share alike text.",
                licence=CC_BY_SA,
                llm_ok=False,
            ),
            fact(3, BERLIN, "little_known", "Reserved source text.", llm_ok=False),
            fact(4, BERLIN, "little_known", "Open text."),
        ]
        facts = [pf.crawler_fact(i) for i in items]
        assert [f["llm_ok"] for f in facts] == [False, False, True]
        # an AI-blocked source is not shown at all, so never in a prompt
        assert (
            pf.crawler_fact(fact(2, BERLIN, "little_known", "Blocked.", blocked=True))
            is None
        )

    def test_languages(self):
        de = fact(1, BERLIN, "little_known", "Berlin hat viele Brücken.", lang="de")
        de_en = fact(
            2,
            BERLIN,
            "little_known",
            "Berlin hat 1.700 Brücken.",
            lang="de",
            text_en="Berlin has 1,700 bridges.",
        )
        assert pf.crawler_fact(de, "en") is None
        assert pf.crawler_fact(de, "de")["text"] == "Berlin hat viele Brücken."
        en = pf.crawler_fact(de_en, "en")
        assert en["text"] == "Berlin has 1,700 bridges." and en["machine_translated"]

    def test_unusable_items_are_dropped(self):
        assert pf.crawler_fact(fact(1, BERLIN, "gossip", "x" * 20)) is None
        assert (
            pf.crawler_fact(fact(1, BERLIN, "little_known", "Text.", source={})) is None
        )
        assert pf.crawler_fact("junk") is None

    def test_off_is_none(self):
        assert run(pf.crawler_facts_for(pf.scopes_for(req()))) is None

    def test_down_is_none(self, crawler_on):
        crawler_on(FakeCrawler(status=500))
        assert run(pf.crawler_facts_for(pf.scopes_for(req()))) is None


# ── agent ─────────────────────────────────────────────────────────────

AI = {
    "places": [
        {
            "key": "city:2950159",
            "facts": [
                # crawler already has historical: dropped
                {
                    "fact_type": "historical",
                    "text": "Berlin was rebuilt after 1945 again.",
                },
                {
                    "fact_type": "unbelievable",
                    "text": "Berlin has more bridges than Venice.",
                },
                {
                    "fact_type": "popular",
                    "text": "Berlin is known for its currywurst stands.",
                    "source_url": "https://made-up.example/currywurst",
                    "source": "Made Up Weekly",
                },
                {"fact_type": "popular", "text": "See https://example.org for more."},
                {"fact_type": "gossip", "text": "Something not in a group at all."},
            ],
        },
        {
            "key": "country:XX",
            "facts": [{"fact_type": "fun", "text": "Unknown place fact."}],
        },
    ]
}


class TestAgent:
    def test_crawler_off_ai_fills_every_group(self, monkeypatch):
        mock = stub_model(monkeypatch, AI)
        agent = PlaceFactsAgent(settings.agents_dir)
        out = run(agent.run(req()))
        prompt = mock.call_args.args[0]
        assert 'key "city:2950159"' in prompt and 'key "country:DE"' in prompt
        assert "REFERENCE DATA" not in prompt
        facts = all_facts(out)
        assert facts and all(f["origin"] == "ai" for f in facts)
        for f in facts:
            assert f["source"] == "ai" and f["verified"] is False
            assert f["citation"] is None
            assert "http" not in json.dumps(f)
        assert "Made Up Weekly" not in json.dumps(out)
        texts = [f["text"] for f in facts]
        assert "Berlin was rebuilt after 1945 again." in texts  # empty group then
        assert "Unknown place fact." not in texts
        assert all("llm_ok" not in f for f in facts)

    def test_ai_only_for_groups_the_crawler_left_empty(
        self, berlin_crawler, monkeypatch
    ):
        mock = stub_model(monkeypatch, AI)
        out = run(PlaceFactsAgent(settings.agents_dir).run(req()))
        prompt = mock.call_args.args[0]
        city_line = next(ln for ln in prompt.splitlines() if "city:2950159" in ln)
        assert "historical" not in city_line and "unbelievable" in city_line
        city = facts_of(out, "city:2950159")
        assert [f["origin"] for f in city["historical"]] == ["crawler"]
        assert [f["text"] for f in city["unbelievable"]] == [
            "Berlin has more bridges than Venice."
        ]
        assert city["unbelievable"][0]["origin"] == "ai"
        assert out["counts"]["crawler"] == 6 and out["counts"]["ai"] >= 1

    def test_the_fun_group_is_always_ai(self, crawler_on, monkeypatch):
        # The crawler writes no fun facts: with every other group sourced,
        # the model is asked for fun only, and those facts are labelled AI
        sourced = [t for t in pf.FACT_TYPES if t != "fun"]
        full = [
            fact(i, BERLIN, t, f"Berlin fact number {i} about {t}.")
            for i, t in enumerate(sourced)
        ]
        country = [
            fact(100 + i, GERMANY, t, f"Germany fact number {i} about {t}.")
            for i, t in enumerate(sourced)
        ]
        crawler_on(FakeCrawler({2950159: full}, {"DE": country}))
        ai = {
            "places": [
                {
                    "key": k,
                    "facts": [
                        {"fact_type": "fun", "text": f"A fun fact about {k} here."},
                        {"fact_type": "popular", "text": f"Not asked for at {k}."},
                    ],
                }
                for k in ("city:2950159", "country:DE")
            ]
        }
        mock = stub_model(monkeypatch, ai)
        out = run(PlaceFactsAgent(settings.agents_dir).run(req()))
        prompt = mock.call_args.args[0]
        for k in ("city:2950159", "country:DE"):
            line = next(ln for ln in prompt.splitlines() if f'key "{k}"' in ln)
            assert line.endswith("groups: fun")
            fun = facts_of(out, k)["fun"]
            assert [f["text"] for f in fun] == [f"A fun fact about {k} here."]
            assert fun[0]["origin"] == "ai" and fun[0]["verified"] is False
            assert fun[0]["citation"] is None
        assert out["counts"] == {"crawler": 8, "ai": 2}

    def test_no_model_call_when_every_group_has_facts(self, monkeypatch):
        scopes = pf.scopes_for(req())
        full = {
            s.key: {
                t: [
                    pf.crawler_fact(
                        fact(f"{s.key}{t}", BERLIN, t, f"{s.key} {t} fact.")
                    )
                ]
                for t in pf.FACT_TYPES
            }
            for s in scopes
        }
        mock = stub_model(monkeypatch, AI)
        section = pf.build_section(scopes, full)
        out = run(PlaceFactsAgent(settings.agents_dir).run(req(), crawler=section))
        mock.assert_not_called()
        assert out["counts"] == {"crawler": 5 * len(scopes), "ai": 0}

    def test_ai_failure_keeps_the_crawler_facts(self, berlin_crawler, monkeypatch):
        stub_model(monkeypatch, {"error": "model down"})
        out = run(PlaceFactsAgent(settings.agents_dir).run(req()))
        assert "error" not in out
        assert out["counts"] == {"crawler": 6, "ai": 0}

    def test_ai_failure_without_crawler_facts_is_the_error(self, monkeypatch):
        stub_model(
            monkeypatch,
            {
                "error": "AI limit reached for this month — try again on the 1st.",
                "error_code": "ai_limit",
            },
        )
        out = run(PlaceFactsAgent(settings.agents_dir).run(req()))
        assert out["error_code"] == "ai_limit"

    def test_locale_reaches_the_model(self, monkeypatch):
        mock = stub_model(monkeypatch, AI)
        run(PlaceFactsAgent(settings.agents_dir).run(req(locale="de")))
        assert mock.call_args.kwargs == {"locale": "de"}

    def test_long_text_is_trimmed(self):
        section = pf.build_section(pf.scopes_for(req()), None)
        ai = {
            "places": [
                {
                    "key": "country:DE",
                    "facts": [{"fact_type": "fun", "text": "word " * 100}],
                }
            ]
        }
        out = pf.merge_ai(section, ai)
        text = facts_of(out, "country:DE")["fun"][0]["text"]
        assert len(text) <= pf.MAX_TEXT and text.endswith("…")


# ── stream ────────────────────────────────────────────────────────────


class _Fake:
    def __init__(self, result):
        self._result = result

    async def run(self, request, **kw):
        return copy.deepcopy(self._result)


def _orchestrator(facts_agent):
    from app.agents.orchestrator import TravelOrchestrator

    orch = TravelOrchestrator.__new__(TravelOrchestrator)
    for attr in [
        "flights",
        "hotels",
        "activities",
        "places",
        "visa",
        "emergency_card",
        "weather",
        "walking_tours",
        "events",
        "sim",
        "tips",
        "getting_around",
        "forex",
        "pricing_advisor",
    ]:
        setattr(orch, attr, _Fake({"results": []}))
    orch.itinerary = _Fake({"days": [{"day": 1}]})
    orch.packing_list = _Fake({"categories": []})
    orch.stress_test = _Fake({"overall": "ok"})
    if facts_agent is not None:
        orch.place_facts = facts_agent
    return orch


async def _events(orch, request):
    out = []
    async for chunk in orch.stream_run(request):
        if chunk.startswith("data: "):
            out.append(json.loads(chunk[6:]))
    return out


class TestStream:
    async def test_crawler_first_then_ai(self, berlin_crawler, monkeypatch):
        stub_model(monkeypatch, AI)
        events = await _events(
            _orchestrator(PlaceFactsAgent(settings.agents_dir)), req()
        )
        facts = [e for e in events if e["type"] == "facts"]
        assert [e["source"] for e in facts] == ["crawler", "ai"]
        first, last = facts[0]["data"], facts[1]["data"]
        assert first["counts"] == {"crawler": 6, "ai": 0}
        # the Factbook fact names its source but has no link: not "verified"
        assert first["verification"]["level"] == "partial"
        assert last["counts"]["ai"] >= 1
        assert last["verification"]["level"] == "partial"
        assert {
            "type": "agent_status",
            "agent": "facts",
            "status": "searching",
        } in events
        # the crawler was asked once per filter set (shared fetch)
        assert len(berlin_crawler.calls) == 2

    async def test_ai_error_after_crawler_facts_is_not_sent(
        self, berlin_crawler, monkeypatch
    ):
        stub_model(monkeypatch, {"error": "x"})
        agent = PlaceFactsAgent(settings.agents_dir)

        async def boom(request, crawler=None):
            await crawler
            return {"error": "timed out"}

        monkeypatch.setattr(agent, "run", boom)
        events = await _events(_orchestrator(agent), req())
        facts = [e for e in events if e["type"] == "facts"]
        assert len(facts) == 1 and facts[0]["source"] == "crawler"

    async def test_a_facts_error_is_not_sent_and_the_run_stays_cacheable(
        self, monkeypatch
    ):
        from app.api.routes.search import _is_cacheable_run

        for err in (
            {"error": "model down"},
            {"error": "No facts found", "error_code": "no_facts"},
            {"error": "No place to describe", "error_code": "no_place"},
        ):
            orch = _orchestrator(_Fake(err))
            chunks = [c async for c in orch.stream_run(req())]
            events = [json.loads(c[6:]) for c in chunks if c.startswith("data: ")]
            assert not [e for e in events if e["type"] == "facts"], err
            assert events[-1]["type"] == "done"
            assert _is_cacheable_run(chunks), err

    async def test_crawler_off_one_ai_yield(self, monkeypatch):
        stub_model(monkeypatch, AI)
        events = await _events(
            _orchestrator(PlaceFactsAgent(settings.agents_dir)), req()
        )
        assert [e["source"] for e in events if e["type"] == "facts"] == ["ai"]

    async def test_flag_off_no_section(self, monkeypatch):
        monkeypatch.setattr(settings, "place_facts_enabled", False)
        mock = stub_model(monkeypatch, AI)
        events = await _events(
            _orchestrator(PlaceFactsAgent(settings.agents_dir)), req()
        )
        assert not [
            e for e in events if e["type"] == "facts" or e.get("agent") == "facts"
        ]
        mock.assert_not_called()

    async def test_orchestrator_without_the_agent(self):
        events = await _events(_orchestrator(None), req())
        assert not [e for e in events if e["type"] == "facts"]
        assert events[-1]["type"] == "done"


# ── route, config, verification ───────────────────────────────────────

BODY = {
    "origin": "London",
    "destination": "Berlin, Germany",
    "departure_date": "2027-05-01",
    "return_date": "2027-05-06",
    "nationality": "British",
}


class TestRoute:
    def test_route(self, client, monkeypatch):
        stub_model(monkeypatch, AI)
        resp = client.post("/api/place-facts", json=BODY)
        assert resp.status_code == 200
        body = resp.json()
        assert body["places"][0]["key"] == "city:2950159"
        assert body["verification"]["level"] == "unverified"

    def test_flag_off_404(self, client, monkeypatch):
        monkeypatch.setattr(settings, "place_facts_enabled", False)
        assert client.post("/api/place-facts", json=BODY).status_code == 404

    def test_validates(self, client):
        assert (
            client.post("/api/place-facts", json={"origin": "NYC"}).status_code == 422
        )

    def test_config_reports_the_feature(self, client, monkeypatch):
        assert client.get("/api/config").json()["features"]["place_facts"] == 1
        monkeypatch.setattr(settings, "place_facts_enabled", False)
        assert client.get("/api/config").json()["features"]["place_facts"] == 0


class TestVerification:
    LINKED = {"name": "Wikidata", "url": "https://www.wikidata.org/wiki/Q64"}

    def _section(self, origins, citation=LINKED):
        return {
            "places": [
                {
                    "key": "city:1",
                    "groups": {
                        "popular": [
                            {
                                "origin": o,
                                "text": "x",
                                "citation": citation if o == "crawler" else None,
                            }
                            for o in origins
                        ],
                    },
                }
            ]
        }

    def test_unlinked_or_conflicting_facts_are_not_verified(self):
        r = req()
        unlinked = self._section(["crawler"], {"name": "CIA World Factbook"})
        assert verify_section("facts", unlinked, r)["level"] == "unverified"
        conflict = self._section(["crawler"], {**self.LINKED, "conflict": True})
        assert verify_section("facts", conflict, r)["level"] == "unverified"
        mixed = self._section(["crawler", "crawler"])
        mixed["places"][0]["groups"]["popular"][1]["citation"] = {"name": "x"}
        assert verify_section("facts", mixed, r)["level"] == "partial"

    def test_levels(self):
        r = req()
        assert (
            verify_section("facts", self._section(["crawler"]), r)["level"]
            == "verified"
        )
        assert (
            verify_section("facts", self._section(["crawler", "ai"]), r)["level"]
            == "partial"
        )
        v = verify_section("facts", self._section(["ai"]), r)
        assert v["level"] == "unverified" and v["items_total"] == 1
        assert verify_section("facts", {"places": []}, r)["level"] == "unverified"
        assert verify_section("facts", {"error": "x"}, r) is None
