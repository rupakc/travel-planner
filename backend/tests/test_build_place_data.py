"""Tests for the offline place-data generator (backend/scripts/build_place_data.py)
on small inline fixtures, plus spot checks of the committed data files."""

import csv
import functools
import gzip
import importlib.util
import io
from pathlib import Path

import pytest

from app.core.places import fold_place

_BACKEND = Path(__file__).resolve().parents[1]
_DATA = _BACKEND / "app" / "db" / "data"


@functools.cache
def _gen():
    path = _BACKEND / "scripts" / "build_place_data.py"
    spec = importlib.util.spec_from_file_location("build_place_data", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# ── Folding ────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("text", "folded"),
    [
        ("St. Louis", "st louis"),
        ("Winston-Salem", "winston salem"),
        ("Washington D.C.", "washington d c"),
        ("  Saint-Étienne ", "saint etienne"),
        ("Bad Homburg vor der Höhe", "bad homburg vor der hohe"),
        ("MÜNCHEN", "munchen"),
        ("Łódź", "lodz"),
        ("Xi’an", "xian"),
        ("St. John's", "st johns"),
        ("Nuku‘alofa", "nukualofa"),
        ("Hawaiʻi", "hawaii"),
        ("Ma`ale", "maale"),
        ("Taʼizz", "taizz"),
        ("Tverʹ", "tver"),
        ("“Quoted”", "quoted"),
        ("Ban\u200cdar", "bandar"),  # ZWNJ dropped
        ("\u200eAswan", "aswan"),  # LRM dropped
        ("Port–Louis", "port louis"),  # en dash
        ("Kraków—Nowa Huta", "krakow nowa huta"),  # em dash
        ("Sant·Joan", "sant joan"),
        ("Gəncə", "gence"),
        ("Ɛkpɛ", "ekpe"),
        ("Ħamrun", "hamrun"),
        ("Ƶarnowiec", "zarnowiec"),
    ],
)
def test_fold_place_punctuation_and_accents(text, folded):
    assert fold_place(text) == folded


def test_generator_uses_the_shared_fold():
    assert _gen().fold_place is fold_place


# ── Municipality cleaning ──────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("raw", "clean"),
    [
        ("Ferno (VA)", "Ferno"),
        ("Sydney (Mascot)", "Sydney"),
        ("Paris (Roissy-en-France, Val-d'Oise)", "Paris"),
        ("Zaventem", "Zaventem"),
        ("Kona, Hawaii", "Kona"),
        ("Bastia/Poretta", "Bastia"),
        ("  Maiquetía ", "Maiquetía"),
        ("", ""),
    ],
)
def test_clean_municipality(raw, clean):
    assert _gen().clean_municipality(raw) == clean


# ── Score ──────────────────────────────────────────────────────────────────


def test_notability_score():
    score = _gen().notability_score
    assert score(1000, 2, "PPL") == 1000 * 9
    assert score(1000, 2, "PPLC") == 1000 * 9 * 3
    assert score(1000, 0, "PPLA") == 1000
    assert score(0, 50, "PPL") == 0


def test_notability_beats_population_for_famous_namesakes():
    score = _gen().notability_score
    # A small famous town with many names vs a bigger obscure namesake.
    famous = score(5_000, 60, "PPL")
    obscure = score(20_000, 5, "PPL")
    assert famous >= 3 * obscure
    # Two well-known cities of similar fame stay within 3x (ambiguous).
    a, b = score(800_000, 120, "PPLA"), score(1_500_000, 70, "PPLA")
    assert max(a, b) < 3 * min(a, b)


# ── Alt names ──────────────────────────────────────────────────────────────


def test_filter_alt_names():
    raw = ",".join(
        [
            "Milano",
            "Mailand",
            "MIL",  # code
            "Milan",  # own name
            "MILAN",  # folds to own name
            "Милан",  # Cyrillic
            "米兰",  # Han
            "Milán",  # folds to own name
            "http://en.wikipedia.org/wiki/Milan",
            "x" * 41,  # too long
            "Mediolanum",
            "Milano",  # duplicate
            "Mi-lano",  # folds to "mi lano"
            "Milano (2)",  # brackets and digits
            "Mil=ano",
            "Mi[lano]",
            "Mi*lano",
            "Mi_lano",
            "Mi/lano",
            "Mi:lano",
            "Mi&lano",
            "Mi?lano",
            "ミ・ラノ",
            "",
        ]
    )
    assert _gen().filter_alt_names(raw, "milan") == [
        "mailand",
        "mediolanum",
        "mi lano",
        "milano",
    ]


def test_is_latin():
    is_latin = _gen().is_latin
    assert is_latin("São Paulo")
    assert is_latin("Kraków-Płaszów")
    assert is_latin("Saint-Jean d’Angély")
    assert not is_latin("Kraków 2")
    assert not is_latin("saqqez (2)")
    assert not is_latin("asu=suwaida")
    assert not is_latin("aru・maruji")
    assert not is_latin("Tai Hang Estate (East & West)")
    assert is_latin("Đà Nẵng")
    assert not is_latin("Москва")
    assert not is_latin("Αθήνα")
    assert not is_latin("Tokyo 東京")


# ── Fixture builder ────────────────────────────────────────────────────────

