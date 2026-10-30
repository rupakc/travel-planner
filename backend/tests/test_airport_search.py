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


def test_koln_lists_cologne_first():
    assert _codes("köln")[0] == "CGN"
    assert _codes("koln")[0] == "CGN"


def test_short_junk_queries_stay_small():
    assert all(c not in _codes("sky") for c in ("MCO", "SFB", "MDT"))


@pytest.mark.parametrize(("q", "codes"), [("yorkshire", ["LBA"]), ("sylt", ["GWT"])])
def test_exact_hint_keeps_namesakes_abroad_out(q, codes):
    assert _codes(q) == codes


@pytest.mark.parametrize(
    ("q", "code", "within"), [("kili", "JRO", 2), ("bucu", "OTP", 1)]
)
def test_r7_prefix_matches_prefer_big_airports(q, code, within):
    assert code in _codes(q)[:within], _codes(q)


def test_r7_no_padding_below_relevance():
    # nothing that only contains the text when real prefix matches exist
    assert "PHX" not in _codes("sky")


@pytest.mark.parametrize(
    ("q", "want"),
    [
        ("kota", {"JAI", "KQH", "KBR", "BKI"}),
        ("ciud", {"CJS", "PZO", "AGT", "CVM", "MEX", "CEN"}),
        ("vila", {"VIX", "VNX", "VRL", "FEN", "OPO", "MMO"}),
        ("sant", {"SCL", "SDQ", "VVI", "JTR", "QRO", "JBQ", "SDU"}),
    ],
)
def test_g5_four_letter_prefixes_are_own_names(q, want):
    codes = _codes(q)
    assert codes and set(codes[:4]) <= want, codes


def test_autocomplete_applies_the_suburb_rule():
    # Peoria, Arizona is a Phoenix suburb: Peoria, Illinois' own PIA first
    assert _codes("peoria")[0] == "PIA"


@pytest.mark.parametrize(
    ("q", "first", "never"),
    [
        ("deutschland", {"BER"}, {"GRZ", "KLU"}),  # not Deutschlandsberg, AT
        ("nederland", {"AMS"}, {"BPT"}),
        ("nippon", {"HND", "NRT"}, set()),
    ],
)
def test_autocomplete_recognises_country_names(q, first, never):
    codes = _codes(q)
    assert codes and codes[0] in first, codes
    assert not never & set(codes)


def test_autocomplete_official_country_queries_unchanged():
    # an official country name keeps matching the airports' country column
    assert len(_codes("germany")) == 10


def test_autocomplete_country_name_prefixes():
    assert _codes("deuts")[0] == "BER"
    assert _codes("sveri")[0] == "ARN"


def test_autocomplete_suburb_rule_on_prefixes():
    codes = _codes("peori")
    assert codes[0] == "PIA"


def test_autocomplete_feature_alternates_and_short_names():
    assert "JTR" in _codes("sifnos")


@pytest.mark.parametrize(
    ("q", "both"),
    [("pontevedra", ({"VGO", "SCQ"}, {"EZE", "AEP"})), ("redmond", ({"SEA"}, {"RDM"}))],
)
def test_autocomplete_keeps_namesakes_the_resolver_cannot_split(q, both):
    codes = set(_codes(q))
    assert all(codes & side for side in both), codes


@pytest.mark.parametrize(
    ("q", "first"),
    [
        ("ealing", "LHR"),  # the London borough, not Ealing, NZ's TIU
        ("peoria", "PIA"),
        ("kakadu", "DRW"),
    ],
)
def test_autocomplete_leads_with_the_resolved_answer(q, first):
    assert _codes(q)[0] == first
