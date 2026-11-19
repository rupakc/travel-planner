"""Trip carbon footprint: a pure, deterministic CO2e calculator (no LLM, no
network). ``POST /api/carbon/trip`` (api/routes/carbon.py) calls ``compute``.

Inputs are a plan's selections or a search-result summary plus the search
fields (dates, travellers, cities). Factors come from the committed table
``app/data/carbon_factors.json`` (built by ``scripts/build_carbon_factors.py``
from UK DESNZ 2026 and Our World in Data); airport coordinates from the
airports table. docs/Carbon-Footprint.md has the method.

Every line says how it was worked out:

- ``measured_tim``: Google Travel Impact Model figure already on the flight
  (``emissions``, added by services/travel_impact.py), times travellers;
- ``factor``: a published factor times a known quantity (great-circle km,
  room-nights, km between itinerary stops);
- ``estimate``: a published factor times a quantity we assumed (km per day
  without coordinates, the length of a boat trip), always labelled.

Lines carry an English ``label`` plus a ``kind`` and ``params`` so clients can
translate them; ``assumptions`` work the same way (``code`` + ``params``).
"""

from __future__ import annotations

import json
import math
import re
from datetime import date
from functools import lru_cache
from pathlib import Path

from ..schemas.request import allocate_city_days
from ..utils.geo import haversine_km

FACTORS_FILE = Path(__file__).resolve().parent.parent / "data" / "carbon_factors.json"

CATEGORIES = ("flights", "stays", "ground", "food", "activities")
DIETS = ("mixed", "meat_heavy", "pescatarian", "vegetarian", "vegan")
CABINS = ("economy", "premium_economy", "business", "first")
_TIM_CLASS = {
    "economy": "economy",
    "premium_economy": "premiumEconomy",
    "business": "business",
    "first": "first",
}
_IATA = re.compile(r"^[A-Z]{3}$")
# Itinerary stops further apart than this are not a local hop (an airport
# run, a day trip to another city): they are left to the inter-city lines.
MAX_LOCAL_HOP_KM = 150.0

# getting_around option type -> ground factor key (None: no emissions)
_MODE_OF_TYPE = {
    "metro": "metro",
    "tram": "light_rail_tram",
    "bus": "bus_local",
    "taxi": "taxi_vehicle",
    "rideshare": "taxi_vehicle",
    "train": "rail_national",
    "long_distance_bus": "coach",
    "tourist_transport": "coach",
    "car_rental": "car_average",
    "ferry": "ferry_foot",
    "water_transport": "ferry_foot",
    "walking": None,
    "bike": None,
    "scooter": None,
}
_VEHICLE_MODES = {"taxi_vehicle": "taxi_seats", "car_average": "car_seats"}


@lru_cache(maxsize=1)
def factors() -> dict:
    return json.loads(FACTORS_FILE.read_text(encoding="utf-8"))


# ── Small helpers ────────────────────────────────────────────────────────────


def _num(v) -> float | None:
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)) and math.isfinite(v):
        return float(v)
    return None


def _int(v, lo: int, hi: int) -> int | None:
    n = _num(v)
    if n is None:
        try:
            n = float(str(v).strip())
        except (TypeError, ValueError):
            return None
    if not math.isfinite(n):
        return None
    return max(lo, min(hi, int(n)))


def _date(v) -> date | None:
    try:
        return date.fromisoformat(str(v)[:10])
    except (TypeError, ValueError):
        return None


def _code(v) -> str | None:
    c = str(v or "").strip().upper().split(",")[0]
    return c if _IATA.match(c) else None


def _point(lat, lng) -> tuple[float, float] | None:
    la, lo = _num(lat), _num(lng)
    if la is None or lo is None or not (-90 <= la <= 90) or not (-180 <= lo <= 180):
        return None
    if la == 0 and lo == 0:
        return None
    return la, lo


