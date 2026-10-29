# Airport and place data

The airport/place data the backend uses. It is generated offline by
`backend/scripts/build_place_data.py` and committed. Nothing downloads or
regenerates it at runtime.

| File | Contents |
|---|---|
| `airports.csv` | One row per airport: `iata, icao, name, city, country, country_code, region, type_rank, scheduled, lat, lng`. Every OurAirports large/medium/small airport with scheduled service and an IATA code (`scheduled=1`), plus every code in the curated list (`backend/app/db/seed_airports.py`). Curated codes that OurAirports lacks or lists as unscheduled are kept with `scheduled=0`. |
| `places.csv.gz` | One row per GeoNames populated place with ≥ 1,000 people, except the feature codes PPLX, PPLH, PPLQ, PPLW and PPLCH: `geonameid, name, country_code, admin1, population, score, lat, lng, airports, alt_names`. `airports` holds up to 3 space-separated IATA codes, ranked. `alt_names` is a `\|`-joined list of folded Latin-script alternate names, kept only for places with ≥ 15,000 people. The place's ASCII spelling is always included when it folds differently from the name, whatever the population. |
| `admin1.csv` | GeoNames first-level administrative divisions: `code` (e.g. `US.OR`, `GB.ENG`), `name`, `folded_name`. |

## Sources and licences

- **OurAirports** (`airports.csv`, `countries.csv`), https://ourairports.com/data/, is in the **public domain**. OurAirports is authoritative for airport codes, names, coordinates, regions and scheduled status.
- **GeoNames** (`cities1000.txt`, `admin1CodesASCII.txt`), https://www.geonames.org/, is licensed **CC BY 4.0**. Attribution:

  > Contains data from GeoNames (geonames.org), CC BY 4.0

Snapshot date of both sources: **2026-10-29**.

## How the data is derived

- **Display city.** For curated airports, the curated city. Otherwise, only places in the airport's own country count:
  1. the highest-scoring place whose first linked airport is this airport;
  2. else the highest-scoring place within 30 km that links it;
  3. else the OurAirports municipality, cleaned: the text before the first `(` or `,`, and `A` for `A/B`. The municipality on its own is never trusted, because it gives the airport's physical location ("Ferno (VA)" for MXP), not the city it serves.
- **Country name.** The OurAirports country name. For countries that appear in the curated list, the curated spelling is used instead ("United States", "United Kingdom").
- **Score.** `population × (alternate_name_count + 1)² × (3 if PPLC)`, where the alternate-name count is the raw count. It ranks namesakes so that the famous one wins: Portland US-OR ≫ Portland US-ME, and Interlaken CH ≫ Interlaken US.
- **Linking (place → airports).** Only scheduled airports are linked. Each airport type has a reach:
  - large: 80 km, or 100 km when the place has ≥ 1M people and no large airport within 50 km;
  - medium: 50 km;
  - small: 30 km.

  Linked airports are ranked by (type, distance), and up to 3 are kept. If no airport is in reach, the place's own country's large or medium airports within 200 km are used (up to 2, by type then distance). If there are none, the nearest large or medium airports in any country within 150 km are used (up to 2).
- **Folding.** Names are folded with `app.core.places.fold_place`, the same function the runtime uses: accents are stripped, ß→ss, ø→o and so on, text is lower-cased, `.` and `-` become spaces, apostrophe variants (`'` `’` `‘` `ʼ` `ʻ` `` ` ``) are dropped, and whitespace is collapsed.

## Regenerating

Download the sources into a directory of their own, as data only:

- OurAirports `airports.csv`, `regions.csv` and `countries.csv`;
- GeoNames `cities1000.zip` (unzipped) and `admin1CodesASCII.txt`.

Then, from the repository root, run:

```bash
python3 -I backend/scripts/build_place_data.py \
    --ourairports /path/to/ourairports-src \
    --geonames-cities /path/to/geonames-src/extracted/cities1000.txt \
    --geonames-admin1 /path/to/geonames-src/admin1CodesASCII.txt \
    --out backend/app/db/data > conflicts.txt
```

`-I` runs Python isolated, so nothing is imported from the current or data directories. The script adds `backend/` to its own path to import `fold_place` and the curated list. It uses only the standard library, takes about 5 seconds, and produces byte-identical output for the same inputs: rows are sorted, and the gzip mtime is 0. Then:

1. Run `pytest tests/test_build_place_data.py` from `backend/` to spot-check the data.
2. Commit the three files. The total must stay ≤ 8 MB. The 2026-10-29 snapshot is about 5.2 MB.

## Conflict report (2026-10-29 snapshot)

The script prints its summary and a conflict report to stdout. The report is not committed. For this snapshot:

- **Totals.** 4,014 airports (4,010 scheduled), 162,014 places (6,424 with no airport), 155,243 alt-name pairs and 3,865 admin1 rows.
- **Curated list corrections.** Stale curated codes were replaced with the scheduled OurAirports codes, keeping the curated city: FRU→BSZ, PBI→DJT, KIV→RMO, TIP→MJI, PNH→KTI, REP→SAI, ULN→UBN, DKR→DSS, NIY→FNA, MYK→JMK, ANT→RUN, CMR→NSI, KHO→MSU, ETH→ETM and RAJ→HSR. The swapped CTU/TFU entries and INC's coordinates were also fixed.
- **Curated codes missing from OurAirports.** None.
- **Curated codes not scheduled in OurAirports (4).** KBP, IEV, LWO and ODS. Ukrainian airspace is closed. They are kept with `scheduled=0` so they return when service resumes.
- **Curated vs OurAirports country mismatches (1).** BSL. The EuroAirport is on French soil and serves Basel; this is correct.
- **Curated coordinates more than 25 km from OurAirports.** None.
- **Large airports whose display city fell back to the municipality (1).** ROP, "Rota Island" (MP). This is correct: GeoNames has no Rota town with ≥ 1,000 people.
- **Curated display city vs computed city.** Informational only; the curated city wins. Most differences are spelling ("Köln" vs "Cologne") or a neighbouring city.
