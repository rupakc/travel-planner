"""Versioned place-data seeding, schema migration and closing connections.

Unit tests run against a throwaway DB file and small fixture data files; the
session DB (seeded once by the ``client`` fixture's startup) is checked
against the committed data.
"""

import csv
import gzip
import logging
import re
import sqlite3
from pathlib import Path

import pytest

from app.db import database, seed_airports
from app.db.database import get_connection

_AIRPORT_COLS = (
    "iata,icao,name,city,country,country_code,region,type_rank,scheduled,lat,lng"
).split(",")
_PLACE_COLS = (
    "geonameid,name,country_code,admin1,population,score,lat,lng,airports,alt_names,"
    "ascii"
).split(",")

_AIRPORTS = [
    ["BER", "EDDB", "Berlin Brandenburg Airport", "Berlin", "Germany", "DE",
     "DE-BR", "0", "1", "52.36", "13.50"],
    ["KTI", "VDTI", "Techo International Airport", "Phnom Penh", "Cambodia",
     "KH", "KH-8", "0", "1", "11.36", "104.92"],
    ["KBP", "UKBB", "Boryspil International Airport", "Kiev", "Ukraine", "UA",
     "UA-32", "0", "0", "50.34", "30.89"],
    ["PDX", "KPDX", "Portland International Airport", "Portland",
     "United States", "US", "US-OR", "0", "1", "45.58", "-122.60"],
]  # fmt: skip
_PLACES = [
    ["2950159", "Berlin", "DE", "16", "3426354", "900", "52.52", "13.41", "BER",
     "berlino|berlim", "Berlin"],
    ["1821306", "Phnom Penh", "KH", "12", "1573544", "500", "11.56", "104.92",
     "KTI", "", "Phnom Penh"],
    ["2867714", "München", "DE", "02", "1260391", "800", "48.14", "11.58", "",
     "muenchen", "Munich"],
]  # fmt: skip
_ADMIN1 = [["DE.02", "Bavaria", "bavaria"], ["DE.16", "Berlin", "berlin"]]


_FEATURE_COLS = (
    "geonameid,name,ascii,country_code,admin1,feature_code,notability,lat,lng,"
    "airports,alt_names"
).split(",")
_FEATURES = [
    ["2078127", "Kakadu National Park", "Kakadu National Park", "AU", "03", "PRK",
     "58", "-13.0", "132.5", "DRW", "parc national de kakadu"],
    ["1283416", "Mount Everest", "Mount Everest", "NP", "00", "MT", "186",
     "27.99", "86.93", "KTM LUA", "chomolungma|sagarmatha"],
]  # fmt: skip


def _write_features(directory: Path, features=_FEATURES) -> None:
    with gzip.open(
        directory / "features.csv.gz", "wt", newline="", encoding="utf-8"
    ) as f:
        csv.writer(f).writerows([_FEATURE_COLS, *features])


def _write_data(
    directory: Path, airports=_AIRPORTS, places=_PLACES, admin1=_ADMIN1
) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    with open(directory / "airports.csv", "w", newline="", encoding="utf-8") as f:
        csv.writer(f).writerows([_AIRPORT_COLS, *airports])
    with gzip.open(
        directory / "places.csv.gz", "wt", newline="", encoding="utf-8"
    ) as f:
        csv.writer(f).writerows([_PLACE_COLS, *places])
    with open(directory / "admin1.csv", "w", newline="", encoding="utf-8") as f:
        csv.writer(f).writerows([["code", "name", "folded_name"], *admin1])
    return directory


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    """Point get_connection() at a fresh DB file for this test."""
    path = tmp_path / "db" / "airports.db"
    path.parent.mkdir()
    monkeypatch.setattr(database, "_db_path", lambda: path)
    return path


@pytest.fixture
def data_dir(tmp_path):
    return _write_data(tmp_path / "data")


def _rows(sql: str, params=()) -> list[sqlite3.Row]:
    with get_connection() as conn:
        return conn.execute(sql, params).fetchall()


