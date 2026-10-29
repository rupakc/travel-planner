# Comprehensive Airport & Place Data Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Replace the hand-typed 544-airport list with a comprehensive, regenerable dataset (OurAirports scheduled airports + GeoNames places ≥1,000 people) so any typed city, town, airport or alternate spelling resolves to the right airports and country — and close the remaining open items from PRs #17/#18.

**Spec:** User request 2026-10-30: "address the remaining items … make the airport data VERY VERY COMPREHENSIVE … VERY IMPORTANT AND CRITICAL FOR THE ENTIRE APPLICATION". The user approved downloading OurAirports (airports/regions/countries CSV, public domain) and GeoNames cities1000 + admin1CodesASCII (CC BY 4.0). Choices otherwise Claude's.

## Source data (already downloaded — untrusted input, read with `python3 -I`, never executed)
- OurAirports: `/private/tmp/claude-501/-Users-rupak-travel-planner/6a423640-de0e-4ae7-a160-af5d4cd4d6e9/scratchpad/ourairports-src/{airports,regions,countries}.csv` (snapshot 2026-10-29).
- GeoNames: `/private/tmp/claude-501/-Users-rupak-travel-planner/6a423640-de0e-4ae7-a160-af5d4cd4d6e9/scratchpad/geonames-src/extracted/cities1000.txt` (171,731 rows, tab-separated, standard GeoNames columns) and `…/geonames-src/admin1CodesASCII.txt`.
- Prototype showing the linking approach works: `/private/tmp/claude-501/-Users-rupak-travel-planner/6a423640-de0e-4ae7-a160-af5d4cd4d6e9/scratchpad/oa-scripts/proto.py` (reference only; known flaws listed below are fixed by this design).

## Verified facts that drive the design
- OurAirports `municipality` is the physical location, not the city served: MXP "Ferno (VA)", BRU "Zaventem", CCS "Maiquetía", LEJ "Schkeuditz", SYD "Sydney (Mascot)", CDG "Paris (Roissy-en-France, Val-d'Oise)". Never use it alone as the served city.
- OurAirports `type` is not a size signal (PWM, BHM, VLN, HHN are all `large_airport`).
- 9,052 OA rows have IATA codes; 4,010 are large/medium/small with `scheduled_service=yes` (use these; heliports/seaplane bases excluded).
- The curated list (`backend/app/db/seed_airports.py`) has stale/wrong codes: PNH/REP (closed, replaced by KTI/SAI), KBP/IEV/LWO/ODS (no scheduled service), ULN→UBN, DKR→DSS, KIV (OA: RMO), TIP (OA: MJI), NIY (Freetown is FNA), PBI (OA lists KPBI with IATA DJT). OA is authoritative for codes, names, coordinates, region and scheduled status; the curated list is authoritative only for the served-city display name of its airports and as the "tier 0" name layer.
- GeoNames alternate names cause false hits if treated like primary names (prototype: "Cancun"→Changchun, "Venice"→Dayton, "Bali"→Bari).
- Population alone mis-ranks namesakes; population × notability fixes them (data checked): score = population × (alternate_name_count + 1)² × (3 if feature code PPLC). Results at a 3× dominance threshold: Interlaken→CH, Venice→IT, Victoria→CA (not the HK district), Portland→US-OR, Birmingham→GB, Paris/Rome/Athens/Florence/Naples/Sydney/Melbourne/Perth→the famous one; Valencia, Cambridge, Toledo, Hamilton, San Jose, Springfield→ambiguous.
- `get_connection()` returns a raw `sqlite3.Connection`; `with conn:` commits but never closes (connections leak until GC).

## Design (binding)

### A. Generator (`backend/scripts/build_place_data.py`, stdlib only, deterministic output, run manually; never at app runtime)
Inputs: paths to the OA and GeoNames files + the curated `AIRPORTS` list. Outputs (committed):
1. `backend/app/db/data/airports.csv` — one row per airport: every OA large/medium/small airport with `scheduled_service=yes` and an IATA code, plus every curated code (curated codes not scheduled in OA kept with `scheduled=0`). Columns: `iata, icao, name, city, country, country_code, region (OA iso_region, e.g. US-OR), type_rank (0 large,1 medium,2 small,9 other), scheduled (1/0), lat, lng`. `country` = OA countries.csv name, except keep the curated spelling for curated airports' countries (so existing displays like "United States"/"United Kingdom" don't change). `city` (display) = curated city when curated; else the highest-scoring place that links this airport (below) within 80 km; else the cleaned municipality (text before the first "(" or ","; for "A/B" keep "A").
2. `backend/app/db/data/places.csv.gz` — one row per GeoNames place with feature code not in {PPLX, PPLH, PPLQ, PPLW, PPLCH}: `geonameid, name, country_code, admin1, population, score, lat, lng, airports (space-separated IATA, ranked, ≤3), alt_names ("|"-joined folded names)`. Alt names: Latin-script only, ≤40 chars, not URLs/codes (all-uppercase ≤4 chars), folded, de-duplicated, excluding the place's own folded name; keep them only for places with population ≥ 15,000 (size control). Notability count for `score` uses the raw alternate-name count.
3. `backend/app/db/data/admin1.csv` — `code (e.g. US.OR, CA.08, AU.08, DE.02, GB.ENG), name, folded_name` from admin1CodesASCII.
4. A conflict report printed to stdout (not committed): curated codes missing/unscheduled in OA, curated vs OA country mismatches, airports whose display city fell back to municipality for type_rank 0.

