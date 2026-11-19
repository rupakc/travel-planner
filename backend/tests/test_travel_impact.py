"""Google Travel Impact Model: per-flight CO2e on flight results.

TIM is always stubbed with httpx.MockTransport (``travel_impact._transport``);
the autouse guard in conftest fails any test that would reach the network."""

import asyncio
import json
import logging
import sqlite3

import httpx
import pytest

from app.agents.flights_agent import FlightsAgent
from app.core.config import settings
from app.db import api_budget_db
from app.db.database import _db_path
from app.services import travel_impact

KEY = "tim-test-key-0123456789"


def _grams(eco: int) -> dict:
    return {
        "first": eco * 3,
        "business": eco * 2,
        "premiumEconomy": int(eco * 1.5),
        "economy": eco,
    }


class Tim:
    """A fake TIM: answers each asked flight, except numbers in ``unknown``."""

    def __init__(self, status=200, unknown=(), exc=None):
        self.status = status
        self.unknown = set(unknown)
        self.exc = exc
        self.calls: list[dict] = []
        self.headers: list[httpx.Headers] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        if self.exc:
            raise self.exc
        body = json.loads(request.content)
        self.calls.append(body)
        self.headers.append(request.headers)
        if self.status != 200:
            return httpx.Response(self.status, json={"error": {"code": self.status}})
        out = []
        for f in body["flights"]:
            entry = {"flight": f, "source": "TIM"}
            if f["flightNumber"] not in self.unknown:
                entry["emissionsGramsPerPax"] = _grams(100_000 + f["flightNumber"])
                entry["contrailsImpactBucket"] = "CONTRAILS_IMPACT_MODERATE"
            out.append(entry)
        return httpx.Response(
            200,
            json={
                "flightEmissions": out,
                "modelVersion": {
                    "major": 3,
                    "minor": 0,
                    "patch": 2,
                    "dated": "20261119",
                },
            },
        )


@pytest.fixture
def tim(monkeypatch, client):
    monkeypatch.setattr(settings, "tim_enabled", True)
    monkeypatch.setattr(settings, "tim_api_key", KEY)
    monkeypatch.setattr(settings, "tim_daily_cap", 2000)
    with sqlite3.connect(_db_path()) as conn:
        conn.execute("DELETE FROM api_budget")
    fake = Tim()
    monkeypatch.setattr(travel_impact, "_transport", httpx.MockTransport(fake))
    return fake


def _leg(no="AF1115", o="ZRH", d="CDG", date="2027-01-15", stops=0):
    return {
        "airline": "Air France",
        "flight_number": no,
        "origin": o,
        "destination": d,
        "departure_date": date,
        "stops": stops,
        "layovers": [] if stops == 0 else [{"airport": "AMS"}],
    }


def _rt(out=None, ret=None):
    return {
        "trip_type": "round_trip",
        "price_usd": 300,
        "outbound": out or _leg(),
        "return": ret or _leg("AF1116", "CDG", "ZRH", "2027-01-20"),
    }


def _annotate(data, cabin=None):
    return asyncio.run(travel_impact.annotate(data, cabin))


def _used() -> int:
    return travel_impact.status()["used_today"]


def test_off_by_default_makes_no_call(client):
    data = {"results": [_rt()]}
    assert _annotate(data) == {
        "results": [_rt()]
    }  # conftest guard would fail on a call


def test_enabled_needs_a_key(client, monkeypatch):
    monkeypatch.setattr(settings, "tim_enabled", True)
    monkeypatch.setattr(settings, "tim_api_key", "")
    assert not travel_impact.enabled()
    assert "emissions" not in _annotate({"results": [_rt()]})["results"][0]


def test_round_trip_sums_both_legs_in_one_batched_call(tim):
    data = {
        "results": [
            _rt(),
            _rt(_leg("LX632", "ZRH", "CDG"), _leg("LX633", "CDG", "ZRH", "2027-01-20")),
        ]
    }
    _annotate(data)
    assert len(tim.calls) == 1
    assert len(tim.calls[0]["flights"]) == 4
    e = data["results"][0]["emissions"]
    assert e["kg_co2e_per_pax"] == round((101_115 + 101_116) / 1000)
    assert e["cabin"] == "economy"
    assert set(e["by_class"]) == {"economy", "premiumEconomy", "business", "first"}
    assert e["by_class"]["business"] == round((202_230 + 202_232) / 1000)
    assert e["legs"] == 2
    assert e["contrails_bucket"] == "CONTRAILS_IMPACT_MODERATE"
    assert e["model_version"] == "3.0.2 (20261119)"
    assert e["source"] == "Google Travel Impact Model"
    assert e["attribution_url"].startswith("https://")
    assert e["licence"] == "CC BY-SA 4.0"