_OA_HEADER = (
    "id,ident,type,name,latitude_deg,longitude_deg,elevation_ft,continent,"
    "iso_country,iso_region,municipality,scheduled_service,icao_code,iata_code,"
    "gps_code,local_code,home_link,wikipedia_link,keywords"
).split(",")

_KM_PER_DEG = 6371.0088 * 3.141592653589793 / 180  # ≈ 111.195 km per degree


def _north(lat, km):
    """Latitude ``km`` due north of ``lat`` (same longitude)."""
    return round(lat + km / _KM_PER_DEG, 6)


def _oa(
    iata,
    lat,
    lng,
    kind="large_airport",
    scheduled="yes",
    municipality="Town",
    cc="XA",
    region="XA-01",
    name=None,
    icao=None,
):
    return {
        "id": str(sum(ord(c) for c in iata)),
        "ident": icao or "X" + iata,
        "type": kind,
        "name": name or f"{iata} Airport",
        "latitude_deg": str(lat),
        "longitude_deg": str(lng),
        "iso_country": cc,
        "iso_region": region,
        "municipality": municipality,
        "scheduled_service": scheduled,
        "icao_code": icao or "X" + iata,
        "iata_code": iata,
    }


def _city(
    gid,
    name,
    lat,
    lng,
    pop,
    cc="XA",
    admin1="01",
    fcode="PPL",
    alts="",
    ascii_name=None,
):
    return [
        str(gid),
        name,
        ascii_name or name,
        alts,
        str(lat),
        str(lng),
        "P",
        fcode,
        cc,
        "",
        admin1,
        "",
        "",
        "",
        str(pop),
        "",
        "10",
        "Etc/UTC",
        "2026-01-01",
    ]


