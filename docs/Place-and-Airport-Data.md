# Place and Airport Data

Travel Planner turns whatever the user types ("Milano", "Portland, ME", "Zermatt") into airport codes for live flight search, and offers an airport-and-place typeahead. Both run against open data committed to the repo and seeded into SQLite. No web call is involved, except for one narrow case described under [Bare airport codes](#bare-airport-codes).

---

## Sources and licences

| Source | Files used | Licence |
|---|---|---|
| [OurAirports](https://ourairports.com/data/) | `airports.csv`, `regions.csv`, `countries.csv` | Public domain |
| [GeoNames](https://www.geonames.org/) | `cities1000.txt`, `admin1CodesASCII.txt`, `allCountries.zip` | [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/) |

**Attribution:** Contains data from GeoNames (geonames.org), CC BY 4.0. The GeoNames data has been modified (filtered, name-folded, scored and linked to airports), and GeoNames does not endorse these changes. Airport data comes from OurAirports.

The app footer shows "Place data © GeoNames (CC BY 4.0) · Airport data: OurAirports". `backend/app/db/data/README.md` holds the full source, licence and derivation notes.

**Snapshot date:** **2026-10-29** for OurAirports, `cities1000` and `admin1CodesASCII`; **2026-10-30** for `allCountries`.

---

## Committed files

`backend/app/db/data/`:

| File | Size | Contents |
|---|---|---|
| `airports.csv` | 347 KB | 4,014 airports (4,010 with scheduled service): iata, icao, name, city, country, country_code, region, type_rank, scheduled, lat, lng |
| `places.csv.gz` | 5.6 MB | 162,014 GeoNames places with at least 1,000 people (excluding sections of places and historical, abandoned or destroyed places), each linked to up to 3 ranked airports, with folded alternate names for places of 15k or more and a `satellite` flag (see [Suburbs](#suburbs-satellite-places)) |
| `features.csv.gz` | 0.9 MB | 14,186 notable GeoNames features that are not towns: islands, parks, resorts, regions, mountains, valleys, lakes, deserts, canyons and ancient sites, each with up to 3 airports |
| `admin1.csv` | 121 KB | 3,865 first-level divisions (states, provinces, regions) |
| `countries.csv` | 265 KB | Every OurAirports country, with 18,205 native and other-language names from GeoNames ("Deutschland", "Brasil", "Nippon") |
| `hints.json` | 15 KB | Hand-curated, not generated (see below) |
| `README.md` | 10 KB | Sources, licences, derivation rules, regeneration, conflict report |

The total is about 7 MB (the limit is 9 MB). In addition, `backend/app/db/seed_airports.py` holds a curated list of 402 airports with served-city overrides, and `REPLACED_CODES` maps 14 retired codes to their replacements (for example PNH → KTI).

### hints.json

Curated knowledge the open data lacks:

| Key | Entries | Purpose |
|---|---|---|
| `islands` | 105 | Islands and their airports ("Sicily" → CTA, PMO, TPS; "Borneo" → BKI, KCH) |
| `destinations` | 82 | Places without a useful airport of their own ("Machu Picchu" → CUZ, "Kyoto" → KIX, ITM; "Zermatt" → ZRH, GVA; "Monte Carlo" → NCE) |
| `regions` | 20 | Regions ("Algarve" → FAO) |
| `exonyms` | 80 | Other-language or English names mapped to a GeoNames id, or to `"ambiguous"` ("Cologne" → Köln, "Milano" → Milan; "Odessa" is ambiguous unless qualified) |
| `city_aliases` | 19 | Shorthands (SF, LA, KL, HCMC, NOLA…) |
| `country_aliases` | 45 | "UK", "England", "Holland", "DPRK", "Eire"… |
| `qualifier_country_aliases` | 4 | KSA, PRC, ROK, ROC: countries only as a qualifier ("Riyadh, KSA", "Beijing PRC"), because typed alone each is a scheduled airport code (Kosrae, Prescott, Rockhampton, Rochester) |
| `saint_exceptions` | 2 | Names that must not get St/Saint variants |

---

## Regenerating the data

`backend/scripts/build_place_data.py` is standard-library only and deterministic (sorted rows, gzip mtime 0); it takes about a minute and treats the downloaded sources as untrusted input. Download the OurAirports CSVs and GeoNames `cities1000.zip` / `admin1CodesASCII.txt` / `allCountries.zip` (423 MB, streamed, not unzipped) into a directory of their own, then from the repo root:

```bash
python3 -I backend/scripts/build_place_data.py \
    --ourairports /path/to/ourairports-src \
    --geonames-cities /path/to/geonames-src/extracted/cities1000.txt \
    --geonames-admin1 /path/to/geonames-src/admin1CodesASCII.txt \
    --geonames-all /path/to/geonames-src/allCountries.zip \
    --out backend/app/db/data > conflicts.txt
```

The script writes `airports.csv`, `places.csv.gz`, `admin1.csv`, `countries.csv` and `features.csv.gz`, and prints a summary and a conflict report to stdout (not committed). Then run `python3 -m pytest tests/test_build_place_data.py` from `backend/`, update the snapshot date in the data README, and commit the five files. The data README holds the derivation rules, including the notability threshold calibration for features. `hints.json` is edited by hand.

---

## Versioned seeding

At startup, `seed()` in `backend/app/db/seed_airports.py` loads the files into the `airports`, `places`, `place_names`, `features`, `feature_names` and `admin1` tables of `$DATA_DIR/airports.db`. `feature_names` holds each feature's name, its ASCII spelling and both without a generic part ("Kakadu National Park" → "kakadu", "Mount Everest" → "everest") as tier 0, and its alternate names as tier 1.

- The **data version** is the sha256 of a loader tag (`place-data-loader:3`) plus the bytes of `airports.csv`, `places.csv.gz`, `admin1.csv` and `features.csv.gz`, truncated to 16 hex characters and stored as `meta.place_data_version`. An older `places` table gains its `satellite` column in place.
- If the stored version matches, seeding is skipped (about 5 ms).
- Otherwise one `BEGIN IMMEDIATE` transaction (waiting up to 30 s for another worker's lock) upserts the airports, sets `scheduled = 0` on old rows missing from the dataset, and rebuilds places, place names and divisions with their indexes. On an empty database this takes about 2.5 s and produces about 316,000 place-name rows, 113,000 feature-name rows and a database of about 33 MB.
- Backups leave these tables and the version out, so a restored database reseeds them.

It can also be run by hand: `cd backend && python -m app.db.seed_airports`. After seeding, `places_db.warm()` builds an in-memory airport-name index (about 0.06 s).

---

## How a typed place resolves

`lookup_city_iata(text)` (`backend/app/db/database.py`) returns up to 3 comma-joined scheduled airport codes, best first, or `None`. The request validator (`backend/app/schemas/request.py`) uses it to fill `origin_iata` and `destination_iata` for flight search, the fare calendar and Compare. When it returns `None`, flights fall back to AI estimates for that route.

### The rules, in order

1. **An airport code.** An upper-case three-letter code is used as typed, after mapping retired codes ("LHR" → LHR, "PNH" → KTI). Lower-case text tries places first and falls back to the code only if it is a scheduled airport ("lhr" → LHR).
2. **A typeahead label** such as "LGW — London, United Kingdom" uses its code alone.
3. **A curated hint**: an island, destination or region from `hints.json`, unless a stated country contradicts it.
4. **The curated city list**: airports whose served city matches the text (accent-folded, with St/Saint variants and city aliases), restricted by any stated country, ISO code, alias or region code. A city name that is ambiguous or contested gives `None`.
5. **GeoNames place resolution** (`resolve_place`, `backend/app/db/places_db.py`):
   - Candidates are places whose own name matches. Alternate names count only when no place has that own name, or when the own-name places are small (under 20k) and the alternate one is at least 10× bigger and 150k or more.
   - Exonyms from `hints.json` map an English name to a specific place, or mark it ambiguous.
   - A country typed alone gives its top place; a first-level division ("Florida", "Scotland") joins as its top place unless a town of that name is comparably notable. Country names include the native and other-language names in `countries.csv` ("Deutschland" → BER, "Nippon" → HND); a name that is also the own name of a town of 15k or more stays the town's ("Nederland", Colorado).
   - Stated qualifiers (country name in any of those forms, ISO code, alias, a qualifier-only alias such as KSA, US/CA/AU/BR/IN region code or a division name) filter the candidates ("Berlin, Deutschland", "Riyadh, KSA"). A qualifier that contradicts every candidate gives `None`.
   - An airport whose whole name equals the text can win ("Wagga Wagga" → WGA), but never over a place of 40k or more.
   - **Suburbs yield to towns with their own airport.** When the top candidate is a [satellite](#suburbs-satellite-places) and the best candidate whose first airport is its own scores at least 1/10 of it, the satellites scoring above that town drop out ("Peoria" → PIA, Illinois, not the Phoenix suburb).
   - **The winner must score 3× the next candidate** (score = population × notability). A place under 15k wins only alone or through a hint; one under 5k with no airport within 100 km gives `None`.
   - **Non-town features.** When no candidate is a town of 15k or more (and no division or curated city has the name), a notable [feature](#non-town-features) by that name answers with its airports ("Kakadu" → DRW; "Arches" → the national park's CNY, not the French village), unless a town of that name lies within 50 km of it (Paros, Naxos: the island town and its airport). Of several features, the most notable needs 3× the next one's notability.
   - The place's linked airports are returned. With a curated city in the same country they are appended to the curated codes ("New York" → JFK, LGA, EWR); otherwise foreign airports are dropped unless the place has no domestic one.
6. **Last resort**: dataset airports whose display city matches.

Text without a comma is also tried as "City, Qualifier" when the last words name a country or region ("Chicago IL", "Berlin Germany"). Generic affixes are retried too ("Zanzibar Island", "Banff National Park", "Tokyo city").

### Suburbs (satellite places)

A place is a *satellite* when its first airport is not its own but the own airport of a place scoring at least 10× more within 60 km: Peoria, Arizona flies from Phoenix's PHX, while Peoria, Illinois has PIA. "Own" is the shared rule (`core.places.is_own_airport`: the airport's display city is the place, its name names the place, or it is in the same country within 25 km). Two comparable suburbs stay ambiguous ("Glendale": California and Arizona → `None`), and a satellite keeps its lead over a far smaller namesake.

### Non-town features

`features.csv.gz` holds 14,186 GeoNames features that are not towns: islands, archipelagos and atolls, peninsulas, parks and reserves, resorts, regions and coasts, mountains, ranges, peaks and volcanoes, valleys, lakes, beaches, ancient and historical sites, ruins and monuments, deserts, gorges and canyons. Only notable ones are kept: at least 10 GeoNames alternate names, and an airport. Their airports are those on the island (for islands), then large and medium airports within 250 km, same country first, large before medium. The data README has the calibration (5 → 83k features and 3.6 MB; 10 → 14k and 0.9 MB; 20 → 1.3k).

Curated hints still come first; features answer names the hints do not cover ("Grand Teton" → JAC, "Crater Lake" → MFR, "Mount Rushmore" → RAP, "Tikal" → FRS, "Haida Gwaii" → YZP). Vast regions give a single point, so their airports can be rough (the Florida Keys give MIA before Key West); big islands with several gateways are curated ("Borneo" → BKI, KCH).

### Examples

Results from the current data:

| Input | Result | Why |
|---|---|---|
| `Milano` | LIN, MXP, BGY | Exonym entry mapping the Italian name to Milan |
| `Kyoto` | KIX, ITM | Curated destination hint (Kyoto has no airport) |
| `Zermatt` | ZRH, GVA | Curated destination hint (no airport nearby) |
| `Portland, ME` | PWM | The state qualifier picks Portland, Maine |
| `Portland` | PDX | Portland, Oregon dominates by score |
| `Valencia` | None | Valencia, Spain and the larger Valencia, Venezuela: ambiguous |
| `Valencia, Spain` | VLC | The country qualifier settles it |
| `Monte Carlo` | NCE | Curated destination hint |
| `New York` | JFK, LGA, EWR | Curated city plus the place's other airports |
| `Chicago IL` | ORD, MDW, GYY | No-comma reading as "Chicago, IL" |
| `Paris, Texas` | DAL, DFW | Never CDG |
| `Springfield` | None | Many similar-sized namesakes |
| `Berlin, Japan` | None | The stated country contradicts the place |
| `Deutschland` | BER | GeoNames country name |
| `Riyadh KSA` | RUH | No-comma qualifier; KSA alone stays Kosrae's code |
| `Peoria` | PIA | Peoria, Arizona is a Phoenix suburb (satellite) |
| `Glendale` | None | Two comparable suburbs |
| `Kakadu` | DRW | Notable national park, no town of that name |
| `Everest` | KTM, LUA, TPJ | Mount Everest (a feature) |

### Bare airport codes

The one web path: when a request's origin or destination is a bare 3-letter code that is not in the database or `REPLACED_CODES`, `lookup_iata` runs a DuckDuckGo search plus a Haiku extraction to name the city, and stores the answer (`backend/app/db/database.py`). Everything else is local.

### Folding and shared rules

`app.core.places.fold_place` (accent and case folding) is shared by the generator and the runtime, so names match the same way in both. `backend/app/core/places.py` also loads `hints.json` and defines `OWN_AIRPORT_KM = 25` and `NEVER_LINK = {"ECN"}` (Ercan is never suggested for a place, only when typed). Region code tables for the US, Canada, Australia, Brazil and India live in `backend/app/db/airport_regions.py`.

---

## Autocomplete

`GET /api/airports/search?q=&limit=` (`search_airports` in `backend/app/db/database.py`; default 10 results, at most 50):

- Matches airports by code, city, airport name or country, plus the airports of GeoNames places and curated hints whose folded name starts with the query ("kyoto" → ITM, KIX, …; "milan" → MXP, LIN, BGY).
- From the fourth letter, when no town of 15k or more and no curated hint matches, up to 3 notable features whose name starts with the query add their airports, below every town match ("kakadu" → DRW, MNG).
- Alternate names count for places of 100k or more from the fourth letter ("münch" → München).
- A place contributes only its own-country airports, and only places scoring at least 1/10 of the best match count.
- Order: exact code, code prefix, exact name, name prefix, then the rest. Lower-case three-letter text that names a place lists the place first ("hue" → HUI; "HUE" → HUE). Within a class, the more notable place comes first, then curated order, then the bigger airport.
- "Contains" matches are dropped once there are real matches, and unscheduled airports appear only for their exact code.

Each row has `iata_code, name, city, country, country_code`.

---

## Quality

- **Golden set.** `backend/tests/data/golden_places.csv` has 731 cases (438 resolution, 275 data, 18 autocomplete; 573 "first code matches", 98 exact, 50 subset and 10 expected `None`). `tests/test_golden_places_runtime.py` runs them all and forbids web calls.
- **Fresh blind probe.** On inputs not used during development, about 1.7% resolved to a wrong airport. More inputs now resolve to `None` by design: when a name is genuinely ambiguous, no answer (and an AI-estimated fare) is better than a confident wrong airport.
- **Country names, suburbs and features (2026-10-30).** On the five earlier probe sets (2,484 inputs) no input gained a wrong airport; one wrong answer was fixed (Peoria) and 50 inputs that gave `None` now resolve, mostly parks, islands and regions.
- **Speed.** `lookup_city_iata` takes about 0.8 ms per call at p50 and under 2.5 ms at p99 (warm), so request handlers call it synchronously.