@lru_cache(maxsize=4096)
def airport(code: str) -> tuple[float, float, str | None] | None:
    """(lat, lng, country_code) of an IATA airport from the airports table."""
    from ..db.database import get_connection

    try:
        with get_connection() as conn:
            row = conn.execute(
                "SELECT latitude, longitude, country_code FROM airports "
                "WHERE iata_code = ?",
                (code,),
            ).fetchone()
    except Exception:
        return None
    if not row:
        return None
    p = _point(row[0], row[1])
    return (p[0], p[1], row[2] or None) if p else None


@lru_cache(maxsize=2048)
def place(name: str) -> tuple[float, float, str | None] | None:
    """(lat, lng, country_code) of a typed city, from the local place data."""
    from ..db.places_db import resolve_place

    if not isinstance(name, str) or not name.strip():
        return None
    try:
        found = resolve_place(name)
    except Exception:
        return None
    if not found:
        return None
    p = _point(found.lat, found.lng)
    if not p:
        return None
    return p[0], p[1], found.country_code or None


def _km(a: tuple, b: tuple) -> float:
    return haversine_km(a[0], a[1], b[0], b[1])


# ── Calculator ───────────────────────────────────────────────────────────────


class _Run:
    def __init__(self, req: dict):
        self.f = factors()
        self.a = self.f["assumptions"]
        self.req = req
        self.search = req.get("search") if isinstance(req.get("search"), dict) else {}
        self.lines: list[dict] = []
        self.assumptions: list[dict] = []
        self.used: set[str] = set()
        self.hints: list[dict] = []

    # bookkeeping
    def assume(self, code: str, text: str, **params) -> None:
        if not any(
            x["code"] == code and x["params"] == params for x in self.assumptions
        ):
            self.assumptions.append({"code": code, "text": text, "params": params})

    def line(self, category, kind, label, kg, method, source, **params) -> dict:
        self.used.add(source)
        ln = {
            "category": category,
            "kind": kind,
            "label": label,
            "kg": kg,
            "method": method,
            "source": source,
            "params": params,
        }
        self.lines.append(ln)
        return ln

    # trip shape
    def travellers(self) -> int:
        s = self.search
        n = _int(s.get("num_travelers"), 1, 20)
        if n is None:
            parts = [
                _int(s.get(k), 0, 20) or 0 for k in ("adults", "children", "seniors")
            ]
            n = max(1, min(20, sum(parts))) if sum(parts) else None
        if n is None:
            self.assume("travellers_default", "One traveller (none given).")
            n = 1
        return n

    def nights(self) -> int:
        dep, ret = (
            _date(self.search.get("departure_date")),
            _date(self.search.get("return_date")),
        )
        if dep and ret and 0 < (ret - dep).days <= 365:
            return (ret - dep).days
        n = int(self.a["default_nights"])
        self.assume("nights_default", f"{n} nights (no return date).", nights=n)
        return n

    def cities(self) -> list[str]:
        s = self.search
        dests = s.get("destinations")
        if isinstance(dests, list):
            c = [d.strip() for d in dests if isinstance(d, str) and d.strip()]
            if len(c) > 1:
                return c[:10]
        d = s.get("destination")
        return [d.strip()] if isinstance(d, str) and d.strip() else []

    def city_nights(self, nights: int) -> list[tuple[str | None, int]]:
        cities = self.cities()
        if len(cities) <= 1:
            return [(cities[0] if cities else None, nights)]
        dn = self.search.get("destination_nights")
        dn = (
            [x if isinstance(x, int) else None for x in dn]
            if isinstance(dn, list)
            else None
        )
        alloc = allocate_city_days(len(cities), max(nights, len(cities)), dn)
        return list(zip(cities, alloc))

    # ── flights
    def flight_factor(self, km: float, cabin: str) -> tuple[str, dict]:
        bands = self.a["flight_bands_km"]
        if km <= bands["domestic_max"]:
            band = "domestic"
        elif km <= bands["short_haul_max"]:
            band = "short_haul"
        else:
            band = "long_haul"
        fallback = self.a["flight_cabin_fallback"].get(band, {})
        cls = fallback.get(cabin, cabin)
        key = f"{band}.{cls}"
        if key not in self.f["flight"]:
            key = f"{band}.average"
        return key, self.f["flight"][key]

    def leg_hops(self, leg: dict) -> list[str] | None:
        o, d = _code(leg.get("origin")), _code(leg.get("destination"))
        if not o or not d:
            return None
        stops = []
        segs = leg.get("segments")
        if isinstance(segs, list) and len(segs) > 1:
            stops = [
                _code(s.get("destination")) for s in segs[:-1] if isinstance(s, dict)
            ]
        elif isinstance(leg.get("layovers"), list):
            stops = [
                _code(lv.get("airport"))
                for lv in leg["layovers"]
                if isinstance(lv, dict)
            ]
        if any(s is None for s in stops):
            stops = []  # unknown connection airport: fly direct instead
        return [o, *stops, d]

    def tim_kg(self, em, cabin: str) -> float | None:
        if not isinstance(em, dict):
            return None
        by = em.get("by_class") if isinstance(em.get("by_class"), dict) else {}
        kg = _num(by.get(_TIM_CLASS[cabin]))
        if kg is None and (em.get("cabin") in (None, _TIM_CLASS[cabin])):
            kg = _num(em.get("kg_co2e_per_pax"))
        return kg if kg is not None and kg >= 0 else None

    def flight_legs(self, result: dict) -> list[dict]:
        if isinstance(result.get("outbound"), dict):
            legs = [result["outbound"]]
            if isinstance(result.get("return"), dict) and result["return"]:
                legs.append(result["return"])
            return legs
        return [result]

    def flights(self, results: list[dict], cabin: str, n: int) -> None:
        for r in results:
            if not isinstance(r, dict):
                continue
            legs = [lg for lg in self.flight_legs(r) if isinstance(lg, dict) and lg]
            leg_tim = [self.tim_kg(lg.get("emissions"), cabin) for lg in legs]
            whole = self.tim_kg(r.get("emissions"), cabin)
            if whole is not None and not all(k is not None for k in leg_tim):
                # An older backend: one figure for the whole result
                route = " / ".join(
                    f"{_code(lg.get('origin')) or '?'}–{_code(lg.get('destination')) or '?'}"
                    for lg in legs
                )
                self.line(
                    "flights",
                    "flight_tim",
                    f"Flights {route} (Google TIM)",
                    whole * n,
                    "measured_tim",
                    "google_tim",
                    route=route,
                    per_person_kg=round(whole, 1),
                    travellers=n,
                )
                for lg in legs:
                    self.rail_hint(lg, None, n)
                continue
            for lg, tim in zip(legs, leg_tim):
                self.flight_leg(lg, tim, cabin, n)

    def flight_leg(self, leg: dict, tim: float | None, cabin: str, n: int) -> None:
        o, d = _code(leg.get("origin")), _code(leg.get("destination"))
        route = f"{o or '?'}–{d or '?'}"
        if tim is not None:
            ln = self.line(
                "flights",
                "flight_tim",
                f"Flight {route} (Google TIM)",
                tim * n,
                "measured_tim",
                "google_tim",
                route=route,
                per_person_kg=round(tim, 1),
                travellers=n,
            )
            self.rail_hint(leg, ln["kg"], n)
            return
        hops = self.leg_hops(leg)
        pts = [airport(c) for c in hops] if hops else []
        if not hops or any(p is None for p in pts):
            # Retry non-stop if only a connection airport is unknown
            if hops and airport(hops[0]) and airport(hops[-1]):
                hops = [hops[0], hops[-1]]
                pts = [airport(hops[0]), airport(hops[1])]
            else:
                self.assume(
                    "flight_unknown_airport",
                    f"Flight {route} left out: airport not found.",
                    route=route,
                )
                return
        km_total = 0.0
        kg_pp = 0.0
        keys = []
        for a, b in zip(pts, pts[1:]):
            km = _km(a, b)
            key, fac = self.flight_factor(km, cabin)
            km_total += km
            kg_pp += km * fac["value"]
            keys.append(key)
        self.assume(
            "flight_desnz",
            "Flights without a TIM figure: great-circle distance × DESNZ 2026 "
            "factor for the distance band and cabin, with radiative forcing.",
        )
        ln = self.line(
            "flights",
            "flight_factor",
            f"Flight {route} ({round(km_total)} km)",
            kg_pp * n,
            "factor",
            "desnz_2026",
            route=route,
            km=round(km_total),
            cabin=cabin,
            factor_keys=keys,
            per_person_kg=round(kg_pp, 1),
            travellers=n,
        )
        self.rail_hint(leg, ln["kg"], n)

    def rail_hint(self, leg: dict, flight_kg: float | None, n: int) -> None:
        o, d = _code(leg.get("origin")), _code(leg.get("destination"))
        a, b = (airport(o), airport(d)) if o and d else (None, None)
        if not a or not b:
            return
        rail_km = _km(a, b) * self.a["rail_route_factor"]
        if rail_km > self.a["rail_hint_max_km"]:
            return
        ca, cb = a[2], b[2]
        no_rail = set(self.a["rail_hint_no_rail_countries"])
        if not ca or not cb or ca in no_rail or cb in no_rail:
            return
        if ca != cb:
            from .trip_geo import continent_of

            if continent_of(ca) != "EU" or continent_of(cb) != "EU" or "IE" in (ca, cb):
                return
        key = "rail_national" if ca == cb else "rail_international"
        rail_kg = rail_km * self.f["ground"][key]["value"] * n
        if flight_kg is None:
            km = _km(a, b)
            _, fac = self.flight_factor(km, "economy")
            flight_kg = km * fac["value"] * n
        self.used.add("desnz_2026")
        for h in self.hints:  # the way back joins the way out
            if {h["from"], h["to"]} == {o, d}:
                h["flight_kg"] = round(h["flight_kg"] + flight_kg, 1)
                h["rail_kg"] = round(h["rail_kg"] + rail_kg, 1)
                h["saving_kg"] = round(max(0.0, h["flight_kg"] - h["rail_kg"]), 1)
                h["legs"] += 1
                return
        self.hints.append(
            {
                "route": f"{o}–{d}",
                "from": o,
                "to": d,
                "rail_km": round(rail_km),
                "legs": 1,
                "flight_kg": round(flight_kg, 1),
                "rail_kg": round(rail_kg, 1),
                "saving_kg": round(max(0.0, flight_kg - rail_kg), 1),
                "factor": key,
            }
        )

    # ── stays
    def stays(self, nights: int, n: int, hotel: dict | None) -> None:
        rooms = _int(self.req.get("rooms"), 1, 20)
        if rooms is None:
            rooms = max(1, math.ceil(n * self.a["rooms_per_traveller"]))
            self.assume(
                "rooms_default",
                f"{rooms} room(s): one per two travellers.",
                rooms=rooms,
            )
        default = self.f["hotel"]["default"]
        by_country = self.f["hotel"]["by_country"]
        hotel_cc = None
        if isinstance(hotel, dict):
            cc = str(hotel.get("country_code") or "").strip().upper()
            hotel_cc = cc if len(cc) == 2 else None
        plan = self.city_nights(nights)
        for city, city_n in plan:
            if city_n <= 0:
                continue
            cc = hotel_cc if (hotel_cc and len(plan) == 1) else None
            if cc is None and city:
                p = place(city)
                cc = p[2] if p else None
            fac = by_country.get(cc or "")
            where = city or cc or "destination"
            if fac:
                self.line(
                    "stays",
                    "hotel_nights",
                    f"Hotel in {where}: {city_n} night(s) × {rooms} room(s)",
                    city_n * rooms * fac["value"],
                    "factor",
                    "desnz_2026",
                    city=where,
                    country=cc,
                    nights=city_n,
                    rooms=rooms,
                    per_room_night_kg=fac["value"],
                )
            else:
                self.assume(
                    "hotel_default",
                    f"No DESNZ hotel factor for {where}: the median of the DESNZ "
                    f"countries ({default['value']} kg per room-night).",
                    city=where,
                    kg=default["value"],
                )
                self.line(
                    "stays",
                    "hotel_nights",
                    f"Hotel in {where}: {city_n} night(s) × {rooms} room(s)",
                    city_n * rooms * default["value"],
                    "estimate",
                    "voyager",
                    city=where,
                    country=cc,
                    nights=city_n,
                    rooms=rooms,
                    per_room_night_kg=default["value"],
                )
                self.used.add("desnz_2026")

    # ── ground
    def mode_mix(self, options: list) -> dict[str, float]:
        modes: list[str] = []
        for o in options or []:
            if not isinstance(o, dict) or o.get("scope") == "inter_city":
                continue
            t = str(o.get("type") or "").lower()
            if t in _MODE_OF_TYPE:
                modes.append(_MODE_OF_TYPE[t] or "active")
        if not modes:
            self.assume(
                "ground_default_mix",
                "Local trips: 40 % metro, 40 % bus, 20 % taxi (no transport picked).",
            )
            return dict(self.a["ground_default_mix"])
        share = 1 / len(modes)
        mix: dict[str, float] = {}
        for m in modes:
            mix[m] = mix.get(m, 0) + share
        return mix

    def mode_kg(self, mode: str, km: float, n: int) -> float:
        if mode == "active":
            return 0.0
        fac = self.f["ground"][mode]["value"]
        if mode in _VEHICLE_MODES:
            vehicles = math.ceil(n / self.a[_VEHICLE_MODES[mode]])
            return km * fac * vehicles
        return km * fac * n

    def mix_kg(self, mix: dict[str, float], km: float, n: int) -> float:
        return sum(self.mode_kg(m, km * s, n) for m, s in mix.items())

    def ground(
        self, itinerary, options: list, nights: int, n: int, covered_legs: set
    ) -> None:
        mix = self.mode_mix(options)
        days = itinerary.get("days") if isinstance(itinerary, dict) else None
        days = (
            [d for d in days if isinstance(d, dict)] if isinstance(days, list) else []
        )
        per_day = float(self.a["ground_default_km_per_day"])
        measured_km = 0.0
        measured_days = 0
        estimate_days = 0
        for day in days[:60]:
            pts = []
            for s in day.get("slots") or []:
                if isinstance(s, dict):
                    p = _point(s.get("lat"), s.get("lng"))
                    if p:
                        pts.append(p)
            hops = [_km(a, b) for a, b in zip(pts, pts[1:])]
            hops = [h for h in hops if h <= MAX_LOCAL_HOP_KM]
            if len(pts) >= 2:
                measured_km += sum(hops)
                measured_days += 1
            else:
                estimate_days += 1
        if not days:
            estimate_days = max(1, nights)
        if measured_days:
            self.assume(
                "ground_straight_line",
                "Local trips: straight-line distance between itinerary stops.",
            )
            self.line(
                "ground",
                "local_measured",
                f"Local transport: {round(measured_km, 1)} km over {measured_days} day(s)",
                self.mix_kg(mix, measured_km, n),
                "factor",
                "desnz_2026",
                km=round(measured_km, 1),
                days=measured_days,
                modes=sorted(mix),
                travellers=n,
            )
        if estimate_days:
            km = estimate_days * per_day
            self.assume(
                "ground_per_day",
                f"Days without itinerary stops: {round(per_day)} km of local transport per day.",
                km_per_day=round(per_day),
            )
            self.line(
                "ground",
                "local_estimate",
                f"Local transport: about {round(per_day)} km/day for {estimate_days} day(s)",
                self.mix_kg(mix, km, n),
                "estimate",
                "desnz_2026",
                km=round(km, 1),
                days=estimate_days,
                modes=sorted(mix),
                travellers=n,
            )
        self.intercity(options, n, covered_legs)

    def intercity(self, options: list, n: int, covered_legs: set) -> None:
        cities = self.cities()
        if len(cities) < 2:
            return
        mode = None
        for o in options or []:
            if isinstance(o, dict) and o.get("scope") == "inter_city":
                m = _MODE_OF_TYPE.get(str(o.get("type") or "").lower(), "")
                if m:
                    mode = m
                    break
        if mode is None:
            mode = "rail_national"
            self.assume(
                "intercity_rail",
                "Moves between cities without a picked flight: by train.",
            )
        for i, (a, b) in enumerate(zip(cities, cities[1:])):
            # leg 0 is origin → first city, so the move a → b is leg i + 1
            if (i + 1) in covered_legs:
                continue
            pa, pb = place(a), place(b)
            route = f"{a} – {b}"
            if not pa or not pb:
                self.assume(
                    "intercity_unknown",
                    f"{route} left out: place not found.",
                    route=route,
                )
                continue
            km = _km(pa, pb) * self.a["rail_route_factor"]
            self.line(
                "ground",
                "intercity",
                f"{route} by {mode.replace('_', ' ')} ({round(km)} km)",
                self.mode_kg(mode, km, n),
                "factor",
                "desnz_2026",
                route=route,
                km=round(km),
                mode=mode,
                travellers=n,
            )

    # ── food
    def food(self, days: int, n: int) -> None:
        diet = self.req.get("diet")
        diet = diet if diet in DIETS else self.f["food"]["default_diet"]
        products = self.f["food"]["products"]
        basket = self.f["food"]["diets"][diet]["basket_g_per_day"]
        per_day = sum(products[p]["value"] * g / 1000 for p, g in basket.items())
        self.assume(
            "food_basket",
            f"Meals: a typical {diet.replace('_', ' ')} day of food "
            f"({round(per_day, 1)} kg per person), counted in full.",
            diet=diet,
            kg_per_day=round(per_day, 1),
        )
        self.used.add("voyager")
        self.line(
            "food",
            "meals",
            f"Meals ({diet.replace('_', ' ')}): {days} day(s) × {n}",
            per_day * days * n,
            "estimate",
            "owid_food",
            diet=diet,
            days=days,
            travellers=n,
            per_person_day_kg=round(per_day, 2),
        )

    # ── activities
    def activities(self, names: list[str], n: int) -> None:
        if not names:
            return
        rules = self.a["activities"]
        unmodelled = self.a["activities_unmodelled"]
        skipped = 0
        for name in names[:100]:
            text = name.lower()
            if any(u in text for u in unmodelled):
                skipped += 1
                continue
            rule = next((r for r in rules if any(m in text for m in r["match"])), None)
            if not rule:
                continue
            kg = self.mode_kg(rule["mode"], rule["km"], n)
            self.line(
                "activities",
                "activity_estimate",
                f"{name[:80]} (about {rule['km']} km by {rule['mode'].replace('_', ' ')})",
                kg,
                "estimate",
                "desnz_2026",
                name=name[:80],
                rule=rule["key"],
                km=rule["km"],
                mode=rule["mode"],
                travellers=n,
            )
        self.assume(
            "activities_partial",
            "Activities: only boat trips, coach tours and drives are estimated; "
            "others are left out (no data).",
        )
        if skipped:
            self.assume(
                "activities_unmodelled",
                f"{skipped} flight-based activit(ies) left out (no factor).",
                count=skipped,
            )