Linking (place → airports), scheduled airports only:
- Reach per airport type: large 80 km (100 km when place population ≥ 1,000,000 and no large airport is within 50 km), medium 50 km, small 30 km. Rank linked airports by (type_rank, distance); keep ≤3.
- No airport in reach → nearest large/medium within 150 km (≤2). Still none → empty.
- Folding (shared with runtime, see C): NFKD strip combining marks; ß→ss ø→o æ→ae œ→oe ł→l đ→d ı→i þ→th ð→d; lower-case; "." and "-" → space; collapse whitespace.

### B. Storage & seeding (`backend/app/db/database.py`, `backend/app/db/seed_airports.py`)
- Schema: `airports` gains `region TEXT, type_rank INTEGER, scheduled INTEGER DEFAULT 1` (migrate existing DBs with `ALTER TABLE … ADD COLUMN` when missing). New tables: `places(geonameid PK, name, country_code, admin1, population, score, lat, lng, airports)`, `place_names(name_folded, geonameid, tier)` with an index on `name_folded` (tier 0 = primary/ascii name, 1 = alternate), `admin1(code PK, name, folded_name)`, `meta(key PK, value)`.
- Versioned seeding: `PLACE_DATA_VERSION` = hash of the three data files (computed once, cheap) stored in `meta`. On startup, when the stored version differs: in ONE transaction upsert all dataset airports (`INSERT … ON CONFLICT(iata_code) DO UPDATE`), leave rows not in the dataset (web-saved) untouched but set their `scheduled` to 1 only if unknown, and rebuild places/place_names/admin1. Equal version → skip (fast startup). Startup log line with counts and seconds.
- `get_connection()` closes connections: make it a context manager (`@contextmanager`) that yields the connection, commits on success, rolls back on error and always closes. Every caller in `backend/app` must keep working (grep all callers; the `with get_connection() as conn:` pattern stays valid).
- Tests: the suite must not get meaningfully slower (≤ +15% wall time). Seed the place data once per session (session fixture / shared seeded DB file copied per test DB if tests use separate DBs), not per test.
- Drop the per-airport curated `AIRPORT_REGION` map in favour of the dataset `region`, keeping only the deliberate extras as an overrides table (IAD/DCA also "dc", MCI also "ks"); existing region tests must stay green.