def _make_old_schema_db(path: Path) -> None:
    """An airports DB as the pre-dataset code created it, with a stale seed
    row (PNH), an outdated seed row (BER) and a web-saved row (XWB)."""
    conn = sqlite3.connect(path)
    conn.executescript("""
        CREATE TABLE airports (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            iata_code TEXT UNIQUE NOT NULL, icao_code TEXT, name TEXT NOT NULL,
            city TEXT NOT NULL, country TEXT NOT NULL, country_code TEXT,
            latitude REAL, longitude REAL);
        INSERT INTO airports (iata_code, icao_code, name, city, country,
                              country_code, latitude, longitude) VALUES
            ('BER', 'EDDB', 'Old Berlin Name', 'Berlin', 'Germany', 'DE', 1, 2),
            ('PNH', 'VDPP', 'Phnom Penh International', 'Phnom Penh',
             'Cambodia', 'KH', 11.5, 104.8);
        INSERT INTO airports (iata_code, name, city, country)
            VALUES ('XWB', 'Webtown Airport', 'Webtown', 'Freedonia');
    """)
    conn.commit()
    conn.close()


# ── get_connection() ─────────────────────────────────────────────────────────


def test_connection_is_closed_after_the_block(temp_db):
    with get_connection() as conn:
        conn.execute("SELECT 1")
    with pytest.raises(sqlite3.ProgrammingError):
        conn.execute("SELECT 1")


def test_connection_commits_on_success(temp_db):
    with get_connection() as conn:
        conn.execute("CREATE TABLE t (x INTEGER)")
        conn.execute("INSERT INTO t VALUES (1)")
    assert [r["x"] for r in _rows("SELECT x FROM t")] == [1]


def test_connection_rolls_back_and_closes_on_error(temp_db):
    with get_connection() as conn:
        conn.execute("CREATE TABLE t (x INTEGER)")
    with pytest.raises(RuntimeError):
        with get_connection() as conn:
            conn.execute("INSERT INTO t VALUES (1)")
            raise RuntimeError("boom")
    with pytest.raises(sqlite3.ProgrammingError):
        conn.execute("SELECT 1")
    assert _rows("SELECT x FROM t") == []


# ── Schema migration ─────────────────────────────────────────────────────────


def test_fresh_db_has_place_tables_and_name_index(temp_db, data_dir):
    seed_airports.seed(data_dir)
    tables = {r["name"] for r in _rows("SELECT name FROM sqlite_master")}
    assert {"airports", "places", "place_names", "admin1", "meta"} <= tables
    index_cols = _rows(
        "SELECT ii.name FROM sqlite_master m, pragma_index_info(m.name) ii "
        "WHERE m.type = 'index' AND m.tbl_name = 'place_names'"
    )
    assert "name_folded" in {r["name"] for r in index_cols}


def test_existing_db_migrates_in_place(temp_db, data_dir):
    _make_old_schema_db(temp_db)
    seed_airports.seed(data_dir)
    cols = {r["name"] for r in _rows("PRAGMA table_info(airports)")}
    assert {"region", "type_rank", "scheduled"} <= cols
    rows = {r["iata_code"]: r for r in _rows("SELECT * FROM airports")}
    # dataset airport upserted over the old seed row, id kept
    assert rows["BER"]["name"] == "Berlin Brandenburg Airport"
    assert rows["BER"]["id"] == 1
    assert (rows["BER"]["region"], rows["BER"]["type_rank"]) == ("DE-BR", 0)
    # web-saved row kept untouched and scheduled
    assert rows["XWB"]["city"] == "Webtown"
    assert rows["XWB"]["scheduled"] == 1
    # a seed row the dataset dropped is kept but no longer scheduled
    assert rows["PNH"]["scheduled"] == 0
    assert rows["KBP"]["scheduled"] == 0
    assert rows["KTI"]["scheduled"] == 1


def test_create_tables_is_idempotent_on_a_migrated_db(temp_db, data_dir):
    _make_old_schema_db(temp_db)
    database.create_tables()
    database.create_tables()
    cols = [r["name"] for r in _rows("PRAGMA table_info(airports)")]
    assert cols.count("region") == 1


def test_old_places_table_gains_the_satellite_column(temp_db, data_dir):
    conn = sqlite3.connect(temp_db)
    conn.execute(
        "CREATE TABLE places (geonameid INTEGER PRIMARY KEY, name TEXT NOT NULL,"
        " country_code TEXT NOT NULL, admin1 TEXT, population INTEGER,"
        " score INTEGER, lat REAL, lng REAL, airports TEXT)"
    )
    conn.commit()
    conn.close()
    seed_airports.seed(data_dir)
    cols = [r["name"] for r in _rows("PRAGMA table_info(places)")]
    assert cols[-1] == "satellite"
    assert _rows("SELECT satellite FROM places WHERE geonameid = 2950159")[0][0] == 0


