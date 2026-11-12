"""The fake SerpAPI (scripts/fake_serpapi.py) and the Phase 3 golden files."""

import json
import sys
import threading
from pathlib import Path

import httpx
import pytest

_BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_BACKEND))

from scripts import fake_serpapi  # noqa: E402

ALERTS = Path(__file__).parent / "fixtures" / "alerts"


@pytest.fixture()
def fake():
    servers = []

    def start(drop_after=None):
        server = fake_serpapi.make_server(0, drop_after)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        servers.append(server)
        return f"http://127.0.0.1:{server.server_address[1]}", server

    yield start
    for s in servers:
        s.shutdown()
        s.server_close()


def _get(base, **params):
    return httpx.get(f"{base}/search.json", params=params, timeout=5)


def test_each_engine_answers_from_fixtures(fake):
    base, _ = fake()
    out = _get(base, engine="google_flights", api_key="k").json()
    assert out["best_flights"] and out["price_insights"]["lowest_price"] == 398
    ret = _get(base, engine="google_flights", departure_token="t").json()
    assert ret["best_flights"][0]["flights"][0]["departure_airport"]["id"] == "LIS"
    hotels = _get(base, engine="google_hotels", q="hotels in Lisbon").json()
    assert hotels["properties"]
    prop = _get(base, engine="google_hotels", property_token="x").json()
    assert prop["type"] == "hotel"
    assert _get(base, engine="google", q="Belem").json()["organic_results"]
    assert _get(base, engine="bing").status_code == 400
    assert httpx.get(f"{base}/nope").status_code == 404


def test_calls_are_counted(fake):
    base, _ = fake()
    _get(base, engine="google_flights")
    _get(base, engine="google_flights")
    _get(base, engine="google")
    calls = httpx.get(f"{base}/__calls").json()
    assert calls == {"total": 3, "by_engine": {"google_flights": 2, "google": 1}}


def test_drop_after_serves_lower_prices(fake):
    base, _ = fake(drop_after=2)
    before = [_get(base, engine="google_flights").json() for _ in range(2)]
    after = _get(base, engine="google_flights").json()
    assert before[0] == before[1]
    old = min(
        f["price"] for f in before[0]["best_flights"] + before[0]["other_flights"]
    )
    new = min(f["price"] for f in after["best_flights"] + after["other_flights"])
    assert new == round(old * 0.88)
    assert after["price_insights"]["lowest_price"] == round(398 * 0.88)


def test_hotel_price_drops_by_12_percent(fake):
    base, _ = fake(drop_after=1)
    first = _get(base, engine="google_hotels", property_token="x").json()
    second = _get(base, engine="google_hotels", property_token="x").json()
    a = first["featured_prices"][0]["rooms"][0]["rate_per_night"]["extracted_lowest"]
    b = second["featured_prices"][0]["rooms"][0]["rate_per_night"]["extracted_lowest"]
    assert b == round(a * 0.88)


@pytest.mark.parametrize("name", ["story_cases", "savings_cases", "quiet_hours_cases"])
def test_golden_files_parse_with_unique_names(name):
    cases = json.loads((ALERTS / f"{name}.json").read_text())
    minimum = {"story_cases": 14, "savings_cases": 6, "quiet_hours_cases": 8}[name]
    assert len(cases) >= minimum
    names = [c["name"] for c in cases]
    assert len(names) == len(set(names))
    assert all({"name", "input", "expected"} <= set(c) for c in cases)


def test_required_golden_names_present():
    def names(n):
        return {c["name"] for c in json.loads((ALERTS / f"{n}.json").read_text())}

    assert {
        "no_key_stale_9_days",
        "pending",
        "hotel_history_typical_6_points",
        "estimate_only",
    } <= names("story_cases")
    assert {
        "repeat_alerts_same_watch_counts_once",
        "eur_separate",
        "estimate_excluded",
        "deleted_watch_counts",
    } <= names("savings_cases")
    assert {
        "kolkata_2330_held_to_0700",
        "ny_spring_forward",
        "no_timezone_immediate",
        "start_equals_end_disabled",
        "wraps_midnight_0630_held",
    } <= names("quiet_hours_cases")


def test_story_cases_cover_every_advice_code_and_verdict():
    cases = json.loads((ALERTS / "story_cases.json").read_text())
    codes = {c["expected"]["advice"]["code"] for c in cases}
    verdicts = {c["expected"]["verdict"] for c in cases}
    assert codes == {
        "pending",
        "checks_paused",
        "below_target",
        "near_target",
        "at_lowest",
        "below_typical",
        "within_typical",
        "above_typical",
        "steady",
        "few_checks",
    }
    assert verdicts == {None, "great", "good", "typical", "high"}


def test_launcher_leaves_no_real_serpapi_url():
    import importlib
    import pkgutil

    from app import services
    from scripts import run_with_fake_serpapi as launcher

    mods = [
        importlib.import_module(f"app.services.{m.name}")
        for m in pkgutil.walk_packages(services.__path__)
        if not m.ispkg
    ]
    saved = {}
    for m in mods:
        for k, v in vars(m).items():
            if isinstance(v, str) and "serpapi.com" in v and v.startswith("http"):
                saved[(m, k)] = v
    try:
        launcher.patch("http://127.0.0.1:1/search.json")
        left = [
            f"{m.__name__}.{k}"
            for m in mods
            for k, v in vars(m).items()
            if isinstance(v, str) and "serpapi.com" in v
        ]
        assert left == []
    finally:
        for (m, k), v in saved.items():
            setattr(m, k, v)
