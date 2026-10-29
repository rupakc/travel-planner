"""Airport autocomplete (search_airports / GET /api/airports/search): codes,
airport cities and names, plus GeoNames places (folded name prefix) through
their linked airports. Response shape is unchanged."""

import pytest

from app.db.database import search_airports


def _codes(q, limit=10):
    return [r["iata_code"] for r in search_airports(q, limit=limit)]


def test_response_shape_is_unchanged(client):
    rows = search_airports("lhr")
    assert rows and set(rows[0]) == {
        "iata_code",
        "name",
        "city",
        "country",
        "country_code",
    }
    r = client.get("/api/airports/search", params={"q": "lhr"})
    assert r.status_code == 200 and r.json()[0]["iata_code"] == "LHR"


def test_exact_code_first():
    assert _codes("lhr")[0] == "LHR"
    assert _codes("JFK")[0] == "JFK"


def test_london_airports_before_long_beach():
    codes = _codes("lon")
    london = {"LHR", "LGW", "STN", "LTN", "LCY"}
    assert codes[0] == "LHR"
    assert set(codes[:5]) == london
    if "LGB" in codes:
        assert codes.index("LGB") > 4


@pytest.mark.parametrize(
    ("q", "code"), [("par", "CDG"), ("new", "JFK"), ("san", "SFO"), ("lon", "LHR")]
)
def test_common_prefixes_reach_the_big_airport(q, code):
    assert code in _codes(q)[:5]


def test_milan_lists_its_airports_with_city_milan():
    rows = search_airports("milan")
    codes = [r["iata_code"] for r in rows]
    assert {"MXP", "LIN", "BGY"} <= set(codes[:5])
    assert {r["city"] for r in rows if r["iata_code"] in {"MXP", "LIN"}} == {"Milan"}


@pytest.mark.parametrize(
    ("q", "codes"),
    [
        ("kyoto", {"ITM", "KIX"}),  # no airport is in Kyoto: the place links
        ("zermatt", {"ZRH", "GVA", "BRN", "LUG", "SIR"}),
        ("zurich", {"ZRH"}),  # accent-folded place name
        ("münchen", {"MUC"}),
        ("sicily", {"CTA", "PMO"}),  # curated island
    ],
)
def test_places_without_their_own_airport_row(q, codes):
    found = _codes(q)
    assert found and found[0] in codes, found


def test_unscheduled_airports_hidden_unless_code_typed():
    assert "PNH" not in _codes("phnom") and "KTI" in _codes("phnom")
    assert "KBP" not in _codes("kiev")
    assert _codes("KBP")[:1] == ["KBP"]


def test_limit_is_respected():
    assert len(_codes("s", limit=4)) == 4
    assert _codes("   ") == []


# ── Final review: relevance of place-derived suggestions ────────────────────


@pytest.mark.parametrize(
    ("q", "allowed"),
    [
        ("milan", {"MXP", "LIN", "BGY"}),  # not Syracuse / Detroit / Windsor
        ("cologne", {"CGN", "DUS", "DTM"}),  # not Minneapolis / Milan
        ("munchen", {"MUC"}),  # not Zurich / Basel / Bern / Leipzig
        ("dubai", {"DXB", "DWC", "SHJ"}),  # not Gorakhpur / Lucknow
    ],
)
def test_place_suggestions_are_notable_and_own_country(q, allowed):
    assert set(_codes(q)) <= allowed, _codes(q)


def test_alternate_prefix_reaches_big_places():
    assert _codes("münch")[0] == "MUC"
    assert _codes("munch")[0] == "MUC"


@pytest.mark.parametrize(("q", "first"), [("hue", "HUI"), ("goa", "GOI")])
def test_lower_case_three_letters_that_name_a_place_list_the_place_first(q, first):
    codes = _codes(q)
    assert codes[0] == first, codes


@pytest.mark.parametrize(("q", "first"), [("HUE", "HUE"), ("GOA", "GOA")])
def test_upper_case_codes_still_come_first(q, first):
    assert _codes(q)[0] == first