# ── Versioned seeding ────────────────────────────────────────────────────────


def test_seed_loads_satellite_flags(temp_db, data_dir):
    cols = [*_PLACE_COLS, "satellite"]
    places = [[*_PLACES[0], "0"], [*_PLACES[1], "1"], [*_PLACES[2], "0"]]
    with gzip.open(data_dir / "places.csv.gz", "wt", newline="", encoding="utf-8") as f:
        csv.writer(f).writerows([cols, *places])
    seed_airports.seed(data_dir)
    flags = dict(_rows("SELECT geonameid, satellite FROM places"))
    assert flags == {2950159: 0, 1821306: 1, 2867714: 0}


def test_seed_loads_features_and_their_names(temp_db, data_dir):
    _write_features(data_dir)
    seed_airports.seed(data_dir)
    kakadu = _rows("SELECT * FROM features WHERE geonameid = 2078127")[0]
    assert (kakadu["name"], kakadu["country_code"], kakadu["feature_code"]) == (
        "Kakadu National Park",
        "AU",
        "PRK",
    )
    assert (kakadu["notability"], kakadu["airports"]) == (58, "DRW")
    names = {
        (r["name_folded"], r["tier"])
        for r in _rows("SELECT * FROM feature_names WHERE geonameid = 2078127")
    }
    # the name without its generic part is a primary name too ("Kakadu")
    assert names == {
        ("kakadu national park", 0),
        ("kakadu", 0),
        ("parc national de kakadu", 1),
    }
    everest = {
        r["name_folded"]
        for r in _rows("SELECT * FROM feature_names WHERE geonameid = 1283416")
    }
    assert {"mount everest", "everest", "sagarmatha"} <= everest
    index_cols = _rows(
        "SELECT ii.name FROM sqlite_master m, pragma_index_info(m.name) ii "
        "WHERE m.type = 'index' AND m.tbl_name = 'feature_names'"
    )
    assert "name_folded" in {r["name"] for r in index_cols}


def test_seed_without_a_features_file_leaves_features_empty(temp_db, data_dir):
    seed_airports.seed(data_dir)
    assert _rows("SELECT COUNT(*) FROM features")[0][0] == 0


def test_features_file_is_part_of_the_data_version(data_dir):
    before = seed_airports.place_data_version(data_dir)
    _write_features(data_dir)
    assert seed_airports.place_data_version(data_dir) != before


def test_feature_tables_are_regenerable_place_tables():
    assert {"features", "feature_names"} <= set(seed_airports.PLACE_TABLES)


def test_seed_loads_places_names_and_admin1(temp_db, data_dir):
    assert seed_airports.seed(data_dir) is True
    berlin = _rows("SELECT * FROM places WHERE geonameid = 2950159")[0]
    assert (berlin["name"], berlin["country_code"], berlin["admin1"]) == (
        "Berlin",
        "DE",
        "16",
    )
    assert (berlin["population"], berlin["score"], berlin["airports"]) == (
        3426354,
        900,
        "BER",
    )
    names = {
        (r["name_folded"], r["tier"])
        for r in _rows("SELECT * FROM place_names WHERE geonameid = 2867714")
    }
    # The ASCII spelling loads as tier 0 with the name.
    assert names == {("munchen", 0), ("munich", 0), ("muenchen", 1)}
    admin = _rows("SELECT * FROM admin1 WHERE code = 'DE.02'")[0]
    assert (admin["name"], admin["folded_name"]) == ("Bavaria", "bavaria")


def test_seed_stores_the_data_version(temp_db, data_dir):
    seed_airports.seed(data_dir)
    version = _rows("SELECT value FROM meta WHERE key = 'place_data_version'")
    assert version[0]["value"] == seed_airports.place_data_version(data_dir)


def test_unchanged_version_skips_the_load(temp_db, data_dir):
    assert seed_airports.seed(data_dir) is True
    with get_connection() as conn:
        conn.execute("UPDATE airports SET name = 'Edited' WHERE iata_code = 'BER'")
    assert seed_airports.seed(data_dir) is False
    assert _rows("SELECT name FROM airports WHERE iata_code = 'BER'")[0][0] == (
        "Edited"
    )