def _activity_names(itinerary, selected: list) -> list[str]:
    names: list[str] = []
    days = itinerary.get("days") if isinstance(itinerary, dict) else None
    if isinstance(days, list):
        for d in days:
            for s in (d.get("slots") or []) if isinstance(d, dict) else []:
                if isinstance(s, dict) and isinstance(s.get("activity"), str):
                    names.append(s["activity"])
    # Picked activities the itinerary doesn't already mention
    slots = [n.lower() for n in names]
    for a in selected or []:
        if isinstance(a, dict):
            nm = a.get("name") or a.get("title")
            if isinstance(nm, str) and not any(nm.lower() in t for t in slots):
                names.append(nm)
    return names


def _cheapest(results) -> dict | None:
    if not isinstance(results, list):
        return None
    rs = [r for r in results if isinstance(r, dict)]
    return rs[0] if rs else None


def compute(req: dict) -> dict:
    """The footprint of one trip. ``req`` is the validated request body as a
    dict: ``search`` plus either ``selections`` (a plan) or ``results`` (a
    search-result summary), optional ``itinerary``, ``diet``, ``cabin``,
    ``rooms``. Pure: the same input always gives the same output."""
    run = _Run(req)
    f = run.f
    n = run.travellers()
    nights = run.nights()
    cabin = req.get("cabin") if req.get("cabin") in CABINS else "economy"
    sel = req.get("selections") if isinstance(req.get("selections"), dict) else None
    res = req.get("results") if isinstance(req.get("results"), dict) else None
    itinerary = req.get("itinerary") if isinstance(req.get("itinerary"), dict) else None

    flights: list[dict] = []
    hotel = None
    options: list = []
    selected_acts: list = []
    include_stays = True
    if sel is not None:
        if isinstance(sel.get("flight"), dict):
            flights.append(sel["flight"])
        flights += [x for x in (sel.get("flights") or []) if isinstance(x, dict)]
        hotel = sel.get("hotel") if isinstance(sel.get("hotel"), dict) else None
        include_stays = hotel is not None
        options = [x for x in (sel.get("getting_around") or []) if isinstance(x, dict)]
        selected_acts = sel.get("activities") or []
        if not include_stays:
            run.assume("stays_none", "No hotel in the plan: stays left out.")
        if not flights:
            run.assume("flights_none", "No flight in the plan: flights left out.")
    else:
        res = res or {}
        fl = res.get("flights") if isinstance(res.get("flights"), dict) else {}
        if isinstance(fl.get("legs"), list) and fl["legs"]:
            for lg in fl["legs"]:
                pick = _cheapest(lg.get("results")) if isinstance(lg, dict) else None
                if pick:
                    flights.append(pick)
        else:
            pick = _cheapest(fl.get("results"))
            if pick:
                flights.append(pick)
        if flights:
            run.assume("flights_cheapest", "Flights: the cheapest listed option.")
        h = res.get("hotels") if isinstance(res.get("hotels"), dict) else {}
        hotel = _cheapest(h.get("results"))
        if itinerary is None and isinstance(res.get("itinerary"), dict):
            itinerary = res["itinerary"]
        # Search results list every way to get around, not the ones used
        options = []
    if flights:
        run.assume("flights_cabin", f"Cabin: {cabin.replace('_', ' ')}.", cabin=cabin)
    run.flights(flights[:20], cabin, n)

    if include_stays:
        run.stays(nights, n, hotel)

    covered = {_int(x.get("leg_index"), 0, 50) for x in flights if "leg_index" in x}
    run.ground(itinerary, options, nights, n, covered)

    days = itinerary.get("days") if isinstance(itinerary, dict) else None
    food_days = nights if nights > 0 else (len(days) if isinstance(days, list) else 1)
    run.food(max(1, food_days), n)

    run.activities(_activity_names(itinerary, selected_acts), n)

    total = sum(ln["kg"] for ln in run.lines)
    per_person = total / n
    cats = []
    for c in CATEGORIES:
        kg = sum(ln["kg"] for ln in run.lines if ln["category"] == c)
        cats.append(
            {
                "key": c,
                "kg": round(kg, 1),
                "share": round(kg / total, 4) if total > 0 else 0.0,
                "included": any(ln["category"] == c for ln in run.lines),
            }
        )
    for ln in run.lines:
        ln["kg"] = round(ln["kg"], 1)
    car = f["ground"]["car_average"]["value"]
    budget = float(f["assumptions"]["annual_budget_kg_per_person"])
    sources = [
        {"id": sid, **f["sources"][sid]}
        for sid in ("google_tim", "desnz_2026", "owid_food", "voyager")
        if sid in run.used
    ]
    return {
        "total_kg": round(total, 1),
        "per_person_kg": round(per_person, 1),
        "travellers": n,
        "nights": nights,
        "diet": next(
            (ln["params"]["diet"] for ln in run.lines if ln["kind"] == "meals"), None
        ),
        "cabin": cabin,
        "categories": cats,
        "lines": run.lines,
        "comparisons": {
            "car_km": round(total / car) if car else None,
            "annual_budget_kg": round(budget),
            "budget_share": round(per_person / budget, 4) if budget else None,
        },
        "lower_carbon": run.hints,
        "sources": sources,
        "assumptions": run.assumptions,
        "factors_version": f["version"],
        "attribution": [s["attribution"] for s in sources if s.get("attribution")],
    }