def test_request_body_and_key_header(tim):
    _annotate({"results": [{"trip_type": "one_way", "outbound": _leg("AF 0012")}]})
    f = tim.calls[0]["flights"][0]
    assert f == {
        "origin": "ZRH",
        "destination": "CDG",
        "operatingCarrierCode": "AF",
        "flightNumber": 12,
        "departureDate": {"year": 2027, "month": 1, "day": 15},
    }
    assert tim.headers[0]["x-goog-api-key"] == KEY


def test_cabin_class_picks_the_headline(tim):
    data = {"results": [{"outbound": _leg()}]}
    _annotate(data, "business")
    e = data["results"][0]["emissions"]
    assert (
        e["cabin"] == "business" and e["kg_co2e_per_pax"] == e["by_class"]["business"]
    )


def test_connections_and_bad_numbers_are_not_estimated(tim):
    data = {
        "results": [
            {"outbound": _leg(stops=1)},
            {"outbound": _leg("Air France")},
            {"outbound": _leg(o="Zurich")},
            {"outbound": _leg(date="15/01/2027")},
        ]
    }
    _annotate(data)
    assert tim.calls == []
    assert all("emissions" not in r for r in data["results"])


def test_unknown_flight_leaves_that_result_alone(tim):
    tim.unknown = {1116}
    data = {"results": [_rt(), {"outbound": _leg("LX632")}]}
    _annotate(data)
    assert "emissions" not in data["results"][0]
    assert data["results"][1]["emissions"]["legs"] == 1


def test_cache_hits_do_not_call_or_count(tim):
    _annotate({"results": [_rt()]})
    assert _used() == 2
    data = {"results": [_rt()]}
    _annotate(data)
    assert len(tim.calls) == 1
    assert _used() == 2
    assert data["results"][0]["emissions"]["kg_co2e_per_pax"] > 0


def test_daily_cap_limits_what_is_sent(tim, monkeypatch):
    monkeypatch.setattr(settings, "tim_daily_cap", 3)
    data = {"results": [_rt(), _rt(_leg("LX632"), _leg("LX633", "CDG", "ZRH"))]}
    _annotate(data)
    assert len(tim.calls[0]["flights"]) == 3
    assert _used() == 3
    assert travel_impact.status()["paused"] is True
    # At the cap: nothing more is sent
    _annotate({"results": [{"outbound": _leg("BA100", "LHR", "JFK")}]})
    assert len(tim.calls) == 1


def test_cap_counts_per_utc_day(tim, monkeypatch):
    monkeypatch.setattr(settings, "tim_daily_cap", 1)
    monkeypatch.setattr(travel_impact, "_today", lambda: "2027-01-01")
    _annotate({"results": [{"outbound": _leg()}]})
    monkeypatch.setattr(travel_impact, "_today", lambda: "2027-01-02")
    _annotate({"results": [{"outbound": _leg("LX632")}]})
    assert len(tim.calls) == 2


@pytest.mark.parametrize(
    "fake", [Tim(status=500), Tim(status=403), Tim(exc=httpx.ConnectTimeout("slow"))]
)
def test_failures_never_break_flights(tim, monkeypatch, fake, caplog):
    monkeypatch.setattr(travel_impact, "_transport", httpx.MockTransport(fake))
    data = {"results": [_rt()]}
    with caplog.at_level(logging.WARNING):
        out = _annotate(data)
    assert out is data and "emissions" not in data["results"][0]
    assert KEY not in caplog.text


def test_flights_agent_enrich_adds_emissions(tim, client):
    agent = FlightsAgent(str(settings_agents_dir()))
    data = {"results": [dict(_rt(), source="google_flights")]}
    out = asyncio.run(agent.enrich(data))
    assert out["results"][0]["emissions"]["legs"] == 2


def settings_agents_dir():
    from pathlib import Path

    return Path(__file__).resolve().parents[2] / ".agents"


