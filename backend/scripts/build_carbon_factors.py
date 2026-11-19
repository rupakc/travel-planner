"""Build ``backend/app/data/carbon_factors.json`` from the published files.

Offline tool, run by hand once a year (DESNZ publishes in June); never at app
runtime. Deterministic output (two runs give identical bytes). The input files
are untrusted data: they are only parsed as XLSX cells / CSV text.

    python3 -I backend/scripts/build_carbon_factors.py \\
        --desnz ghg-conversion-factors-2026-flat-format-revised.xlsx \\
        --owid ghg-per-kg-poore.csv \\
        --out backend/app/data/carbon_factors.json

Sources (docs/Carbon-Footprint.md):

- UK DESNZ "Greenhouse gas reporting: conversion factors 2026", flat file,
  sheet "Factors by Category" (OGL v3.0).
  https://assets.publishing.service.gov.uk/media/6a6c9748862aaf18d9c62ac9/ghg-conversion-factors-2026-flat-format-revised.xlsx
- Our World in Data, "Greenhouse gas emissions per kilogram of food product"
  (Poore & Nemecek 2018), grapher CSV (CC BY 4.0).
  https://ourworldindata.org/grapher/ghg-per-kg-poore.csv?v=1&csvType=full&useColumnShortNames=true

Everything that is ours (diet baskets, default distances, the ground mix,
activity estimates) is written under the ``voyager`` source so it is never
mistaken for a published factor. Needs ``openpyxl`` (dev only).
"""

from __future__ import annotations

import argparse
import csv
import json
import statistics
import sys
from pathlib import Path

DESNZ_URL = (
    "https://assets.publishing.service.gov.uk/media/6a6c9748862aaf18d9c62ac9/"
    "ghg-conversion-factors-2026-flat-format-revised.xlsx"
)
OWID_URL = (
    "https://ourworldindata.org/grapher/ghg-per-kg-poore.csv"
    "?v=1&csvType=full&useColumnShortNames=true"
)
YEAR = 2026
PKM = "kg CO2e per passenger.km"
VKM = "kg CO2e per vehicle.km"

# (our key) -> (Level 2, Level 3, Level 4, Column Text, UOM) in the flat file
DESNZ_ROWS: dict[str, tuple] = {
    # Flights, with radiative forcing ("With RF")
    "flight.domestic.average": (
        "Flights",
        "Domestic, to/from UK",
        "Average passenger",
        "With RF",
        "passenger.km",
    ),
    "flight.short_haul.average": (
        "Flights",
        "Short-haul, to/from UK",
        "Average passenger",
        "With RF",
        "passenger.km",
    ),
    "flight.short_haul.economy": (
        "Flights",
        "Short-haul, to/from UK",
        "Economy class",
        "With RF",
        "passenger.km",
    ),
    "flight.short_haul.business": (
        "Flights",
        "Short-haul, to/from UK",
        "Business class",
        "With RF",
        "passenger.km",
    ),
    "flight.long_haul.average": (
        "Flights",
        "Long-haul, to/from UK",
        "Average passenger",
        "With RF",
        "passenger.km",
    ),
    "flight.long_haul.economy": (
        "Flights",
        "Long-haul, to/from UK",
        "Economy class",
        "With RF",
        "passenger.km",
    ),
    "flight.long_haul.premium_economy": (
        "Flights",
        "Long-haul, to/from UK",
        "Premium economy class",
        "With RF",
        "passenger.km",
    ),
    "flight.long_haul.business": (
        "Flights",
        "Long-haul, to/from UK",
        "Business class",
        "With RF",
        "passenger.km",
    ),
    "flight.long_haul.first": (
        "Flights",
        "Long-haul, to/from UK",
        "First class",
        "With RF",
        "passenger.km",
    ),
    # Ground and sea
    "ground.rail_national": ("Rail", "National rail", None, None, "passenger.km"),
    "ground.rail_international": (
        "Rail",
        "International rail",
        None,
        None,
        "passenger.km",
    ),
    "ground.light_rail_tram": (
        "Rail",
        "Light rail and tram",
        None,
        None,
        "passenger.km",
    ),
    "ground.metro": ("Rail", "London Underground", None, None, "passenger.km"),
    "ground.bus_local": ("Bus", "Average local bus", None, None, "passenger.km"),
    "ground.coach": ("Bus", "Coach", None, None, "passenger.km"),
    "ground.taxi_vehicle": ("Taxis", "Regular taxi", None, None, "km"),
    "ground.car_average": ("Cars (by size)", "Average car", None, "Unknown", "km"),
    "ground.ferry_foot": ("Ferry", "Foot passenger", None, None, "passenger.km"),
}