def test_changed_data_reseeds_and_rebuilds(temp_db, data_dir, tmp_path):
    seed_airports.seed(data_dir)
    old = seed_airports.place_data_version(data_dir)
    _write_data(data_dir, places=_PLACES[:1])
    assert seed_airports.place_data_version(data_dir) != old
    assert seed_airports.seed(data_dir) is True
    assert [r[0] for r in _rows("SELECT geonameid FROM places")] == [2950159]
    assert {r[0] for r in _rows("SELECT geonameid FROM place_names")} == {2950159}


def test_web_saved_rows_survive_a_reseed(temp_db, data_dir):
    seed_airports.seed(data_dir)
    with get_connection() as conn:
        conn.execute(
            "INSERT INTO airports (iata_code, name, city, country)"
            " VALUES ('XWC', 'Web Airport', 'Webcity', 'Somewhere')"
        )
    _write_data(data_dir, places=_PLACES[:1])
    seed_airports.seed(data_dir)
    row = _rows("SELECT * FROM airports WHERE iata_code = 'XWC'")[0]
    assert (row["city"], row["scheduled"]) == ("Webcity", 1)


def test_failed_load_rolls_back_everything(temp_db, data_dir):
    """A failure after the airport upsert (here a duplicate admin1 code, the
    last table written) leaves the DB exactly as it was."""
    _make_old_schema_db(temp_db)
    _write_data(data_dir, admin1=[*_ADMIN1, _ADMIN1[0]])
    with pytest.raises(sqlite3.IntegrityError):
        seed_airports.seed(data_dir)
    assert _rows("SELECT name FROM airports WHERE iata_code = 'BER'")[0][0] == (
        "Old Berlin Name"
    )
    assert _rows("SELECT scheduled FROM airports WHERE iata_code = 'PNH'")[0][0] == 1
    assert _rows("SELECT * FROM meta") == []
    assert _rows("SELECT * FROM places") == []
    assert _rows("SELECT * FROM place_names") == []


def test_unparsable_data_fails_before_writing(temp_db, data_dir):
    bad = [*_PLACES, ["999", "Broken", "DE", "16", "not-a-number", "1", "0",
                      "0", "", ""]]  # fmt: skip
    _write_data(data_dir, places=bad)
    with pytest.raises(ValueError):
        seed_airports.seed(data_dir)
    assert _rows("SELECT * FROM airports") == []
    assert _rows("SELECT * FROM meta") == []


def test_curated_airports_keep_curated_order_on_a_fresh_db(temp_db, data_dir):
    """lookup_city_iata ranks a city's airports by insertion order."""
    airports = [
        ["AAA", "", "A", "Testcity", "X", "XX", "XX-1", "0", "1", "0", "0"],
        ["ZZZ", "", "Z", "Testcity", "X", "XX", "XX-1", "0", "1", "0", "0"],
        ["MMM", "", "M", "Other", "X", "XX", "XX-1", "0", "1", "0", "0"],
    ]
    _write_data(data_dir, airports=airports)
    curated = [("ZZZ",), ("AAA",)]
    seed_airports.seed(data_dir, curated=curated)
    order = [r[0] for r in _rows("SELECT iata_code FROM airports ORDER BY id")]
    assert order == ["ZZZ", "AAA", "MMM"]


def test_seed_logs_counts_and_seconds(temp_db, data_dir, caplog):
    with caplog.at_level(logging.INFO, logger="app.db.seed_airports"):
        seed_airports.seed(data_dir)
    line = next(r.getMessage() for r in caplog.records if "place data" in r.message)
    assert "4 airports" in line
    assert "3 places" in line
    assert "7 names" in line
    assert "2 admin1" in line
    assert re.search(r"in \d+\.\d+ s", line), line


# ── Session DB: the committed dataset ────────────────────────────────────────


