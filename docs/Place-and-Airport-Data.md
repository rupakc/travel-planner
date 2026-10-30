# Place and Airport Data

Travel Planner turns whatever the user types ("Milano", "Portland, ME", "Zermatt") into airport codes for live flight search, and offers an airport-and-place typeahead. Both run against open data committed to the repo and seeded into SQLite. No web call is involved, except for one narrow case described under [Bare airport codes](#bare-airport-codes).

---

## Sources and licences

| Source | Files used | Licence |
|---|---|---|
| [OurAirports](https://ourairports.com/data/) | `airports.csv`, `regions.csv`, `countries.csv` | Public domain |
| [GeoNames](https://www.geonames.org/) | `cities1000.txt`, `admin1CodesASCII.txt` | [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/) |

**Attribution:** Contains data from GeoNames (geonames.org), CC BY 4.0. The GeoNames data has been modified (filtered, name-folded, scored and linked to airports), and GeoNames does not endorse these changes. Airport data comes from OurAirports.

The app footer shows "Place data © GeoNames (CC BY 4.0) · Airport data: OurAirports". `backend/app/db/data/README.md` holds the full source, licence and derivation notes.

**Snapshot date** of both sources: **2026-10-29**.

---

## Committed files

`backend/app/db/data/`:

| File | Size | Contents |
|---|---|---|
| `airports.csv` | 347 KB | 4,014 airports (4,010 with scheduled service): iata, icao, name, city, country, country_code, region, type_rank, scheduled, lat, lng |
| `places.csv.gz` | 5.5 MB | 162,014 GeoNames places with at least 1,000 people (excluding sections of places and historical, abandoned or destroyed places), each linked to up to 3 ranked airports, with folded alternate names for places of 15k or more |
| `admin1.csv` | 121 KB | 3,865 first-level divisions (states, provinces, regions) |
| `countries.csv` | 3.5 KB | Every OurAirports country, used for country names in resolution |
| `hints.json` | 15 KB | Hand-curated, not generated (see below) |
| `README.md` | 10 KB | Sources, licences, derivation rules, regeneration, conflict report |

The total is about 6 MB (the limit is 8 MB). In addition, `backend/app/db/seed_airports.py` holds a curated list of 402 airports with served-city overrides, and `REPLACED_CODES` maps 14 retired codes to their replacements (for example PNH → KTI).

### hints.json

Curated knowledge the open data lacks:

| Key | Entries | Purpose |
|---|---|---|
| `islands` | 104 | Islands and their airports ("Sicily" → CTA, PMO, TPS) |
| `destinations` | 82 | Places without a useful airport of their own ("Machu Picchu" → CUZ, "Kyoto" → KIX, ITM; "Zermatt" → ZRH, GVA; "Monte Carlo" → NCE) |
| `regions` | 20 | Regions ("Algarve" → FAO) |
| `exonyms` | 80 | Other-language or English names mapped to a GeoNames id, or to `"ambiguous"` ("Cologne" → Köln, "Milano" → Milan; "Odessa" is ambiguous unless qualified) |
| `city_aliases` | 19 | Shorthands (SF, LA, KL, HCMC, NOLA…) |
| `country_aliases` | 43 | "UK", "England", "Holland"… |
| `saint_exceptions` | 2 | Names that must not get St/Saint variants |

---

## Regenerating the data

`backend/scripts/build_place_data.py` is standard-library only and deterministic (sorted rows, gzip mtime 0); it takes about 5 s and treats the downloaded sources as untrusted input. Download the OurAirports CSVs and GeoNames `cities1000.zip` / `admin1CodesASCII.txt` into a directory of their own, then from the repo root:

```bash
python3 -I backend/scripts/build_place_data.py \
    --ourairports /path/to/ourairports-src \
    --geonames-cities /path/to/geonames-src/extracted/cities1000.txt \
    --geonames-admin1 /path/to/geonames-src/admin1CodesASCII.txt \
    --out backend/app/db/data > conflicts.txt
```

The script writes `airports.csv`, `places.csv.gz`, `admin1.csv` and `countries.csv`, and prints a summary and a conflict report to stdout (not committed). Then run `python3 -m pytest tests/test_build_place_data.py` from `backend/`, update the snapshot date in the data README, and commit the four files. `hints.json` is edited by hand.

---

## Versioned seeding

At startup, `seed()` in `backend/app/db/seed_airports.py` loads the files into the `airports`, `places`, `place_names` and `admin1` tables of `$DATA_DIR/airports.db`.

- The **data version** is the sha256 of a loader tag plus the bytes of `airports.csv`, `places.csv.gz` and `admin1.csv`, truncated to 16 hex characters and stored as `meta.place_data_version`.
- If the stored version matches, seeding is skipped (about 5 ms).
- Otherwise one `BEGIN IMMEDIATE` transaction (waiting up to 30 s for another worker's lock) upserts the airports, sets `scheduled = 0` on old rows missing from the dataset, and rebuilds places, place names and divisions with their indexes. On an empty database this takes about 2 s and produces about 316,000 name rows and a database of about 29 MB.
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
   - A country typed alone gives its top place; a first-level division ("Florida", "Scotland") joins as its top place unless a town of that name is comparably notable.
   - Stated qualifiers (country, ISO code, alias, US/CA/AU/BR/IN region code or a division name) filter the candidates. A qualifier that contradicts every candidate gives `None`.
   - An airport whose whole name equals the text can win ("Wagga Wagga" → WGA), but never over a place of 40k or more.
   - **The winner must score 3× the next candidate** (score = population × notability). A place under 15k wins only alone or through a hint; one under 5k with no airport within 100 km gives `None`.
   - The place's linked airports are returned. With a curated city in the same country they are appended to the curated codes ("New York" → JFK, LGA, EWR); otherwise foreign airports are dropped unless the place has no domestic one.
6. **Last resort**: dataset airports whose display city matches.

Text without a comma is also tried as "City, Qualifier" when the last words name a country or region ("Chicago IL", "Berlin Germany"). Generic affixes are retried too ("Zanzibar Island", "Banff National Park", "Tokyo city").

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

### Bare airport codes

The one web path: when a request's origin or destination is a bare 3-letter code that is not in the database or `REPLACED_CODES`, `lookup_iata` runs a DuckDuckGo search plus a Haiku extraction to name the city, and stores the answer (`backend/app/db/database.py`). Everything else is local.

### Folding and shared rules

`app.core.places.fold_place` (accent and case folding) is shared by the generator and the runtime, so names match the same way in both. `backend/app/core/places.py` also loads `hints.json` and defines `OWN_AIRPORT_KM = 25` and `NEVER_LINK = {"ECN"}` (Ercan is never suggested for a place, only when typed). Region code tables for the US, Canada, Australia, Brazil and India live in `backend/app/db/airport_regions.py`.

---

## Autocomplete

`GET /api/airports/search?q=&limit=` (`search_airports` in `backend/app/db/database.py`; default 10 results, at most 50):

- Matches airports by code, city, airport name or country, plus the airports of GeoNames places and curated hints whose folded name starts with the query ("kyoto" → ITM, KIX, …; "milan" → MXP, LIN, BGY).
- Alternate names count for places of 100k or more from the fourth letter ("münch" → München).
- A place contributes only its own-country airports, and only places scoring at least 1/10 of the best match count.
- Order: exact code, code prefix, exact name, name prefix, then the rest. Lower-case three-letter text that names a place lists the place first ("hue" → HUI; "HUE" → HUE). Within a class, the more notable place comes first, then curated order, then the bigger airport.
- "Contains" matches are dropped once there are real matches, and unscheduled airports appear only for their exact code.

Each row has `iata_code, name, city, country, country_code`.

---

## Quality

- **Golden set.** `backend/tests/data/golden_places.csv` has 693 cases (400 resolution, 275 data, 18 autocomplete; 541 "first code matches", 94 exact, 50 subset and 8 expected `None`). `tests/test_golden_places_runtime.py` runs them all and forbids web calls.
- **Fresh blind probe.** On inputs not used during development, about 1.7% resolved to a wrong airport. More inputs now resolve to `None` by design: when a name is genuinely ambiguous, no answer (and an AI-estimated fare) is better than a confident wrong airport.
- **Speed.** `lookup_city_iata` takes well under 2 ms per call (p50 about 0.6 ms), so request handlers call it synchronously.