# DESNZ hotel-stay row labels -> ISO 3166-1 alpha-2
HOTEL_COUNTRIES = {
    "UK": "GB",
    "Argentina": "AR",
    "Australia": "AU",
    "Austria": "AT",
    "Belgium": "BE",
    "Brazil": "BR",
    "Canada": "CA",
    "Chile": "CL",
    "China": "CN",
    "Colombia": "CO",
    "Costa Rica": "CR",
    "Czech Republic": "CZ",
    "Egypt": "EG",
    "Fiji": "FJ",
    "Finland": "FI",
    "France": "FR",
    "Germany": "DE",
    "Greece": "GR",
    "Hong Kong, China": "HK",
    "India": "IN",
    "Indonesia": "ID",
    "Ireland": "IE",
    "Israel": "IL",
    "Italy": "IT",
    "Japan": "JP",
    "Jordan": "JO",
    "Kazakhstan": "KZ",
    "Korea": "KR",
    "Macau, China": "MO",
    "Malaysia": "MY",
    "Maldives": "MV",
    "Mexico": "MX",
    "Netherlands": "NL",
    "New Zealand": "NZ",
    "Oman": "OM",
    "Panama": "PA",
    "Peru": "PE",
    "Philippines": "PH",
    "Poland": "PL",
    "Portugal": "PT",
    "Qatar": "QA",
    "Romania": "RO",
    "Russian Federation": "RU",
    "Saudi Arabia": "SA",
    "Singapore": "SG",
    "South Africa": "ZA",
    "Spain": "ES",
    "Switzerland": "CH",
    "Taiwan, China": "TW",
    "Thailand": "TH",
    "Turkey": "TR",
    "United Arab Emirates": "AE",
    "United States": "US",
    "Vietnam": "VN",
}

# OWID entity -> our product key
FOOD_PRODUCTS = {
    "Beef (beef herd)": "beef_herd",
    "Beef (dairy herd)": "beef_dairy",
    "Lamb & Mutton": "lamb",
    "Pig Meat": "pig",
    "Poultry Meat": "poultry",
    "Fish (farmed)": "fish_farmed",
    "Prawns (farmed)": "prawns_farmed",
    "Cheese": "cheese",
    "Milk": "milk",
    "Eggs": "eggs",
    "Tofu": "tofu",
    "Soy milk": "soy_milk",
    "Other Pulses": "pulses",
    "Nuts": "nuts",
    "Groundnuts": "groundnuts",
    "Rice": "rice",
    "Wheat & Rye": "wheat_rye",
    "Potatoes": "potatoes",
    "Other Vegetables": "vegetables",
    "Tomatoes": "tomatoes",
    "Other Fruit": "fruit",
    "Bananas": "bananas",
    "Cane Sugar": "cane_sugar",
    "Coffee": "coffee",
}

# Our per-person daily baskets, grams of each product (assumption, not a
# published figure). Calibrated so the totals sit near the diet-type
# averages in Scarborough et al. 2014 (vegan < vegetarian < mixed < meat-heavy).
DIETS = {
    "mixed": {
        "beef_herd": 25,
        "pig": 40,
        "poultry": 60,
        "fish_farmed": 25,
        "cheese": 30,
        "milk": 250,
        "eggs": 30,
        "rice": 75,
        "wheat_rye": 150,
        "potatoes": 100,
        "vegetables": 300,
        "tomatoes": 50,
        "fruit": 150,
        "bananas": 50,
        "cane_sugar": 40,
        "coffee": 15,
        "pulses": 20,
    },
    "meat_heavy": {
        "beef_herd": 45,
        "lamb": 15,
        "pig": 60,
        "poultry": 80,
        "cheese": 40,
        "milk": 250,
        "eggs": 40,
        "rice": 60,
        "wheat_rye": 150,
        "potatoes": 120,
        "vegetables": 250,
        "tomatoes": 50,
        "fruit": 150,
        "cane_sugar": 50,
        "coffee": 15,
    },
    "pescatarian": {
        "fish_farmed": 80,
        "prawns_farmed": 15,
        "cheese": 40,
        "milk": 250,
        "eggs": 40,
        "pulses": 40,
        "rice": 90,
        "wheat_rye": 170,
        "potatoes": 120,
        "vegetables": 350,
        "tomatoes": 60,
        "fruit": 200,
        "bananas": 50,
        "nuts": 20,
        "cane_sugar": 40,
        "coffee": 15,
    },
    "vegetarian": {
        "cheese": 45,
        "milk": 300,
        "eggs": 50,
        "pulses": 60,
        "tofu": 40,
        "rice": 90,
        "wheat_rye": 180,
        "potatoes": 120,
        "vegetables": 350,
        "tomatoes": 60,
        "fruit": 200,
        "bananas": 60,
        "nuts": 30,
        "cane_sugar": 40,
        "coffee": 15,
    },
    "vegan": {
        "tofu": 100,
        "pulses": 100,
        "soy_milk": 250,
        "nuts": 40,
        "groundnuts": 20,
        "rice": 100,
        "wheat_rye": 200,
        "potatoes": 150,
        "vegetables": 400,
        "tomatoes": 70,
        "fruit": 250,
        "bananas": 80,
        "cane_sugar": 30,
        "coffee": 15,
    },
}

