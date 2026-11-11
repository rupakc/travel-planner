import csv
from datetime import date
from pathlib import Path

from app.schemas.request import TravelSearchRequest
from app.services import trip_geo

SD = {
    "destination": "Lisbon",
    "destinations": ["Lisbon", "Porto"],
    "destination_nights": [3, 2],
}
START, END = date(2026, 12, 1), date(2026, 12, 6)


def test_trip_cities():
    assert trip_geo.trip_cities(SD) == ["Lisbon", "Porto"]
    assert trip_geo.trip_cities({"destination": "Tokyo"}) == ["Tokyo"]
    assert trip_geo.trip_cities({"destinations": ["Rome"]}) == []
    assert trip_geo.trip_cities({}) == []


def test_city_for_day_multi_city():
    for day in (1, 2, 3):
        assert trip_geo.city_for_day(SD, START, END, day) == "Lisbon"
    for day in (4, 5):
        assert trip_geo.city_for_day(SD, START, END, day) == "Porto"
    assert trip_geo.city_for_day(SD, START, END, 9) == "Porto"


def test_city_for_day_single_and_none():
    assert trip_geo.city_for_day({"destination": "Tokyo"}, START, END, 3) == "Tokyo"
    assert trip_geo.city_for_day({}, START, END, 1) is None


def test_city_stays_unchanged():
    req = TravelSearchRequest(
        origin="NYC",
        nationality="American",
        destination="Lisbon",
        destinations=["Lisbon", "Porto"],
        destination_nights=[3, 2],
        departure_date=START,
        return_date=END,
    )
    assert [s["nights"] for s in req.city_stays] == [3, 2]
    assert req.city_stays[1]["start_date"] == date(2026, 12, 4)


def test_country_and_continent():
    assert trip_geo.country_of("Lisbon") == "PT"
    assert trip_geo.country_of("") is None
    assert trip_geo.continent_of("PT") == "EU"
    assert trip_geo.continent_of("pt") == "EU"
    assert trip_geo.continent_of("QQ") is None


def test_trip_countries_ordered_unique():
    sd = {"destinations": ["Lisbon", "Porto", "Tokyo"]}
    assert trip_geo.trip_countries(sd) == ["PT", "JP"]


def test_every_country_has_a_continent():
    path = Path(__file__).parents[1] / "app" / "db" / "data" / "countries.csv"
    with path.open(encoding="utf-8") as f:
        codes = [r["code"] for r in csv.DictReader(f)]
    # ZZ is OurAirports' "unknown or unassigned" placeholder, not a country.
    missing = [c for c in codes if c != "ZZ" and trip_geo.continent_of(c) is None]
    assert missing == []