def test_session_db_holds_the_committed_dataset(client):
    data = seed_airports.PLACE_DATA_DIR
    with open(data / "airports.csv", encoding="utf-8") as f:
        airports = sum(1 for _ in f) - 1
    with gzip.open(data / "places.csv.gz", "rt", encoding="utf-8") as f:
        places = sum(1 for _ in csv.reader(f)) - 1
    seeded = _rows("SELECT COUNT(*) FROM airports WHERE type_rank IS NOT NULL")[0][0]
    assert seeded == airports
    assert _rows("SELECT COUNT(*) FROM places")[0][0] == places
    assert (
        _rows("SELECT value FROM meta WHERE key = 'place_data_version'")[0][0]
        == seed_airports.place_data_version()
    )
    pdx = _rows("SELECT region, type_rank, scheduled FROM airports "
                "WHERE iata_code = 'PDX'")[0]  # fmt: skip
    assert tuple(pdx) == ("US-OR", 0, 1)


# ── Regions come from the dataset; only the deliberate extras are curated ──


@pytest.mark.parametrize(
    ("code", "country", "region", "expected"),
    [
        ("PDX", "US", "US-OR", {"or"}),
        ("IAD", "US", "US-VA", {"va", "dc"}),
        ("DCA", "US", "US-VA", {"va", "dc"}),
        ("MCI", "US", "US-MO", {"mo", "ks"}),
        ("SYD", "AU", "AU-NSW", {"nsw"}),
        ("YYZ", "CA", "CA-ON", {"on"}),
        ("GRU", "BR", "BR-SP", {"sp"}),
        ("LHR", "GB", "GB-ENG", set()),  # regions only for US/CA/AU/BR
        ("XWB", None, None, set()),  # web-saved row
    ],
)
def test_airport_regions_from_dataset_region(code, country, region, expected):
    from app.db.airport_regions import airport_regions

    assert airport_regions(code, country, region) == expected


def test_only_deliberate_region_overrides_remain():
    from app.db.airport_regions import REGION_OVERRIDES

    assert REGION_OVERRIDES == {
        "IAD": frozenset({"dc"}),
        "DCA": frozenset({"dc"}),
        "MCI": frozenset({"ks"}),
    }


# ── lookup_city_iata on the dataset keeps today's behaviour ─────────────────


def test_unscheduled_airport_is_never_returned(client, extra_airports_sched):
    extra_airports_sched("ZQG", "Closedville", "United States", "US", 0)
    extra_airports_sched("ZQH", "Closedville", "United States", "US", 1)
    assert database.lookup_city_iata("Closedville") == "ZQH"
    # an unscheduled code is not a known label prefix: the text stays whole
    assert database.lookup_city_iata("ZQG — Closedville") is None


def test_dataset_namesake_airport_does_not_change_curated_city(client):
    """YXU (London, Ontario) is in the dataset but not curated: "London"
    keeps the curated answer ("London, Ontario" → YXU via the place data)."""
    assert _rows("SELECT city FROM airports WHERE iata_code = 'YXU'")[0][0] == (
        "London"
    )
    assert database.lookup_city_iata("London") == "LHR,LGW,STN"


@pytest.fixture
def extra_airports_sched():
    codes: list[str] = []

    def add(code, city, country, country_code, scheduled):
        with get_connection() as conn:
            conn.execute(
                "INSERT INTO airports (iata_code, name, city, country,"
                " country_code, scheduled) VALUES (?, ?, ?, ?, ?, ?)",
                (code, f"{city} Test Airport", city, country, country_code, scheduled),
            )
        codes.append(code)

    yield add
    with get_connection() as conn:
        conn.executemany(
            "DELETE FROM airports WHERE iata_code = ?", [(c,) for c in codes]
        )


def test_seeding_waits_up_to_30s_for_another_workers_lock(
    temp_db, data_dir, monkeypatch
):
    import contextlib

    statements: list[str] = []
    real = seed_airports.get_connection

    @contextlib.contextmanager
    def traced():
        with real() as conn:
            conn.set_trace_callback(statements.append)
            yield conn

    monkeypatch.setattr(seed_airports, "get_connection", traced)
    seed_airports.seed(data_dir)
    lock = statements.index("BEGIN IMMEDIATE")
    assert "PRAGMA busy_timeout=30000" in statements[:lock]
    assert seed_airports.SEED_LOCK_TIMEOUT_MS == 30_000


# ── Task 2 review fixes ──────────────────────────────────────────────────────