VOYAGER = {
    "flight_bands_km": {"domestic_max": 500, "short_haul_max": 3700},
    "flight_cabin_fallback": {
        "short_haul": {"premium_economy": "economy", "first": "business"},
        "domestic": {
            "economy": "average",
            "premium_economy": "average",
            "business": "average",
            "first": "average",
        },
    },
    "ground_default_km_per_day": 10,
    "ground_default_mix": {"metro": 0.4, "bus_local": 0.4, "taxi_vehicle": 0.2},
    "taxi_seats": 4,
    "car_seats": 5,
    "rail_route_factor": 1.2,
    "rail_hint_max_km": 700,
    "rail_hint_no_rail_countries": ["CY", "FJ", "ID", "IS", "MT", "MV", "NZ", "PH"],
    "rooms_per_traveller": 0.5,
    "default_nights": 7,
    "annual_budget_kg_per_person": 2000,
    # Transport-heavy activities: mode, assumed km (per traveller for
    # public modes, per vehicle for car). Everything else is omitted.
    "activities": [
        {
            "key": "boat",
            "match": ["boat", "cruise", "ferry", "sailing", "catamaran", "yacht"],
            "mode": "ferry_foot",
            "km": 20,
        },
        {
            "key": "coach_tour",
            "match": ["day trip", "excursion", "tour bus", "coach tour", "bus tour"],
            "mode": "coach",
            "km": 100,
        },
        {
            "key": "car_tour",
            "match": ["jeep", "safari", "atv", "quad", "4x4", "road trip", "drive"],
            "mode": "car_average",
            "km": 60,
        },
    ],
    "activities_unmodelled": [
        "helicopter",
        "scenic flight",
        "hot air balloon",
        "seaplane",
        "skydiv",
    ],
}


def _desnz(path: Path) -> tuple[dict, dict, str]:
    import openpyxl  # dev-only dependency

    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    ws = wb["Factors by Category"]
    header = None
    rows = []
    for r in ws.iter_rows(values_only=True):
        if header is None:
            if r and r[0] == "ID" and r[7] == "UOM":
                header = r
            continue
        rows.append(r)
    if header is None:
        sys.exit("DESNZ: header row not found")
    value_col = next(
        i
        for i, h in enumerate(header)
        if str(h or "").startswith("GHG Conversion Factor")
    )
    if str(YEAR) not in str(header[value_col]):
        sys.exit(f"DESNZ: expected the {YEAR} column, got {header[value_col]!r}")

    def find(spec: tuple) -> tuple[str, float]:
        l2, l3, l4, col, uom = spec
        for r in rows:
            if (
                r[8] == "kg CO2e"
                and r[3] == l2
                and r[4] == l3
                and r[5] == l4
                and r[6] == col
                and r[7] == uom
                and isinstance(r[value_col], (int, float))
            ):
                return r[0], float(r[value_col])
        sys.exit(f"DESNZ: row not found {spec}")

    factors = {}
    for key, spec in DESNZ_ROWS.items():
        fid, value = find(spec)
        unit = PKM if spec[4] == "passenger.km" else VKM
        label = " / ".join(str(x) for x in spec[:4] if x)
        factors[key] = {
            "value": round(value, 5),
            "unit": unit,
            "source": "desnz_2026",
            "year": YEAR,
            "factor_id": fid,
            "label": label,
            **({"basis": "co2e_with_rf"} if key.startswith("flight.") else {}),
        }
    hotels = {}
    for r in rows:
        if (
            r[2] == "Hotel stay"
            and r[8] == "kg CO2e"
            and isinstance(r[value_col], (int, float))
        ):
            iso = HOTEL_COUNTRIES.get(r[4])
            if iso:  # "UK (London)" and unmapped labels are left out
                hotels[iso] = {
                    "value": round(float(r[value_col]), 2),
                    "unit": "kg CO2e per room.night",
                    "source": "desnz_2026",
                    "year": YEAR,
                    "factor_id": r[0],
                    "label": f"Hotel stay / {r[4]}",
                }
    return factors, dict(sorted(hotels.items())), str(header[value_col])


