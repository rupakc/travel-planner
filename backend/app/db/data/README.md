# Airport and place data

The airport/place data the backend uses. It is generated offline by
`backend/scripts/build_place_data.py` and committed. Nothing downloads or
regenerates it at runtime.

| File | Contents |
|---|---|
| `airports.csv` | One row per airport: `iata, icao, name, city, country, country_code, region, type_rank, scheduled, lat, lng`. Every OurAirports large/medium/small airport with scheduled service and an IATA code (`scheduled=1`), plus every code in the curated list (`backend/app/db/seed_airports.py`). Curated codes that OurAirports lacks or lists as unscheduled are kept with `scheduled=0`. |
| `places.csv.gz` | One row per GeoNames populated place with ≥ 1,000 people, except the feature codes PPLX, PPLH, PPLQ, PPLW and PPLCH: `geonameid, name, country_code, admin1, population, score, lat, lng, airports, alt_names, ascii`. `airports` holds up to 3 space-separated IATA codes, ranked. `alt_names` is a `\|`-joined list of folded Latin-script alternate names, kept only for places with ≥ 15,000 people. `ascii` is GeoNames' ASCII spelling of the name, present for every place; the app loads it as a primary name together with `name`, so it is not repeated in `alt_names`. `satellite` is 1 for a place that flies from another place's airport (see below). |
| `admin1.csv` | GeoNames first-level administrative divisions: `code` (e.g. `US.OR`, `GB.ENG`), `name`, `folded_name`. |
| `countries.csv` | Every OurAirports country, `code, name, names`, also those with no scheduled airport (Andorra, Liechtenstein): the resolver's country names. `names` is a `\|`-joined list of folded native and other-language names from GeoNames ("deutschland", "brasil", "nippon", "suomi", "ellada"). Written by the generator. |
| `features.csv.gz` | Notable GeoNames features that are not towns (islands, parks, resorts, regions, mountains, valleys, lakes, sites…): `geonameid, name, ascii, country_code, admin1, feature_code, notability, lat, lng, airports, alt_names`, `airports` up to 3 ranked IATA codes, `alt_names` as in `places.csv.gz`. |
| `hints.json` | Hand-curated, not generated: tourist islands, destinations and regions with their airports, exonyms (GeoNames place ids), city and country aliases (`qualifier_country_aliases` holds KSA, PRC, ROK and ROC, which are also airport codes and so name a country only as a qualifier), and the names whose St/Saint variants must not borrow a hint. Keys are folded names; a test checks every code is scheduled and every exonym id exists. |

## Sources and licences

- **OurAirports** (`airports.csv`, and the `code` / `name` columns of `countries.csv`), https://ourairports.com/data/, is in the **public domain**. OurAirports is authoritative for airport codes, names, coordinates, regions and scheduled status.
- **GeoNames** (`cities1000.txt`, `admin1CodesASCII.txt`, `allCountries.zip`; used in `places.csv.gz`, `features.csv.gz`, `admin1.csv` and the `names` / `qualifier_names` columns of `countries.csv`), https://www.geonames.org/, is licensed **CC BY 4.0**. Attribution:

  > Contains data from GeoNames (geonames.org), CC BY 4.0

  Licence: https://creativecommons.org/licenses/by/4.0/. **The GeoNames data here is modified**: places are filtered (feature codes, alternate names), names are folded, scored and linked to airports, some are used as airport display cities, and places carry a derived suburb (`satellite`) flag; country names are extracted from the political entities, filtered and split into standalone and qualifier-only names; non-town features and districts are filtered by notability, linked to airports (districts to their parent city's) and their alternate names filtered. GeoNames does not endorse these changes.

Snapshot date: **2026-10-29** for OurAirports, `cities1000` and `admin1CodesASCII`; **2026-10-30** for `allCountries`.

## How the data is derived