def test_health_reports_tim(client, tim):
    _annotate({"results": [{"outbound": _leg()}]})
    body = client.get("/health").json()
    assert body["travel_impact_model"] == {
        "configured": True,
        "enabled": True,
        "used_today": 1,
        "cap": 2000,
        "paused": False,
    }


def test_budget_rows_are_per_day(tim):
    _annotate({"results": [{"outbound": _leg()}]})
    s = api_budget_db.status(f"google_tim:{travel_impact._today()}", 2000)
    assert s["used"] == 1


def _connecting(segments, o="ZRH", d="JFK", date="2027-01-15"):
    return {
        **_leg(o=o, d=d, date=date, stops=len(segments) - 1),
        "flight_number": segments[0][0],
        "segments": [
            {
                "flight_number": no,
                "origin": so,
                "destination": sd,
                "departure_date": sdate,
            }
            for no, so, sd, sdate in segments
        ],
    }


def test_connecting_leg_sums_its_segments(tim):
    out = _connecting(
        [("LX318", "ZRH", "LHR", "2027-01-15"), ("BA117", "LHR", "JFK", "2027-01-15")]
    )
    ret = _leg("LX17", "JFK", "ZRH", "2027-01-22")
    data = {"results": [_rt(out, ret)]}
    _annotate(data)
    assert len(tim.calls[0]["flights"]) == 3
    r = data["results"][0]
    assert r["emissions"]["legs"] == 3
    assert r["emissions"]["kg_co2e_per_pax"] == round(
        (100_318 + 100_117 + 100_017) / 1000
    )
    # Each leg carries its own figure, so a footprint can count one way only
    assert r["outbound"]["emissions"]["kg_co2e_per_pax"] == round(
        (100_318 + 100_117) / 1000
    )
    assert r["outbound"]["emissions"]["legs"] == 2
    assert r["return"]["emissions"]["kg_co2e_per_pax"] == round(100_017 / 1000)


def test_connecting_leg_needs_every_segment_chained(tim):
    broken = [
        # a segment without a flight number
        _connecting(
            [("LX318", "ZRH", "LHR", "2027-01-15"), ("", "LHR", "JFK", "2027-01-15")]
        ),
        # segments that don't chain (LHR -> LGW gap)
        _connecting(
            [
                ("LX318", "ZRH", "LHR", "2027-01-15"),
                ("BA117", "LGW", "JFK", "2027-01-15"),
            ]
        ),
        # segments that don't end at the leg's destination
        _connecting(
            [
                ("LX318", "ZRH", "LHR", "2027-01-15"),
                ("BA117", "LHR", "EWR", "2027-01-15"),
            ]
        ),
        # stops disagree with the segment count
        {
            **_connecting(
                [
                    ("LX318", "ZRH", "LHR", "2027-01-15"),
                    ("BA117", "LHR", "JFK", "2027-01-15"),
                ]
            ),
            "stops": 2,
        },
    ]
    data = {"results": [{"outbound": leg} for leg in broken]}
    _annotate(data)
    assert tim.calls == []
    assert all("emissions" not in r for r in data["results"])


def test_serp_leg_lists_segments_with_their_own_dates():
    from app.services.serp_flights import _map_leg

    leg = _map_leg(
        [
            {
                "flight_number": "LX 318",
                "departure_airport": {"id": "ZRH", "time": "2027-01-15 21:10"},
                "arrival_airport": {"id": "LHR", "time": "2027-01-15 21:55"},
            },
            {
                "flight_number": "BA 117",
                "departure_airport": {"id": "LHR", "time": "2027-01-16 08:20"},
                "arrival_airport": {"id": "JFK", "time": "2027-01-16 11:05"},
            },
        ],
        [{"id": "LHR", "name": "Heathrow", "duration": 625}],
        "2027-01-15",
    )
    assert leg["segments"] == [
        {
            "flight_number": "LX 318",
            "origin": "ZRH",
            "destination": "LHR",
            "departure_date": "2027-01-15",
        },
        {
            "flight_number": "BA 117",
            "origin": "LHR",
            "destination": "JFK",
            "departure_date": "2027-01-16",
        },
    ]
    assert travel_impact._leg_keys(leg) == [
        ("LX", 318, "ZRH", "LHR", "2027-01-15"),
        ("BA", 117, "LHR", "JFK", "2027-01-16"),
    ]