def _owid(path: Path) -> dict:
    out = {}
    with open(path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            key = FOOD_PRODUCTS.get(row["entity"])
            value = row.get("ghg_emissions_per_kilogram__poore__and__nemecek__2018")
            if key and value:
                out[key] = {
                    "value": float(value),
                    "unit": "kg CO2e per kg",
                    "source": "owid_food",
                    "year": int(row["year"]),
                    "label": row["entity"],
                }
    missing = sorted(set(FOOD_PRODUCTS.values()) - set(out))
    if missing:
        sys.exit(f"OWID: missing products {missing}")
    return dict(sorted(out.items()))


def build(desnz: Path, owid: Path) -> dict:
    factors, hotels, column = _desnz(desnz)
    food = _owid(owid)
    median = round(statistics.median(h["value"] for h in hotels.values()), 1)
    diets = {}
    for name, basket in DIETS.items():
        kg = sum(food[p]["value"] * g / 1000 for p, g in basket.items())
        diets[name] = {
            "basket_g_per_day": basket,
            "kg_per_day": round(kg, 3),
            "unit": "kg CO2e per person.day",
            "source": "voyager",
            "year": YEAR,
        }
    flights = {
        k.split(".", 1)[1]: v for k, v in factors.items() if k.startswith("flight.")
    }
    ground = {
        k.split(".", 1)[1]: v for k, v in factors.items() if k.startswith("ground.")
    }
    return {
        "version": f"{YEAR}.1",
        "sources": {
            "desnz_2026": {
                "name": "UK Government GHG Conversion Factors for Company Reporting 2026 (flat file, revised)",
                "publisher": "Department for Energy Security and Net Zero (DESNZ)",
                "year": YEAR,
                "url": DESNZ_URL,
                "column": column,
                "licence": "Open Government Licence v3.0",
                "licence_url": "https://www.nationalarchives.gov.uk/doc/open-government-licence/version/3/",
                "attribution": "Contains public sector information licensed under the Open Government Licence v3.0",
            },
            "owid_food": {
                "name": "Greenhouse gas emissions per kilogram of food product",
                "publisher": "Our World in Data, based on Poore & Nemecek (2018)",
                "year": 2018,
                "url": OWID_URL,
                "licence": "CC BY 4.0",
                "licence_url": "https://creativecommons.org/licenses/by/4.0/",
                "attribution": "Our World in Data, based on Poore & Nemecek (2018), CC BY 4.0",
            },
            "google_tim": {
                "name": "Travel Impact Model",
                "publisher": "Google",
                "url": "https://travelimpactmodel.org",
                "licence": "CC BY-SA 4.0",
                "attribution": "Emissions estimates: Google Travel Impact Model, CC BY-SA 4.0",
            },
            "voyager": {
                "name": "Voyager assumptions",
                "publisher": "Voyager",
                "url": "https://github.com/rupakc/travel-planner/blob/main/docs/Carbon-Footprint.md",
                "licence": "MIT",
            },
        },
        "flight": flights,
        "ground": ground,
        "hotel": {
            "by_country": hotels,
            "default": {
                "value": median,
                "unit": "kg CO2e per room.night",
                "source": "voyager",
                "year": YEAR,
                "label": "Median of the DESNZ 2026 hotel-stay countries",
            },
        },
        "food": {"products": food, "diets": diets, "default_diet": "mixed"},
        "assumptions": VOYAGER,
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--desnz", type=Path, required=True)
    ap.add_argument("--owid", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    a = ap.parse_args()
    data = build(a.desnz, a.owid)
    a.out.write_text(
        json.dumps(data, indent=1, ensure_ascii=False) + "\n", encoding="utf-8"
    )


if __name__ == "__main__":
    main()