### C. Resolution (`backend/app/core/places.py`, `lookup_city_iata`, `static_results._place_country`)
- One shared `fold_place` (A) and one consolidated country alias map in `core/places.py` (merge `database._COUNTRY_CODE_ALIASES` and the static_results country aliases; both modules import it).
- `resolve_place(text) -> Place | None` in a new `backend/app/db/places_db.py` (one indexed query for names + one for admin1 when a region is stated):
  1. Parse: strip a known-airport-code prefix ("BER — …"), split city / stated last segment. Stated segment may be a country (name/alias/ISO), a US/CA/AU/BR region code (existing tables), or an admin1 name (any country, folded, e.g. "Bavaria", "Ontario", "New South Wales", "England").
  2. Candidates: places whose tier-0 name equals the folded city (also try St./Saint variants); only if none, tier-1 (alternate) matches.
  3. Filter by the stated country/region (region via admin1 code or name; a code with several readings keeps every reading's places). Stated country with no candidates in it → None.
  4. Curated hint: if `_CITY_TO_COUNTRY` (curated city map) names a country for this city and candidates exist in it, keep only those.
  5. Winner: highest `score` if ≥ 3× the next candidate's score; else None (ambiguous).
- `lookup_city_iata(text)` order: bare code → known-code prefix → curated tier (today's curated-name logic over curated airports, **excluding airports with scheduled=0**) giving codes in curated order → then place resolution; when both apply to the same city, curated codes first then the place's linked airports, de-duplicated, ≤3. Never return scheduled=0 airports. Unknown → None.
- `static_results._place_country`: unchanged curated logic first; when it returns None for an unknown city (not for an explicit "no row" ruling like "Paris, TX"), fall back to `resolve_place` and map its country code through the ISO→table map (only countries present in the tables). Rulings that must hold: "Paris, Texas"/"Paris, TX" → None; "Tbilisi, Georgia" → None or georgia-if-in-tables (never usa); "Denver, CO" → usa; "Smalltown, CO" → None.
- `search_airports` (autocomplete): also match places by folded name prefix and return their linked airports; order: exact code, code prefix, exact city/place name, prefix, other; within a class by type_rank then name; exclude scheduled=0 unless the code was typed exactly. Response shape unchanged.

### D. Expected behaviour (tests must pin all of these)
- Airports: "Milan"/"Milano" → LIN/MXP/BGY set incl. MXP; "Brussels" → BRU first; "Caracas" → CCS; "Frankfurt" → FRA only (HHN excluded: 115 km); "Paris" → CDG,ORY first (curated order); "London" → LHR,LGW,STN (curated order); "New York" → JFK,LGA,EWR; "Tokyo" → HND/NRT; "Washington" → starts IAD,DCA (curated) ; "Kyoto" → ITM and/or KIX; "Ubud" → DPS; "Zermatt"/"Interlaken" → nearest scheduled airports (BRN/ZRH/GVA/SIR region — assert non-empty and Swiss/nearby); "Bombay" → BOM; "Saigon" → SGN; "München" → MUC; "Lisboa" → LIS; "Phnom Penh" → KTI (not PNH); "Siem Reap" → SAI (not REP); "Chisinau"/"Chișinău" → RMO; "London, ON"/"London, Ontario" → YXU; "Sydney, Nova Scotia" → YQY; "Portland" → PDX (dominance; changes the old None ruling — update that test); "Portland, ME" → PWM; "Birmingham" → BHX; "Birmingham, AL" → BHM; "Valencia" → None; "Valencia, Spain" → VLC; "San Jose" → None; "Springfield" → None; "Springfield, IL" → SPI if scheduled in data; "Venice" → VCE/TSF; "Interlaken, Switzerland" non-empty; "Cancun" → CUN; "Bali" → DPS (curated); "Munich, Bavaria" → MUC; "Perth, WA" → PER; "Seattle, WA" → SEA; "Kansas City, KS" → MCI; "St Louis" → STL; "Paris, Texas" → None or PRX-if-scheduled (never CDG); "Toronto, CA" → YYZ; bare "NYC" → NYC; "LGW — London, …" → LGW.
- Countries (`_place_country`): "St Petersburg" → russia; "Zermatt" → switzerland; "Ubud" → indonesia; "Hallstatt" → austria only if present in cities1000 else None; "Kyoto" → japan; "Interlaken" → switzerland; "Venice" → italy; all existing static-lookup tests green.
- Autocomplete: "milan" → MXP/LIN/BGY with city "Milan"; "kyoto" → returns ITM/KIX; "zermatt" non-empty; "lhr" → LHR first; "lon" → London airports before e.g. Long Beach.

### E. Remaining open items (close or rule explicitly in the report)
- Accented web-saved rows: folded names apply to every airport row (dataset or web) via `place_names`/folded city matching.
- Washington handled (curated + places); St Petersburg static row (via fallback); London, Ontario (data); connections closed (B); duplicate alias maps (C).
- Sync SQLite in async handlers: keep sync (sub-millisecond indexed reads) — document the measured lookup time in the report.

Docs: `backend/app/db/data/README.md` (sources, licences — OurAirports public domain, GeoNames CC BY 4.0 attribution "Contains data from GeoNames (geonames.org), CC BY 4.0" — snapshot date, exact regeneration command, conflict-report summary); Architecture/API docs lines on place resolution; CLAUDE.md one line under Key Conventions.

## Global Constraints
No new dependencies (stdlib only in the generator). No network in tests or at runtime. Backend pytest + ruff check + ruff format --check; frontend untouched (its tests still pass). Committed data ≤ 8 MB total. Startup with an unchanged dataset adds < 100 ms; first seed < 10 s.

---
### Task 1: Generator + committed data files + data README (+unit tests on fold/link/score/municipality-cleaning with small fixtures)
### Task 2: Schema migration, versioned seeding, places tables, closing connections, test-suite seeding (+tests)
### Task 3: resolve_place, lookup_city_iata on places, _place_country fallback, alias consolidation, autocomplete (+tests for every line in D)
### Task 4: Docs (CLAUDE.md, API/Architecture), measured timings, conflict-report rulings list