- **Display city.** For curated airports, the curated city. Otherwise the first of these rules that applies, using only places in the airport's own country (never empty):
  1. the highest-scoring place within 40 km whose folded name occurs as whole words in the folded airport name ("Verona" for "Verona Villafranca Airport"); names made only of generic words such as "International" or "San" never match, nor a name followed by "County", "Parish", "Province", "District" or "Region" (MSN "Dane County Regional" is Madison's);
  2. the highest-scoring place within 40 km whose first in-reach linked airport is this airport, unless a place within 15 km that links the airport in any position scores at least 10× more (`DISPLAY_ANY_LINK_RATIO`: HLP → Jakarta, not Bekasi);
  3. the nearest place within 15 km;
  4. the OurAirports municipality, cleaned: the text before the first `(` or `,`, and `A` for `A/B`;
  5. the airport name without "Airport", "International", "Aerodrome" and "Airfield".

  A place name with letters beyond Latin Extended-A (scholarly transliterations such as "Marsá Maţrūḩ") is shown in its GeoNames ASCII spelling, every display name is cut at its first comma, and a hyphenated East-Asian admin suffix (-si, -shi, -gun, -ku, -cho, -machi, -mura) is removed ("Cheongju-si" → "Cheongju"). The municipality on its own is never trusted first, because it gives the airport's physical location ("Ferno (VA)" for MXP), not the city it serves.
- **Country name.** The OurAirports country name. For countries that appear in the curated list, the curated spelling is used instead ("United States", "United Kingdom").
- **Score.** `population × (alternate_name_count + 1)² × (3 if PPLC)`, where the alternate-name count is the raw count. It ranks namesakes so that the famous one wins: Portland US-OR ≫ Portland US-ME, and Interlaken CH ≫ Interlaken US.
- **Linking (place → airports).** Only scheduled airports are linked. Airports named as an air base, air force base/station or air station (unless curated or also named an "airport") are linked only when no civil airport is in reach of the place (Bareilly → BEK); air *bases* ("Air Base", "Air Force Base", "AFB") never link when any civil airport is within fallback range (Cape May → ACY, not Dover AFB). Each airport type has a reach:
  - large: 80 km, or 100 km when the place has ≥ 1M people (Kyoto → KIX at 81 km);
  - medium: 50 km;
  - small: 30 km.

  Airports in reach are ranked by (foreign, not named for the place, small, not curated — counted only among airports named for the place —, effective distance), and up to 3 are kept. The effective distance is the distance in km, × 0.3 for a large airport (a large airport leads a medium one unless the medium is over 3.3× nearer: Arvada → DEN, Providence → PVD) and × 0.8 again for another place's curated large airport (Makkah → JED). An airport is *named for* the place when its display city is the place or its name contains the place name (Treviso → TSF; Basel → BSL in France). An airport is the place's *own* (`app.core.places.is_own_airport`, shared with the runtime) when it is named for it or lies in the same country within 25 km; an own airport across a border is not foreign. Among two neighbours not named for the place whose effective distances are within 1.25× of each other, the one in the place's admin1 goes first (an airport's admin1 is that of the nearest same-country place within 50 km). `NEVER_LINK` airports (ECN, reachable only via Turkey) are never linked.

  When the only airports in reach are foreign and not the place's own, large or medium airports in the place's own country within 200 km come first (≤ 2), then the foreign ones (Kingston, Ontario → YOW; Hof → ERF, NUE). If no airport is in reach, large or medium airports within 200 km (own country) or 150 km (foreign) are used, ranked by (foreign, distance with a large airport at × 0.75), up to 2.
