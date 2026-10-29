"""The golden set (tests/data/golden_places.csv) at runtime, on the seeded
session DB: "task3" rows through lookup_city_iata (+ resolve_place for the
country), "autocomplete" rows through search_airports. Rows: query,
expected_airports, match (exact / subset / first / none), expected_country,
scope, display_city. Autocomplete "subset" means within the top five.
"""

import csv
from pathlib import Path

import pytest

from app.db.database import get_connection, lookup_city_iata, search_airports
from app.db.places_db import resolve_place

_GOLDEN = Path(__file__).parent / "data" / "golden_places.csv"


def _rows(scope):
    with open(_GOLDEN, encoding="utf-8", newline="") as f:
        return [r for r in csv.DictReader(f) if r["scope"] == scope]


@pytest.fixture(autouse=True)
def seeded_db(client):
    """The session client seeds the place data on startup."""


@pytest.fixture(autouse=True)
def no_web(monkeypatch):
    def _fail(*_a, **_kw):
        raise AssertionError("place resolution must not hit the web")

    monkeypatch.setattr("app.db.database._web_search_iata", _fail)


def _airport(code):
    with get_connection() as conn:
        return conn.execute(
            "SELECT city, country_code, scheduled FROM airports WHERE iata_code = ?",
            (code,),
        ).fetchone()


@pytest.mark.parametrize("row", _rows("task3"), ids=lambda r: r["query"])
def test_golden_lookup(row):
    result = lookup_city_iata(row["query"])
    expected = row["expected_airports"].split()
    if row["match"] == "none":
        assert result is None
        return
    assert result, row["query"]
    codes = result.split(",")
    assert len(codes) <= 3
    assert all(_airport(c)["scheduled"] == 1 for c in codes)
    if row["match"] == "exact":
        assert codes == expected
    elif row["match"] == "subset":
        assert set(expected) <= set(codes), codes
    else:
        assert codes[0] in expected, codes
    place = resolve_place(row["query"])
    country = place.country_code if place else _airport(codes[0])["country_code"]
    assert country == row["expected_country"]
    if row["display_city"]:
        assert _airport(codes[0])["city"] == row["display_city"]


@pytest.mark.parametrize("row", _rows("autocomplete"), ids=lambda r: r["query"])
def test_golden_autocomplete(row):
    codes = [r["iata_code"] for r in search_airports(row["query"])]
    expected = row["expected_airports"].split()
    assert codes, row["query"]
    if row["match"] == "subset":
        assert set(expected) <= set(codes[:5]), codes
    else:
        assert codes[0] in expected, codes
