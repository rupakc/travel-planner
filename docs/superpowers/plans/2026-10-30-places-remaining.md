# Place Resolution — Remaining Items Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Resolve the three open place-lookup items generically: (1) country nicknames and native names ("Deutschland", "Brasil", "España", "Nippon", "KSA", "PRC"…), (2) suburbs without their own airport beating namesake cities that have one ("Peoria" → Arizona instead of Illinois/PIA), (3) islands, national parks, ski resorts, regions, mountains, valleys and archaeological sites that are not towns returning None.

**Spec:** User request 2026-10-30 ("proceed with the Still Open items and solve them comprehensively"). The user approved downloading GeoNames `allCountries.zip` (CC BY 4.0, same licence as the cities file already used). Choices otherwise Claude's.

## Source
- `/private/tmp/claude-501/-Users-rupak-travel-planner/6a423640-de0e-4ae7-a160-af5d4cd4d6e9/scratchpad/geonames-all/allCountries.zip` (untrusted data: read with `python3 -I`, stream the zip — do not unzip 1.6 GB to disk unless needed; never execute anything from it). Standard GeoNames columns (geonameid, name, asciiname, alternatenames, lat, lng, feature class, feature code, country code, cc2, admin1, admin2, admin3, admin4, population, elevation, dem, timezone, modified).
- Existing: generator `backend/scripts/build_place_data.py`, data in `backend/app/db/data/` (airports.csv, places.csv.gz, admin1.csv, countries.csv, hints.json), runtime `backend/app/db/places_db.py` (`resolve_place`), `backend/app/db/database.py` (`lookup_city_iata`, `search_airports`), `backend/app/agents/static_results.py` (`_place_country`), golden set `backend/tests/data/golden_places.csv`, data README.

## Verified facts
- "Peoria": Peoria US-AZ (pop 190,985, score 3.87e8, airports `PHX` — PHX's display city is Phoenix) vs Peoria US-IL (pop 115,070, score 1.04e8, airports `PIA`, its own). AZ wins by 3.7× today.
- Same pattern elsewhere: Aurora CO/IL (both suburbs of Denver/Chicago), Glendale CA/AZ (both suburbs), Arlington TX/VA (both suburbs).
- OurAirports `countries.csv` keywords are too noisy for native names; GeoNames political-entity features carry multilingual alternate names.

## Design (binding)

### A. Country names (generic)
- Generator: from allCountries features with feature class `A` and codes `PCLI, PCLD, PCLF, PCLS, PCL, PCLIX, TERR` collect the name, asciiname and Latin-script alternate names (≤40 chars, not URLs, not ISO-3 or other all-caps ≤4 tokens unless in the curated alias list) per ISO country code; write them as a `names` column (`|`-joined, folded) in `backend/app/db/data/countries.csv`.
- Curated aliases (hints.json) only for colloquial abbreviations GeoNames lacks, each verified absent from the data first: at least KSA → SA, PRC → CN, ROK → KR, DPRK → KP, ROC → TW, UAE → AE (exists), USA/US/UK/GB (exist). No ISO-3 codes in general (they collide with IATA codes).
- Runtime: country names from this column are recognised everywhere a country is today (qualifier "Berlin, Deutschland", no-comma "Munich Deutschland", standalone "Brasil" → the country's gateway airports, `_place_country`).
- Collision guard: a country alternate name that is also a tier-0 place name with population ≥ 15k (e.g. a city) does not override the place; measure and report collisions.

### B. Suburbs without their own airport (generic)
- Generator: mark each place `satellite=1` when its first linked airport is not its own (own = the shared own-airport definition: display city equals the place, name contains the place name, or ≤25 km same country) AND that airport is own to a different place with higher score within 60 km. Add the column to places.csv.gz and the `places` table (versioned reseed handles migration).
- Runtime dominance: when the top-scoring candidate is a satellite and the best non-satellite candidate (one with its own airport) scores ≥ 1/10 of it, the non-satellite takes its place as the leader; the normal 3× dominance test then runs against the remaining candidates. Otherwise normal rules apply. Expected outcomes (pin as golden rows; calibrate the 1/10 on the probe sets if needed): Peoria → PIA; Glendale → None (both satellites, comparable); Aurora → DEN or None (both satellites); Arlington → DFW group (both satellites, 42×); Springfield → None; Portland → PDX unchanged.

### C. Non-town features (generic)
- Generator: from allCountries, features with feature codes in a documented allow-list — islands/archipelagos/atolls (`ISL, ISLS, ATOL, ISLT` excluded), peninsulas (`PEN`), parks and reserves (`PRK, RESN, RESW, RESF`), resorts and ski areas (`RSRT`, ski codes if present), regions/areas/coasts (`RGN, AREA, CST`), mountains and ranges (`MT, MTS, PK, VLC` — volcanoes), valleys (`VAL`), lakes (`LK`), beaches (`BCH`), archaeological/historical sites and monuments (`ANS, RUIN, HSTS, MNMT`), deserts (`DSRT`), gorges/canyons (`GRGE, CNYN`) — kept only when notable: alternate-name count ≥ N (calibrate; start at 10; report the count/size trade-off) and an airport within 250 km.
- New committed file `backend/app/db/data/features.csv.gz` (≤ 3 MB): `geonameid, name, ascii, country_code, admin1, feature_code, notability, lat, lng, airports, alt_names`. Airports linked like places but by distance only, same-country first (large/medium within 250 km, ≤3, ranked by (foreign, type, distance)); islands also take airports located on the island when determinable (airport within the island's reach and not farther than the nearest mainland alternative — keep it simple and documented).
- Loader: new `features` table + `feature_names` (tier 0 name/ascii, tier 1 alternates), versioned with the rest.
- Resolution: after curated hints/exonyms and before giving up, and also as competing candidates: a feature beats town candidates when every town candidate has population < 15k (or none exist) and the feature's notability ≥ calibrated threshold; a town with population ≥ 15k beats a feature of the same name (Banff town vs park both map to YYC — fine either way). Hints still override everything. `_place_country` uses the feature's country.
- Autocomplete: features may contribute suggestions (their airports) below town matches, same no-padding rules.

### D. Measurement (all mandatory, before → after)
Run every probe set: 660 (scratchpad/fr), 432 (rr), blind-824 (blind), lc-408 + lc-nc-160 (lc), and the golden set. Constraint: **no set gains a WRONG**; golden stays green. Report WRONG/NONE per set and per item (A/B/C). Then the controller commissions a fresh blind probe.

### E. Docs
Place-and-Airport-Data.md (sources incl. allCountries, features, satellite rule, country names), data README (regeneration command now takes allCountries), CLAUDE.md one line, Changelog entry.

## Global Constraints
No new deps; stdlib generator; deterministic output; committed data total ≤ 9 MB; no network at runtime or in tests; `lookup_city_iata` p99 < 3 ms; backend pytest + ruff; frontend untouched unless autocomplete tests need it.

---
### Task 1: Generator + data (countries names, satellite flag, features) + loader (+tests)
### Task 2: Runtime resolution (A, B, C) + autocomplete + measurement + docs (+tests)
