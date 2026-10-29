# Airport and place data

The airport/place data the backend uses. It is generated offline by
`backend/scripts/build_place_data.py` and committed. Nothing downloads or
regenerates it at runtime.

| File | Contents |
|---|---|
| `airports.csv` | One row per airport: `iata, icao, name, city, country, country_code, region, type_rank, scheduled, lat, lng`. Every OurAirports large/medium/small airport with scheduled service and an IATA code (`scheduled=1`), plus every code in the curated list (`backend/app/db/seed_airports.py`). Curated codes that OurAirports lacks or lists as unscheduled are kept with `scheduled=0`. |
| `places.csv.gz` | One row per GeoNames populated place with ≥ 1,000 people, except the feature codes PPLX, PPLH, PPLQ, PPLW and PPLCH: `geonameid, name, country_code, admin1, population, score, lat, lng, airports, alt_names`. `airports` holds up to 3 space-separated IATA codes, ranked. `alt_names` is a `\|`-joined list of folded Latin-script alternate names, kept only for places with ≥ 15,000 people. |
| `admin1.csv` | GeoNames first-level administrative divisions: `code` (e.g. `US.OR`, `GB.ENG`), `name`, `folded_name`. |

## Sources and licences

- **OurAirports** (`airports.csv`, `countries.csv`), https://ourairports.com/data/, is in the **public domain**. OurAirports is authoritative for airport codes, names, coordinates, regions and scheduled status.
- **GeoNames** (`cities1000.txt`, `admin1CodesASCII.txt`), https://www.geonames.org/, is licensed **CC BY 4.0**. Attribution:

  > Contains data from GeoNames (geonames.org), CC BY 4.0

Snapshot date of both sources: **2026-10-29**.

## How the data is derived

- **Display city.** For curated airports, the curated city. Otherwise, the highest-scoring place that links the airport and lies within 80 km of it. Otherwise, the OurAirports municipality, cleaned: the text before the first `(` or `,`, and `A` for `A/B`. The municipality on its own is never trusted, because it gives the airport's physical location ("Ferno (VA)" for MXP), not the city it serves.
- **Country name.** The OurAirports country name. For countries that appear in the curated list, the curated spelling is used instead ("United States", "United Kingdom").
- **Score.** `population × (alternate_name_count + 1)² × (3 if PPLC)`, where the alternate-name count is the raw count. It ranks namesakes so that the famous one wins: Portland US-OR ≫ Portland US-ME, and Interlaken CH ≫ Interlaken US.
- **Linking (place → airports).** Only scheduled airports are linked. Each airport type has a reach:
  - large: 80 km, or 100 km when the place has ≥ 1M people and no large airport within 50 km;
  - medium: 50 km;
  - small: 30 km.

  Linked airports are ranked by (type, distance), and up to 3 are kept. If no airport is in reach, the nearest large or medium airports within 150 km are used (up to 2).
- **Folding.** Names are folded with `app.core.places.fold_place`, the same function the runtime uses: accents are stripped, ß→ss, ø→o and so on, text is lower-cased, `.` and `-` become spaces, and whitespace is collapsed.

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
2. Commit the three files. The total must stay ≤ 8 MB. The 2026-10-29 snapshot is about 5.5 MB.

## Conflict report (2026-10-29 snapshot)

The script prints its summary and a conflict report to stdout. The report is not committed. For this snapshot:

- **Totals.** 4,028 airports (4,010 scheduled), 162,014 places (10,415 with no airport within reach), 158,313 alt-name pairs and 3,865 admin1 rows.
- **Curated codes missing from OurAirports (7).**
  - ETH: Eilat is replaced by ETM Ramon.
  - FRU: OurAirports lists Bishkek Manas as BSZ.
  - KIV: Chișinău is RMO in OurAirports.
  - NIY: Freetown Lungi is FNA.
  - PBI: OurAirports lists KPBI with IATA DJT.
  - REP: Siem Reap is now SAI.
  - TIP: Tripoli is MJI in OurAirports.

  These codes are kept with `scheduled=0` and the curated data.
- **Curated codes not scheduled in OurAirports (11).**
  - Closed or replaced: PNH (now KTI), DKR (now DSS), ULN (now UBN) and RAJ (now HSR).
  - No service: the Ukrainian airports KBP, IEV, LWO and ODS.
  - Wrong curated codes that point at unrelated airports: ANT (an Austrian heliport; Réunion is RUN), CMR (Colmar; Yaoundé is NSI) and KHO (a South African strip; Maseru is MSU).
- **Curated vs OurAirports country mismatches (5).** ANT, CMR and KHO are wrong codes, as above. BSL is the EuroAirport, which is in France and serves Basel. MYK is May Creek, Alaska, in OurAirports; Mykonos is JMK.
- **Curated coordinates more than 25 km from OurAirports (8).** ANT, CMR, KHO and MYK are wrong codes. CTU and TFU have their curated names and coordinates swapped. DKR's curated coordinates are those of the new airport. INC's curated coordinates are 38 km off.
- **Large airports whose display city fell back to the municipality (2).** DQM (Duqm) and MFU (Mfuwe), which are correct.