def _write_sources(tmp_path, airports, cities, admin1=None, countries=None):
    src = tmp_path / "src"
    oa = src / "oa"
    oa.mkdir(parents=True)
    with open(oa / "airports.csv", "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=_OA_HEADER, quoting=csv.QUOTE_NONNUMERIC)
        w.writeheader()
        for row in airports:
            w.writerow({k: row.get(k, "") for k in _OA_HEADER})
    with open(oa / "countries.csv", "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["id", "code", "name", "continent", "wikipedia_link", "keywords"])
        for code, name in (countries or {"XA": "Xland", "XB": "Yland"}).items():
            w.writerow(["1", code, name, "EU", "", ""])
    cities_path = src / "cities.txt"
    cities_path.write_text(
        "".join("\t".join(c) + "\n" for c in cities), encoding="utf-8"
    )
    admin1_path = src / "admin1.txt"
    admin1_path.write_text(
        "".join(
            "\t".join(r) + "\n"
            for r in (admin1 or [("XA.01", "Nörth Prövince", "North Province", "9")])
        ),
        encoding="utf-8",
    )
    return oa, cities_path, admin1_path


def _build(tmp_path, airports, cities, curated=(), **kw):
    oa, cities_path, admin1_path = _write_sources(tmp_path, airports, cities, **kw)
    return _gen().build(oa, cities_path, admin1_path, list(curated))


def _links(result, gid):
    return result.places[str(gid)]["airports"]


# ── Linking ────────────────────────────────────────────────────────────────

_LAT, _LNG = 10.0, 20.0


def test_large_reach_is_80km_for_normal_places(tmp_path):
    r = _build(
        tmp_path,
        [_oa("AAA", _north(_LAT, 75), _LNG), _oa("BBB", _north(_LAT, 90), _LNG)],
        [_city(1, "Smallville", _LAT, _LNG, 50_000)],
    )
    assert _links(r, 1) == ["AAA"]


def test_large_reach_is_100km_for_million_cities_without_close_large(tmp_path):
    airports = [
        _oa("FAR", _north(_LAT, 90), _LNG),  # 90/100 = 0.9 of its reach
        _oa("MED", _north(_LAT, 40), _LNG, kind="medium_airport"),  # 40/50 = 0.8
    ]
    r = _build(tmp_path, airports, [_city(1, "Bigville", _LAT, _LNG, 2_000_000)])
    assert _links(r, 1) == ["MED", "FAR"]


def test_million_city_reaches_100km_even_with_a_close_large(tmp_path):
    # Kyoto / KIX: ITM is close, KIX 81 km away still links.
    airports = [
        _oa("FAR", _north(_LAT, 90), _LNG),  # 0.9
        _oa("NEA", _north(_LAT, 30), _LNG),  # 0.3
        _oa("MED", _north(_LAT, 40), _LNG, kind="medium_airport"),  # 0.8
        _oa("OUT", _north(_LAT, -105), _LNG),
    ]
    r = _build(tmp_path, airports, [_city(1, "Bigville", _LAT, _LNG, 2_000_000)])
    assert _links(r, 1) == ["NEA", "MED", "FAR"]
    r = _build(tmp_path / "small", airports, [_city(1, "Town", _LAT, _LNG, 999_999)])
    assert _links(r, 1) == ["NEA", "MED"]


def test_small_town_with_only_far_large_falls_back(tmp_path):
    # 90 km large is out of the 80 km reach for a non-million place, so the
    # fallback picks it up instead.
    airports = [
        _oa("FAR", _north(_LAT, 90), _LNG),
        _oa("SML", _north(_LAT, 40), _LNG, kind="small_airport"),
    ]
    r = _build(tmp_path, airports, [_city(1, "Village", _LAT, _LNG, 5_000)])
    assert _links(r, 1) == ["FAR"]


def test_medium_and_small_reach(tmp_path):
    airports = [
        _oa("MIN", _north(_LAT, 45), _LNG, kind="medium_airport"),
        _oa("MOT", _north(_LAT, 55), _LNG, kind="medium_airport"),
        _oa("SIN", _north(_LAT, -25), _LNG, kind="small_airport"),
        _oa("SOT", _north(_LAT, -35), _LNG, kind="small_airport"),
    ]
    r = _build(tmp_path, airports, [_city(1, "Village", _LAT, _LNG, 5_000)])
    # SIN 25/30 = 0.83 of its reach, MIN 45/50 = 0.9.
    assert _links(r, 1) == ["SIN", "MIN"]


def test_links_keep_at_most_three_ranked_by_distance_over_reach(tmp_path):
    airports = [
        _oa("SM1", _north(_LAT, 5), _LNG, kind="small_airport"),  # 0.17
        _oa("ME1", _north(_LAT, 10), _LNG, kind="medium_airport"),  # 0.20
        _oa("LA2", _north(_LAT, 60), _LNG),  # 0.75
        _oa("LA1", _north(_LAT, 20), _LNG),  # 0.25
        _oa("ME2", _north(_LAT, -12), _LNG, kind="medium_airport"),  # 0.24
    ]
    r = _build(tmp_path, airports, [_city(1, "Village", _LAT, _LNG, 5_000)])
    assert _links(r, 1) == ["SM1", "ME1", "ME2"]


def test_curated_airports_rank_before_other_airports(tmp_path):
    airports = [
        _oa("NON", _north(_LAT, 20), _LNG),
        _oa("CUR", _north(_LAT, -60), _LNG),
    ]
    curated = [("CUR", "XCUR", "Cur", "Bigcity", "Xland", "XA", 0.0, 0.0)]
    r = _build(
        tmp_path, airports, [_city(1, "Village", _LAT, _LNG, 5_000)], curated=curated
    )
    assert _links(r, 1) == ["CUR", "NON"]


def test_the_places_own_airport_ranks_before_curated_ones(tmp_path):
    airports = [
        _oa("OWN", _north(_LAT, 30), _LNG, name="Fortville International Airport"),
        _oa("CUR", _north(_LAT, -20), _LNG),
    ]
    curated = [("CUR", "XCUR", "Cur", "Bigcity", "Xland", "XA", 0.0, 0.0)]
    r = _build(
        tmp_path, airports, [_city(1, "Fortville", _LAT, _LNG, 50_000)], curated=curated
    )
    assert _links(r, 1) == ["OWN", "CUR"]


def test_foreign_airports_rank_after_own_country_ones(tmp_path):
    airports = [
        _oa("FOR", _north(_LAT, 10), _LNG, cc="XB"),
        _oa("HOM", _north(_LAT, -40), _LNG, kind="medium_airport"),
    ]
    r = _build(tmp_path, airports, [_city(1, "Village", _LAT, _LNG, 5_000)])
    assert _links(r, 1) == ["HOM", "FOR"]


def test_foreign_airport_named_for_the_place_counts_as_its_own(tmp_path):
    # Basel / BSL: the airport is across the border but carries the name.
    airports = [
        _oa("BSL", _north(_LAT, 8), _LNG, cc="XB", name="EuroAirport Basel Mulhouse"),
        _oa("ZRH", _north(_LAT, -70), _LNG),
    ]
    curated = [("ZRH", "XZRH", "Z", "Zurich", "Xland", "XA", 0.0, 0.0)]
    r = _build(
        tmp_path, airports, [_city(1, "Basel", _LAT, _LNG, 170_000)], curated=curated
    )
    assert _links(r, 1) == ["BSL", "ZRH"]


def test_foreign_airport_whose_curated_city_is_the_place_counts_as_its_own(tmp_path):
    airports = [
        _oa("BSL", _north(_LAT, 8), _LNG, cc="XB", name="EuroAirport"),
        _oa("HOM", _north(_LAT, -30), _LNG, kind="medium_airport"),
    ]
    curated = [("BSL", "XBSL", "E", "Basel", "Yland", "XB", 0.0, 0.0)]
    r = _build(
        tmp_path, airports, [_city(1, "Basel", _LAT, _LNG, 170_000)], curated=curated
    )
    assert _links(r, 1) == ["BSL", "HOM"]


def test_air_bases_are_not_linked_when_a_civil_airport_is_in_reach(tmp_path):
    airports = [
        _oa("MIL", _north(_LAT, 5), _LNG, name="Xyz Air Base"),
        _oa("AFS", _north(_LAT, 6), _LNG, name="Hindon Air Force Station"),
        _oa("JNT", _north(_LAT, 7), _LNG, name="Xyz Airport/Xyz Air Base"),
        _oa("CUR", _north(_LAT, 8), _LNG, name="Big Air Station"),
    ]
    curated = [("CUR", "XCUR", "Big", "Village", "Xland", "XA", 0.0, 0.0)]
    r = _build(
        tmp_path, airports, [_city(1, "Village", _LAT, _LNG, 5_000)], curated=curated
    )
    assert sorted(_links(r, 1)) == ["CUR", "JNT"]
    # Excluded from linking only: the rows stay in airports.csv.
    assert r.airports["MIL"]["scheduled"] == 1


def test_air_base_is_linked_when_no_civil_airport_is_in_reach(tmp_path):
    # Bareilly / BEK: the only airport in reach is an air force station; the
    # civil airports are fallback distance away.
    airports = [
        _oa("BEK", _north(_LAT, 5), _LNG, kind="medium_airport",
            name="Bareilly Air Force Station"),
        _oa("MZS", _north(_LAT, 60), _LNG, kind="medium_airport"),
    ]  # fmt: skip
    r = _build(tmp_path, airports, [_city(1, "Bareilly", _LAT, _LNG, 900_000)])
    assert _links(r, 1) == ["BEK"]


@pytest.mark.parametrize(
    ("b_km", "expected"), [(45, ["BBB", "AAA"]), (55, ["AAA", "BBB"])]
)
def test_near_equal_airports_prefer_the_places_admin1(tmp_path, b_km, expected):
    # AAA sits by a place in admin1 02, BBB is nearest to Home (admin1 01).
    airports = [
        _oa("AAA", _north(_LAT, 40), _LNG),
        _oa("BBB", _north(_LAT, -b_km), _LNG),
    ]
    cities = [
        _city(1, "Home", _LAT, _LNG, 50_000, admin1="01"),
        _city(2, "Other", _north(_LAT, 40), _LNG, 2_000, admin1="02"),
    ]
    r = _build(tmp_path, airports, cities)
    assert _links(r, 1) == expected


def test_fallback_ranks_own_country_first_then_by_distance(tmp_path):
    airports = [
        _oa("SMA", _north(_LAT, 100), _LNG, kind="small_airport"),
        _oa("MED", _north(_LAT, 120), _LNG, kind="medium_airport"),
        _oa("FOR", _north(_LAT, 110), _LNG, cc="XB"),
        _oa("LAR", _north(_LAT, -190), _LNG),
        _oa("LA3", _north(_LAT, 195), _LNG),
        _oa("OUT", _north(_LAT, -210), _LNG),
    ]
    r = _build(tmp_path, airports, [_city(1, "Remote", _LAT, _LNG, 5_000)])
    # Own country within 200 km by distance (not type); small airports never.
    assert _links(r, 1) == ["MED", "LAR"]


def test_fallback_uses_foreign_airports_within_150km(tmp_path):
    airports = [
        _oa("SMA", _north(_LAT, 100), _LNG, kind="small_airport", cc="XB"),
        _oa("MED", _north(_LAT, 120), _LNG, kind="medium_airport", cc="XB"),
        _oa("LAR", _north(_LAT, -140), _LNG, cc="XB"),
        _oa("LA3", _north(_LAT, 145), _LNG, cc="XB"),
        _oa("FAR", _north(_LAT, -160), _LNG, cc="XB"),
    ]
    r = _build(tmp_path, airports, [_city(1, "Remote", _LAT, _LNG, 5_000)])
    assert _links(r, 1) == ["MED", "LAR"]


def test_own_country_fallback_beats_a_nearer_foreign_one(tmp_path):
    airports = [
        _oa("FOR", _north(_LAT, 100), _LNG, cc="XB"),
        _oa("HOM", _north(_LAT, -180), _LNG),
    ]
    r = _build(tmp_path, airports, [_city(1, "Remote", _LAT, _LNG, 5_000)])
    assert _links(r, 1) == ["HOM", "FOR"]


def test_nothing_in_fallback_range_links_nothing(tmp_path):
    r = _build(
        tmp_path,
        [
            _oa("OWN", _north(_LAT, 210), _LNG),
            _oa("FOR", _north(_LAT, -160), _LNG, cc="XB"),
        ],
        [_city(1, "Remote", _LAT, _LNG, 5_000)],
    )
    assert _links(r, 1) == []


def test_unscheduled_and_non_airport_types_never_link(tmp_path):
    airports = [
        _oa("UNS", _north(_LAT, 5), _LNG, scheduled="no"),
        _oa("HEL", _north(_LAT, 5), _LNG, kind="heliport"),
        _oa("SEA", _north(_LAT, 5), _LNG, kind="seaplane_base"),
    ]
    r = _build(tmp_path, airports, [_city(1, "Village", _LAT, _LNG, 5_000)])
    assert _links(r, 1) == []
    assert set(r.airports) == set()  # none qualifies, none curated


def test_linking_works_across_the_antimeridian_and_at_high_latitude(tmp_path):
    airports = [
        _oa("EST", -16.0, 179.9),
        _oa("NOR", 78.2, 15.5),
    ]
    cities = [
        _city(1, "West", -16.0, -179.9, 5_000),
        _city(2, "Arctic", 78.2, 19.5, 5_000),  # ~91 km east at 78°N
    ]
    r = _build(tmp_path, airports, cities)
    assert _links(r, 1) == ["EST"]
    assert _links(r, 2) == ["NOR"]


# ── Places ─────────────────────────────────────────────────────────────────


def test_historical_and_section_places_are_excluded(tmp_path):
    cities = [
        _city(1, "Keep", _LAT, _LNG, 5_000, fcode="PPLA"),
        _city(2, "Section", _LAT, _LNG, 5_000, fcode="PPLX"),
        _city(3, "Historic", _LAT, _LNG, 5_000, fcode="PPLH"),
        _city(4, "Abandoned", _LAT, _LNG, 5_000, fcode="PPLQ"),
        _city(5, "Destroyed", _LAT, _LNG, 5_000, fcode="PPLW"),
        _city(6, "Seat", _LAT, _LNG, 5_000, fcode="PPLCH"),
        _city(7, "Capital", _LAT, _LNG, 5_000, fcode="PPLC"),
    ]
    r = _build(tmp_path, [], cities)
    assert sorted(r.places) == ["1", "7"]


def test_place_row_fields(tmp_path):
    cities = [
        _city(
            7,
            "Grand Ville",
            _LAT,
            _LNG,
            20_000,
            fcode="PPLC",
            alts="Gross Stadt,GV,Великий,Grand-Ville,Grande Ville",
        ),
        _city(8, "Tiny", _LAT, _LNG, 14_999, alts="Tinyburg,Petit"),
    ]
    r = _build(tmp_path, [_oa("AAA", _LAT, _LNG)], cities)
    big = r.places["7"]
    assert big["name"] == "Grand Ville"
    assert big["country_code"] == "XA"
    assert big["admin1"] == "01"
    assert big["population"] == 20_000
    # 5 raw alternate names (Cyrillic and the code count for notability).
    assert big["score"] == 20_000 * 36 * 3
    assert big["alt_names"] == ["grande ville", "gross stadt"]
    # Alternate names are kept only for places with population ≥ 15,000.
    assert r.places["8"]["alt_names"] == []
    assert r.places["8"]["score"] == 14_999 * 9


def test_ascii_spelling_stored_at_any_population(tmp_path):
    cities = [
        _city(1, "Zürich", _LAT, _LNG, 2_000, ascii_name="Zuerich"),
        _city(2, "Xi’an", _LAT, _LNG, 2_000, ascii_name="Xi'an"),
        _city(
            3,
            "Big Zürich",
            _LAT,
            _LNG,
            50_000,
            ascii_name="Big Zuerich",
            alts="Big Zuerich,Grosszurich",
        ),
    ]
    r = _build(tmp_path, [], cities)
    # The ASCII spelling has its own column at any population (loaded as a
    # primary name) and is not repeated among the alternate names.
    assert [r.places[g]["ascii"] for g in "123"] == ["Zuerich", "Xi'an", "Big Zuerich"]
    assert r.places["1"]["alt_names"] == []
    assert r.places["2"]["alt_names"] == []
    assert r.places["3"]["alt_names"] == ["grosszurich"]


# ── Airports ───────────────────────────────────────────────────────────────


def _place(gid, name, pop, cc="XA", ascii_name=None, score=None):
    gen = _gen()
    return gen.Place(
        geonameid=str(gid),
        name=name,
        ascii_name=ascii_name or name,
        country_code=cc,
        admin1="01",
        population=pop,
        score=pop if score is None else score,
        lat=0.0,
        lng=0.0,
        folded=fold_place(name),
    )


def _chain(name, near, first=(), municipality="", cc="XA"):
    a = {"name": name, "country_code": cc}
    return _gen()._computed_city(a, near, {str(g) for g in first}, municipality)


def test_display_chain_name_match_within_40km_wins():
    trento, verona = _place(1, "Trento", 900_000), _place(2, "Verona", 250_000)
    near = [(10, trento), (35, verona)]
    assert _chain("Verona Villafranca Airport", near, first=[1]) == (
        "Verona",
        "name",
    )
    # Beyond 40 km the name match does not count.
    assert _chain("Verona Villafranca Airport", [(10, trento), (45, verona)], [1]) == (
        "Trento",
        "first-link",
    )


def test_display_chain_name_match_ignores_generic_words_and_partial_words():
    near = [(5, _place(1, "International", 9_000)), (6, _place(2, "Bur", 9_000))]
    city, rule = _chain("Burbank International Airport", near, municipality="Burbank")
    assert rule == "nearest"


def test_display_chain_first_link_within_40km_then_nearest_within_15km():
    big, near_town = _place(1, "Bigtown", 900_000), _place(2, "Hamlet", 1_500)
    # Highest score among first-link places within 40 km.
    assert _chain("Xyz Airport", [(12, near_town), (30, big)], first=[1, 2]) == (
        "Bigtown",
        "first-link",
    )
    # A first-link place beyond 40 km does not count → nearest within 15 km.
    assert _chain("Xyz Airport", [(12, near_town), (45, big)], first=[1]) == (
        "Hamlet",
        "nearest",
    )


def test_display_chain_municipality_then_airport_name_never_empty():
    far = [(20, _place(1, "Hamlet", 1_500))]
    assert _chain("Xyz Airport", far, municipality="Farm (X), Y") == (
        "Farm",
        "municipality",
    )
    assert _chain("Boulia Airport", far) == ("Boulia", "airport-name")
    assert _chain("International Airport", []) == (
        "International Airport",
        "airport-name",
    )


def test_display_chain_only_uses_places_in_the_airports_country():
    famous = _place(1, "Famous", 2_000_000, cc="XB")
    assert _chain("Famous Airport", [(5, famous)], first=[1], municipality="Mun") == (
        "Mun",
        "municipality",
    )


@pytest.mark.parametrize(
    ("name", "ascii_name", "shown"),
    [
        ("Marsá Maţrūḩ", "Marsa Matruh", "Marsa Matruh"),
        ("Kolhāpur", "Kolhapur", "Kolhāpur"),  # Latin Extended-A is kept
        (
            "Del Carmen, Surigao del Norte",
            "Del Carmen, Surigao del Norte",
            "Del Carmen",
        ),
        ("Zürich", "Zurich", "Zürich"),
        ("Cheongju-si", "Cheongju-si", "Cheongju"),
        ("Tottori-shi", "Tottori-shi", "Tottori"),
        ("Yangyang-gun", "Yangyang-gun", "Yangyang"),
        ("Chūō-ku", "Chuo-ku", "Chūō"),
        ("Shiraoi-cho", "Shiraoi-cho", "Shiraoi"),
        ("Oki-machi", "Oki-machi", "Oki"),
        ("Kami-mura", "Kami-mura", "Kami"),
        ("Hamburg-Nord", "Hamburg-Nord", "Hamburg-Nord"),
    ],
)
def test_display_names_prefer_ascii_for_scholarly_transliterations(
    name, ascii_name, shown
):
    assert _gen().display_name(name, ascii_name) == shown
    place = _place(1, name, 5_000, ascii_name=ascii_name)
    assert _chain("Xyz Airport", [(5, place)])[0] == shown


def test_display_city_ignores_famous_places_in_other_countries(tmp_path):
    # A border airport in XB next to a famous XA city that links it first.
    airports = [_oa("BRD", _LAT, _LNG, cc="XB", municipality="Bordertown")]
    cities = [
        _city(1, "Famous", _north(_LAT, 10), _LNG, 2_000_000, alts="A,B,C,D"),
        _city(2, "Village", _north(_LAT, -5), _LNG, 1_500, cc="XB"),
    ]
    r = _build(tmp_path, airports, cities)
    assert r.airports["BRD"]["city"] == "Village"


def test_display_city_prefers_places_whose_first_airport_it_is(tmp_path):
    # Bigtown links MAIN first and SIDE second; Sidetown (25 km past SIDE)
    # links SIDE first.
    airports = [
        _oa("MAIN", _LAT, _LNG),
        _oa("SIDE", _north(_LAT, 25), _LNG),
    ]
    cities = [
        _city(1, "Bigtown", _LAT, _LNG, 900_000, alts="A,B,C"),
        _city(2, "Sidetown", _north(_LAT, 50), _LNG, 3_000),
    ]
    r = _build(tmp_path, airports, cities)
    assert _links(r, 2)[0] == "SIDE"
    assert r.airports["SIDE"]["city"] == "Sidetown"


def test_large_airport_without_a_place_falls_back_and_is_reported(tmp_path):
    airports = [
        _oa("RMT", 40.0, 40.0, municipality="Far Town (Ward 3), Hills"),
        _oa("NOM", 50.0, 50.0, municipality="", name="Boulia Airport"),
    ]
    r = _build(tmp_path, airports, [])
    assert r.airports["RMT"]["city"] == "Far Town"
    assert r.airports["NOM"]["city"] == "Boulia"
    report = "\n".join(r.report)
    assert "RMT" in report and "NOM" in report


def test_curated_display_city_wins_over_computed(tmp_path):
    airports = [_oa("MXP", _north(_LAT, 40), _LNG, municipality="Ferno (VA)")]
    cities = [_city(1, "Ferno", _north(_LAT, 40), _LNG, 7_000)]
    curated = [
        ("MXP", "LIMC", "Malpensa", "Milan", "Xland Curated", "XA", 1.0, 1.0),
    ]
    r = _build(tmp_path, airports, cities, curated=curated)
    row = r.airports["MXP"]
    assert row["city"] == "Milan"
    # OA stays authoritative for name and coordinates.
    assert row["name"] == "MXP Airport"
    assert row["lat"] == pytest.approx(_north(_LAT, 40))
    # Curated country spelling is kept for the curated country's airports.
    assert row["country"] == "Xland Curated"


def test_curated_country_spelling_applies_to_the_whole_country(tmp_path):
    airports = [_oa("AAA", _LAT, _LNG), _oa("BBB", 30.0, 30.0, cc="XB")]
    curated = [("AAA", "XAAA", "A", "Acity", "Xland Curated", "XA", _LAT, _LNG)]
    r = _build(tmp_path, airports, [], curated=curated)
    assert r.airports["AAA"]["country"] == "Xland Curated"
    assert r.airports["BBB"]["country"] == "Yland"


def test_curated_codes_unscheduled_in_oa_kept_with_scheduled_0(tmp_path):
    airports = [
        _oa("OLD", _north(_LAT, 5), _LNG, scheduled="no", name="Old Intl"),
        _oa("NEW", _north(_LAT, 30), _LNG),
    ]
    curated = [
        ("OLD", "XOLD", "Old", "Oldcity", "Xland", "XA", 0.0, 0.0),
        ("GON", "XGON", "Gone Intl", "Gonecity", "Xland", "XA", 11.0, 21.0),
    ]
    cities = [_city(1, "Oldcity", _LAT, _LNG, 50_000)]
    r = _build(tmp_path, airports, cities, curated=curated)
    old = r.airports["OLD"]
    assert old["scheduled"] == 0
    assert old["name"] == "Old Intl"
    assert old["city"] == "Oldcity"
    gone = r.airports["GON"]
    assert gone["scheduled"] == 0
    assert gone["type_rank"] == 9
    assert (gone["name"], gone["city"], gone["lat"]) == ("Gone Intl", "Gonecity", 11.0)
    assert r.airports["NEW"]["scheduled"] == 1
    # Unscheduled airports are never linked.
    assert _links(r, 1) == ["NEW"]
    report = "\n".join(r.report)
    assert "OLD" in report and "GON" in report


def test_airport_row_fields(tmp_path):
    airports = [_oa("MED", _LAT, _LNG, kind="medium_airport", region="XA-07")]
    r = _build(tmp_path, airports, [])
    row = r.airports["MED"]
    assert row["type_rank"] == 1
    assert row["region"] == "XA-07"
    assert row["icao"] == "XMED"
    assert row["country"] == "Xland"
    assert row["country_code"] == "XA"


# ── Admin1 + outputs ───────────────────────────────────────────────────────


def test_admin1_rows(tmp_path):
    r = _build(tmp_path, [], [])
    assert r.admin1 == [("XA.01", "Nörth Prövince", "north province")]


def _sample_sources(tmp_path):
    airports = [
        _oa("AAA", _north(_LAT, 20), _LNG, municipality="Suburb (XY)"),
        _oa("BBB", _north(_LAT, -45), _LNG, kind="medium_airport"),
    ]
    cities = [
        _city(1, "Bigtown", _LAT, _LNG, 900_000, alts="Big Town,Grossstadt,BT"),
        _city(2, "Smalltown", _north(_LAT, -40), _LNG, 2_000),
    ]
    curated = [("BBB", "XBBB", "B", "Bee", "Xland", "XA", 0.0, 0.0)]
    return _write_sources(tmp_path, airports, cities), curated


def test_outputs_are_deterministic(tmp_path):
    gen = _gen()
    (oa, cities, admin1), curated = _sample_sources(tmp_path)
    outs = []
    for name in ("one", "two"):
        out = tmp_path / name
        gen.write_outputs(gen.build(oa, cities, admin1, curated), out)
        outs.append(out)
    for fname in ("airports.csv", "places.csv.gz", "admin1.csv"):
        assert (outs[0] / fname).read_bytes() == (outs[1] / fname).read_bytes()
    raw = (outs[0] / "places.csv.gz").read_bytes()
    assert raw[4:8] == b"\0\0\0\0"  # gzip mtime = 0


def test_output_file_format(tmp_path):
    gen = _gen()
    (oa, cities, admin1), curated = _sample_sources(tmp_path)
    out = tmp_path / "out"
    gen.write_outputs(gen.build(oa, cities, admin1, curated), out)
    with open(out / "airports.csv", encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    assert list(rows[0]) == [
        "iata",
        "icao",
        "name",
        "city",
        "country",
        "country_code",
        "region",
        "type_rank",
        "scheduled",
        "lat",
        "lng",
    ]
    assert [r["iata"] for r in rows] == ["AAA", "BBB"]
    # AAA: nobody links it first and no place is within 15 km → municipality.
    assert rows[0]["city"] == "Suburb" and rows[1]["city"] == "Bee"
    with gzip.open(out / "places.csv.gz", "rt", encoding="utf-8", newline="") as f:
        places = list(csv.DictReader(f))
    assert list(places[0]) == [
        "geonameid",
        "name",
        "country_code",
        "admin1",
        "population",
        "score",
        "lat",
        "lng",
        "airports",
        "alt_names",
        "ascii",
    ]
    big = places[0]
    assert big["airports"] == "BBB AAA"  # curated BBB ranks first
    assert big["alt_names"] == "big town|grossstadt"
    with open(out / "admin1.csv", encoding="utf-8", newline="") as f:
        assert list(csv.reader(f))[0] == ["code", "name", "folded_name"]


# ── Spot checks of the committed data ──────────────────────────────────────


@functools.cache
def _committed_airports() -> dict[str, dict]:
    with open(_DATA / "airports.csv", encoding="utf-8", newline="") as f:
        return {r["iata"]: r for r in csv.DictReader(f)}


@functools.cache
def _committed_places() -> list[dict]:
    raw = (_DATA / "places.csv.gz").read_bytes()
    with gzip.open(io.BytesIO(raw), "rt", encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def _places(name, cc, admin1=None):
    return [
        p
        for p in _committed_places()
        if p["name"] == name
        and p["country_code"] == cc
        and (admin1 is None or p["admin1"] == admin1)
    ]


def _top_score(name, cc, admin1=None):
    return max(int(p["score"]) for p in _places(name, cc, admin1))


def test_committed_data_size_within_budget():
    total = sum(
        (_DATA / f).stat().st_size
        for f in ("airports.csv", "places.csv.gz", "admin1.csv")
    )
    assert total <= 8 * 1024 * 1024


@pytest.mark.parametrize(
    ("iata", "city"),
    [
        ("MXP", "Milan"),
        ("BRU", "Brussels"),
        ("CCS", "Caracas"),
        ("JMK", "Mykonos"),
        ("RUN", "Saint-Denis"),
        ("DJT", "West Palm Beach"),
    ],
)
def test_committed_display_cities(iata, city):
    assert _committed_airports()[iata]["city"] == city


@pytest.mark.parametrize("iata", ["KTI", "SAI", "BSZ", "RMO", "UBN", "DSS", "FNA"])
def test_committed_replacement_codes_are_scheduled(iata):
    assert _committed_airports()[iata]["scheduled"] == "1"


@pytest.mark.parametrize("iata", ["PNH", "REP", "FRU", "PBI", "KIV", "ULN", "DKR"])
def test_committed_obsolete_codes_are_not_scheduled(iata):
    # Dropped from the curated list, so absent (or unscheduled if OA lists it).
    assert _committed_airports().get(iata, {}).get("scheduled") != "1"


@pytest.mark.parametrize("iata", ["GIB", "BTS", "BTH", "AQJ", "DJT"])
def test_committed_display_city_is_in_the_airports_own_country(iata):
    airport = _committed_airports()[iata]
    assert _places(airport["city"], airport["country_code"]), airport


def test_committed_milan_links_mxp_and_lin():
    (milan,) = _places("Milan", "IT")
    assert {"MXP", "LIN"} <= set(milan["airports"].split())


def test_committed_zermatt_links_swiss_airports():
    (zermatt,) = _places("Zermatt", "CH")
    codes = zermatt["airports"].split()
    assert codes
    assert all(_committed_airports()[c]["country_code"] == "CH" for c in codes)


def test_committed_scores_rank_namesakes():
    assert _top_score("Portland", "US", "OR") >= 3 * _top_score("Portland", "US", "ME")
    assert _top_score("Interlaken", "CH") > _top_score("Interlaken", "US")
    es, ve = _top_score("Valencia", "ES"), _top_score("Valencia", "VE")
    assert max(es, ve) < 3 * min(es, ve)


def test_committed_places_link_only_scheduled_airports():
    airports = _committed_airports()
    scheduled = {code for code, a in airports.items() if a["scheduled"] == "1"}
    linked = {c for p in _committed_places() for c in p["airports"].split()}
    assert linked <= scheduled


@pytest.mark.parametrize(
    ("iata", "city"),
    [
        ("VRN", "Verona"),
        ("FLL", "Fort Lauderdale"),
        ("CZM", "Cozumel"),
        ("TSF", "Treviso"),
        ("BES", "Brest"),
        ("ZTH", "Zakynthos"),
        ("KIS", "Kisumu"),
        ("YIW", "Yiwu"),
        ("NAV", "Nevşehir"),
        ("BUR", "Burbank"),
        ("ONT", "Ontario"),
        ("CJJ", "Cheongju"),
        ("TTJ", "Tottori"),
        # Curated served-city overrides (fix round 3).
        ("WSI", "Sydney"),
        ("AVV", "Melbourne"),
        ("THR", "Tehran"),
        ("NLU", "Mexico City"),
        ("DXN", "Noida"),
        ("DJE", "Djerba"),
        ("GSM", "Qeshm"),
        ("LXA", "Lhasa"),
        ("RKZ", "Shigatse"),
        ("YNT", "Yantai"),
        ("UIH", "Qui Nhon"),
    ],
)
def test_committed_large_airport_display_cities(iata, city):
    assert _committed_airports()[iata]["city"] == city


def test_committed_display_cities_never_empty_or_comma():
    for a in _committed_airports().values():
        assert a["city"].strip() and "," not in a["city"], a


# ── Golden set (data level) ────────────────────────────────────────────────
# tests/data/golden_places.csv: query, expected_airports, match, expected_country
# (ISO alpha-2), scope, display_city. Rows with scope "data" are checked here
# against the committed files: the highest-scoring place whose folded name is
# the query in that country, and its linked airports — exact (same list),
# subset (all expected present) or first (the first link is one of them) —
# plus, when given, the display city of the first expected airport. Rows with
# scope "task3" (lookup_city_iata) and "autocomplete" (search_airports) are
# checked at runtime by tests/test_golden_places_runtime.py.

_GOLDEN = _BACKEND / "tests" / "data" / "golden_places.csv"


def _golden_rows(scope):
    with open(_GOLDEN, encoding="utf-8", newline="") as f:
        return [r for r in csv.DictReader(f) if r["scope"] == scope]


@functools.cache
def _places_by_name() -> dict[tuple[str, str], dict]:
    best: dict[tuple[str, str], dict] = {}
    for p in _committed_places():
        key = (fold_place(p["name"]), p["country_code"])
        if key not in best or int(p["score"]) > int(best[key]["score"]):
            best[key] = p
    return best


def test_golden_set_shape():
    with open(_GOLDEN, encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    assert len(rows) >= 200
    assert {r["match"] for r in rows} <= {"exact", "subset", "first", "none"}
    assert {r["scope"] for r in rows} == {"data", "task3", "autocomplete"}
    airports = _committed_airports()
    for r in rows:
        for code in r["expected_airports"].split():
            assert airports[code]["scheduled"] == "1" or r["match"] == "none", r


@pytest.mark.parametrize(
    "row", _golden_rows("data"), ids=lambda r: f"{r['query']}-{r['expected_country']}"
)
def test_golden_place_links(row):
    place = _places_by_name().get((fold_place(row["query"]), row["expected_country"]))
    assert place, f"no place {row['query']!r} in {row['expected_country']}"
    links = place["airports"].split()
    expected = row["expected_airports"].split()
    if row["match"] == "exact":
        assert links == expected
    elif row["match"] == "subset":
        assert set(expected) <= set(links), links
    else:
        assert links and links[0] in expected, links
    if row["display_city"]:
        city = _committed_airports()[expected[0]]["city"]
        assert fold_place(city) == fold_place(row["display_city"])