- **Folding.** Names are folded with `app.core.places.fold_place`, the same function the runtime uses: accents are stripped, ß→ss, ø→o and so on, text is lower-cased, `.`, `·` and every dash become spaces, apostrophe and quote variants (`'` `’` `‘` `ʼ` `ʻ` `` ` `` `ʹ` `“` `”`) and invisible format characters (ZWNJ, LRM) are dropped, ə/ɛ→e, ħ→h, ƶ→z, and whitespace is collapsed. Alternate names are kept only when made of Latin letters, spaces, apostrophes, dashes and dots (no digits, brackets or symbols).

- **Satellite places.** A place is a satellite when its first linked airport is not *named* for it (`core.places.is_named_airport`: the final display city is the place, or the airport name contains it; never distance alone) and that airport is named for a place scoring at least 10× more within 60 km (`SATELLITE_OWNER_RATIO`, `SATELLITE_KM`): Peoria, Arizona flies from Phoenix's PHX; Peoria, Illinois has PIA. `satellite=2` marks a deep suburb, whose owner scores ≥ 100× more (`SATELLITE_DEEP_RATIO`: Pontevedra, Buenos Aires and EZE), `1` an ordinary satellite (Pontevedra, Spain and Santiago's SCQ). A comparable neighbour does not make a town a suburb (Concord, New Hampshire and Manchester's MHT). 83,021 of the 162,014 places are satellites (75,372 deep), most of them small towns near a city.
- **Country names** (`countries.csv` `names`). From the allCountries political entities (feature codes PCLI, PCLD, PCLF, PCLS, PCL, PCLIX, TERR), per country code: the name, the ASCII name and the Latin-script alternates (≤ 40 characters, at least 5 letters when folded and with a vowel — shorter ones are mostly noise such as "pain" for Spain or "kili" for Chile, and "Eire" is a curated alias —, no URL, no all-caps code: ISO-3 codes would collide with airport codes, so "KSA" or "PRC" are curated aliases instead). Names the resolver already knows (OurAirports and curated country names, aliases) are not repeated. A name two countries carry ("Congo", "Niger" spellings, "San Martin") is dropped, and so is the own name of a place with ≥ 15,000 people ("Brasilia", "Columbia", "Granada", "Nederland" in Texas): both are listed in the conflict report. A name that is the own name of a smaller place (any population) goes to `qualifier_names`: it names the country only as a qualifier ("Asmara, Eretria"), and typed alone stays the town (Eretria, Greece; Coria, Spain; Grenade, Granada's French name). Countries' own native names, verified against GeoNames, are curated aliases in `hints.json` instead and win standalone over any town ("Nederland", "Palestine", "Aland", "Deutschland", "España", "Nippon", "Suomi", "Hellas", "Sverige", "Misr", "Maroc"…).
- **Features** (`features.csv.gz`). allCountries rows with these feature codes: islands, archipelagos and atolls (ISL, ISLS, ATOL; not ISLT), peninsulas (PEN), parks and reserves (PRK, RESN, RESW, RESF), resorts (RSRT; GeoNames has no ski-area code), regions, areas and coasts (RGN, AREA, CST), mountains, ranges, peaks and volcanoes (MT, MTS, PK, VLC), valleys (VAL), lakes (LK), beaches (BCH), ancient and historical sites, ruins and monuments (ANS, RUIN, HSTS, MNMT), deserts (DSRT), gorges and canyons (GRGE, CNYN), glaciers (GLCR), capes (CAPE), fjords (FJD) and caves (CAVE). A feature is kept when it is **notable** (its GeoNames alternate-name count, `notability`, is at least 10; at least 5 for parks, reserves, resorts, glaciers, capes, fjords, caves, islands and deserts, which are rarely translated) and has an airport. An island or desert admitted only by the lower threshold (5–9 alternate names) is dropped when its own or short name is another allCountries row's own name (3,771 dropped: "Sugarloaf" Island, California among the Sugarloaf mountains):
  - **airports on an island** come first, nearest first: scheduled airports whose nearest island point among islands notable at 10 is this island, within 50 km (Sylt → GWT, Mafia Island → MFA). GeoNames has points, not outlines, so a big island whose point is far from its coast gets none this way; with every island's point (not only notable ones), a nearby islet claimed the airport instead (Paros, Naxos);
  - then scheduled large and medium airports within 250 km, ranked by (foreign, effective distance): same country first, a large airport at half its distance (`FEATURE_LARGE_FACTOR` = 0.5; tuned on Lake Tahoe → RNO before Truckee, Matterhorn → GVA, ZRH, Florida Keys → EYW before MIA, Rügen → Heringsdorf, Rostock before BER);
  - at most 3; air bases and `NEVER_LINK` airports never link; a feature with none is dropped.

  An alternate name that is the own name of another allCountries row (a populated place, a division or a listed feature) is dropped, in a second pass over the file: "Blue Mountains" is an alternate of Utah's Abajo Mountains and the name of the Australian range, "El Chaltén" one of Cerro Fitzroy and the name of the town, "Smoky Mountains" one of Nevada's Toquima Range. 17,565 alternates go this way, some useful ones with them ("Lake Garda", "Sardegna"; both are now curated hints).

  **Famous districts** are kept too (`feature_code` PPLX or an administrative seat): sections of places with ≥ 10 alternate names or ≥ 10,000 people (`population` column), and administrative seats GeoNames gives no population with ≥ 10 alternate names (Ealing). They take the airports of the highest-scoring place within 50 km (Manly, Frankston, Shinjuku → their city's airports). A district's own name is **contested** (the `contested` column, `|`-joined folded names) when other sections carry it: namesakes are other PPLX rows (for a seat also other seats, PPLA…PPLA5 and PPLC) more than 50 km away, those within 20 km of each other counted once; with `k` namesakes whose best alternate-name count is `b` and the district's own `t`, the name is kept when `k = 0`, or `k ≤ 3` and `t > b`, or `k ≤ 8`, `t ≥ 10` and `t ≥ 2b`, or `t ≥ 30` and `t ≥ 2b` (calibrated in the final blind check). The loader stores contested names as tier 2; a bare query that only they match gives `None` ("Centar", "Chinatown", "Downtown", "Altstadt"), while Kreuzberg, Trastevere, Brixton and La Jolla keep theirs. 1,003 names are contested. 7,306 of the 31,995 features are districts.

  The loader also stores each name without a generic part as a primary name ("Kakadu National Park" → "kakadu", "Mount Everest" → "everest", "Ko Phi Phi" → "phi phi"; `core.places.feature_short_names`).

  **Notability threshold calibration** (2026-10-30 snapshot):

  | Threshold | Features kept | `features.csv.gz` | Examples first kept at this threshold (dropped at the next one up) |
  |---|---|---|---|
  | 5 | 83,141 | 3.60 MB (over the 3 MB budget) | Patagonia (8; would link Comodoro Rivadavia), Grand Canyon (a valley, 8), Amalfi Coast (8), Yosemite Valley (7), Lake Bled (7), Atacama Desert (6), Sahara (5; would link Sebha), Hwange National Park |
  | 10 | 14,186 | 0.88 MB | Bohol (18), Bora Bora (18), Serengeti National Park (14), Knossos, Val de Loire, Lake Petén Itzá, Nyiragongo |
  | 20 | 1,343 | 0.17 MB | Mount Everest (186), Java (85), Kakadu National Park (58), Matterhorn (51), Arches National Park (43), Petra (40), Gozo (33), Sylt (23), Angkor Wat (22) |

  At 10, most of what is dropped below it is obscure (thousands of unnamed-looking mountains and valleys), and the famous names below 10 are mostly vast regions whose single point gives a wrong gateway; the curated hints cover the ones travellers type (Grand Canyon, Amalfi Coast, Yosemite).

  **Used:** 10, and 5 for parks, reserves, resorts, glaciers, capes, fjords, caves, islands and deserts (famous ones have few translations: Doñana, Postojna Cave, Perito Moreno Glacier, Amrum, Île d'Oléron, the Thar and Namib deserts), plus the districts: 31,995 features, 1.70 MB.

## Regenerating

Download the sources into a directory of their own, as data only:

- OurAirports `airports.csv`, `regions.csv` and `countries.csv`;
- GeoNames `cities1000.zip` (unzipped), `admin1CodesASCII.txt` and `allCountries.zip` (423 MB; the script streams it, so it need not be unzipped).

Then, from the repository root, run:

```bash
python3 -I backend/scripts/build_place_data.py \
    --ourairports /path/to/ourairports-src \
    --geonames-cities /path/to/geonames-src/extracted/cities1000.txt \
    --geonames-admin1 /path/to/geonames-src/admin1CodesASCII.txt \
    --geonames-all /path/to/geonames-src/allCountries.zip \
    --out backend/app/db/data > conflicts.txt
```

`-I` runs Python isolated, so nothing is imported from the current or data directories. The script adds `backend/` to its own path to import `fold_place` and the curated list. It uses only the standard library, takes about a minute (most of it two streaming passes over allCountries), and produces byte-identical output for the same inputs: rows are sorted, and the gzip mtime is 0. Then:

1. Run `pytest tests/test_build_place_data.py` from `backend/` to spot-check the data.
2. Commit the five files. The total must stay ≤ 9 MB (`features.csv.gz` ≤ 3 MB). The current snapshot is about 7.2 MB.

## Conflict report (2026-10-29 / 2026-10-30 snapshot)

The script prints its summary and a conflict report to stdout. The report is not committed. For this snapshot:

- **Totals.** 4,014 airports (4,010 scheduled), 162,014 places (6,424 with no airport), 151,908 alt-name pairs, 3,865 admin1 rows, 83,021 satellite places (75,372 deep), 18,071 country names (99 qualifier-only) and 31,995 features including 7,306 districts (3,771 weak islands and deserts dropped for a shared name).
- **Country names dropped.** 21 that two countries share (Congo/Kongo spellings, Niger/Nigeria spellings, "San Martin" for MF and SX, "Soudan" for ML and SD…) and 46 that are the own name of a place with ≥ 15,000 people ("Brasilia", "Columbia", "Formosa", "Granada", "Gold Coast", "Marrakesh", "Nederland", "Norfolk"…): the place keeps the name, except the three that are the country's own name ("Nederland", "Palestine", "Aland"), curated back as aliases.
- **Curated list corrections.** Stale curated codes were replaced with the scheduled OurAirports codes, keeping the curated city: FRU→BSZ, PBI→DJT, KIV→RMO, TIP→MJI, PNH→KTI, REP→SAI, ULN→UBN, DKR→DSS, NIY→FNA, MYK→JMK, ANT→RUN, CMR→NSI, KHO→MSU, ETH→ETM and RAJ→HSR. The swapped CTU/TFU entries and INC's coordinates were also fixed.
- **Curated codes missing from OurAirports.** None.
- **Curated codes not scheduled in OurAirports (4).** KBP, IEV, LWO and ODS. Ukrainian airspace is closed. They are kept with `scheduled=0` so they return when service resumes.
- **Curated vs OurAirports country mismatches (1).** BSL. The EuroAirport is on French soil and serves Basel; this is correct.
- **Curated coordinates more than 25 km from OurAirports.** None.
- **Large airports whose display city fell back to the municipality (7).** DQM Duqm, MFU Mfuwe, OCS Corisco Island, RMF Marsa Alam, ROP Rota Island, RSI Hanak and SCR Malung-Sälen. All are acceptable: no GeoNames place of ≥ 1,000 people near them names or primarily uses them.
- **Curated display city vs computed city (109).** Informational only; the curated city wins. 45 are airport-name matches, which are often the airport's own town rather than the city it serves (LTN → Luton, NRT → Narita, ICN → Incheon) or a person's name in the airport name (BGY → Caravaggio). 56 are first-link picks, which can be a suburb for a metropolitan airport (CDG → Saint-Denis, SVO → Mytishchi). Curating the served city stays necessary for major airports; the curated list includes served-city overrides for large airports whose computed city was a nearby town (WSI Sydney, AVV Melbourne, THR Tehran, NLU Mexico City, DXN Noida, DJE Djerba, GSM Qeshm, LXA Lhasa, RKZ Shigatse, YNT Yantai, UIH Qui Nhon, CXI Kiritimati, YIE Arxan, NUM Neom) and, after the final review, for airports whose computed city was a suburb or a neighbouring town (BJC Broomfield, BWK Bol, CLD Carlsbad, WUX Wuxi, SPX Giza, CCE Cairo, NAT Natal, PTP Pointe-à-Pitre, HLA Johannesburg).