def test_existing_db_migration_keeps_user_tables(temp_db, data_dir):
    _make_old_schema_db(temp_db)
    conn = sqlite3.connect(temp_db)
    conn.executescript("""
        CREATE TABLE users (id TEXT PRIMARY KEY, username TEXT);
        INSERT INTO users VALUES ('u1', 'alice');
        CREATE TABLE plans (id TEXT PRIMARY KEY, user_id TEXT, name TEXT);
        INSERT INTO plans VALUES ('p1', 'u1', 'Tokyo trip');
    """)
    conn.commit()
    conn.close()
    seed_airports.seed(data_dir)
    assert [tuple(r) for r in _rows("SELECT * FROM users")] == [("u1", "alice")]
    assert [tuple(r) for r in _rows("SELECT * FROM plans")] == [
        ("p1", "u1", "Tokyo trip")
    ]


def test_seed_returns_false_when_another_worker_seeded_first(
    temp_db, data_dir, monkeypatch
):
    """Between the first version check and the lock, another worker stores
    the version: this worker must not load again."""
    database.create_tables()
    version = seed_airports.place_data_version(data_dir)
    real = seed_airports._stored_version
    calls = []

    def racing(conn):
        calls.append(1)
        if len(calls) == 1:  # the unlocked check: nothing stored yet
            with sqlite3.connect(temp_db) as other:
                other.execute(
                    "INSERT INTO meta (key, value) VALUES (?, ?)",
                    (seed_airports.PLACE_VERSION_KEY, version),
                )
            return None
        return real(conn)

    monkeypatch.setattr(seed_airports, "_stored_version", racing)
    assert seed_airports.seed(data_dir) is False
    assert len(calls) == 2
    assert _rows("SELECT COUNT(*) FROM places")[0][0] == 0


def test_adding_a_column_another_worker_added_is_tolerated(temp_db):
    database.create_tables()
    with get_connection() as conn:
        database._add_column(conn, "region", "TEXT")  # already there: no-op
        with pytest.raises(sqlite3.OperationalError):
            database._add_column(conn, "extra", "INTEGER PRIMARY KEY")


def test_curated_tier_ranks_by_curated_position_not_row_id(
    temp_db, data_dir, monkeypatch
):
    """On a migrated DB a city's new primary airport can have a higher id
    than its other airports; curated order still wins."""
    seed_airports.seed(data_dir)
    with get_connection() as conn:
        conn.executemany(
            "INSERT INTO airports (iata_code, name, city, country, country_code,"
            " type_rank, scheduled) VALUES (?, ?, 'Rankville', 'Testland', 'XT',"
            " 0, 1)",
            [("ZZB", "Second"), ("ZZA", "Primary")],
        )
    monkeypatch.setattr(database, "_curated_rank", lambda: {"ZZA": 0, "ZZB": 1})
    assert database.lookup_city_iata("Rankville") == "ZZA,ZZB"


def test_autocomplete_hides_unscheduled_airports_unless_code_typed(client):
    codes = [r["iata_code"] for r in database.search_airports("kiev")]
    assert "KBP" not in codes and "IEV" not in codes
    assert [r["iata_code"] for r in database.search_airports("KBP")][:1] == ["KBP"]


def test_known_obsolete_code_needs_no_web_search(client, monkeypatch):
    def _fail(*_a, **_kw):
        raise AssertionError("no web search for a known code")

    monkeypatch.setattr(database, "_web_search_iata", _fail)
    info = database.lookup_iata("PNH")
    assert (info["city"], info["country"]) == ("Phnom Penh", "Cambodia")
    assert database.lookup_iata("KBP")["city"] == "Kiev"  # unscheduled row


@pytest.mark.parametrize(
    ("name", "short"),
    [
        ("kakadu national park", {"kakadu"}),
        ("serengeti national park", {"serengeti"}),
        ("mount everest", {"everest"}),
        ("mt kenya", {"kenya"}),
        ("lake tahoe", {"tahoe"}),
        ("ko phi phi", {"phi phi"}),
        ("koh tao", {"tao"}),
        ("isle of skye", {"skye"}),
        ("pulau tioman", {"tioman"}),
        ("bohol island", {"bohol"}),
        ("death valley", set()),  # a generic word that is the name's own
        ("monte rosa", set()),
        ("national park", set()),
        ("mount", set()),
    ],
)
def test_feature_short_names(name, short):
    from app.core.places import feature_short_names

    assert feature_short_names(name) == short
