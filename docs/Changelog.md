# Changelog

Changes since the project started on 2026-05-17. From 2026-08-30 on, every change went through a pull request; dates are merge dates (UTC). A "(#N)" inside a PR title refers to a backlog item, not a PR.

---

## Unreleased: documentation and housekeeping

- Developer docs consolidated into one set of pages (this site and the GitHub wiki share them), with new pages for trip-planning features, place and airport data, testing and CI, and this changelog.
- Added an MIT `LICENSE` file.
- App footer credits the place data: "Place data © GeoNames (CC BY 4.0) · Airport data: OurAirports".
- `docker-compose.yml` now builds the backend from the repo root, so `docker compose up --build` works.
- `get_optional_user` treats a deactivated user's token as anonymous.
- Removed the unused `knowledge_planner.py` and the unused `tools` / `max_turns` agent frontmatter fields.
- Place resolution (GeoNames `allCountries`, CC BY 4.0): countries resolve by their native and other-language names ("Deutschland", "Brasil", "Nippon", "Suomi"; KSA, PRC, ROK and ROC, and names that are also a town's, as qualifiers only); a suburb no longer beats a namesake with its own named airport ("Peoria" → PIA, "Pontevedra" → Spain); 26,329 notable islands, parks, glaciers, caves, mountains, regions, sites and famous districts resolve to their airports ("Kakadu" → DRW, "Grand Teton" → JAC, "Ealing" → LHR). See [Place and Airport Data](Place-and-Airport-Data.md).

---

## Pull requests

### Place and airport data

| PR | Merged | Title |
|---|---|---|
| #19 | 2026-10-30 | feat(places): comprehensive airport & place data (OurAirports + GeoNames) |
| #18 | 2026-10-29 | fix(places): states narrow airports, accents/aliases, fare calendar matches cards |
| #17 | 2026-10-29 | fix(places): typed cities get airport codes; ISO country codes in lookups |

Typed places now resolve to airports through committed OurAirports and GeoNames data with a versioned seed, curated hints and a golden test set. See [Place and Airport Data](Place-and-Airport-Data.md).

### Itinerary

| PR | Merged | Title |
|---|---|---|
| #16 | 2026-10-29 | feat(plan): picked itinerary slots keep their scheduled times |
| #14 | 2026-10-29 | Timed itinerary (#18) |
| #11 | 2026-10-29 | Itinerary polish: accessibility + re-check edited plan |
| #8 | 2026-10-29 | Drag-and-drop itinerary editing (#12) |

### Flights, budget and comparison

| PR | Merged | Title |
|---|---|---|
| #15 | 2026-10-29 | Fare calendar (#9) |
| #13 | 2026-10-29 | Budget planner (#16) |
| #9 | 2026-10-29 | Side-by-side trip comparison (#1) |
| #7 | 2026-10-29 | Best-value package card on Results page (#26) |

### Trust and hardening

| PR | Merged | Title |
|---|---|---|
| #12 | 2026-10-29 | Backend hardening: exact reference lookups + rate limiting |
| #10 | 2026-10-29 | Source verification labels on Results (#28) |
| #4 | 2026-10-28 | fix(ci): unblock security audit — replace python-jose with PyJWT, bump npm deps |

### Results, plans and onboarding

| PR | Merged | Title |
|---|---|---|
| #6 | 2026-10-28 | feat: Free Walking Tours section (new crawler + specialist agent) |
| #5 | 2026-10-28 | feat: first-run onboarding tour on the Search page |
| #3 | 2026-10-28 | feat: export a plan to calendar (.ics) and print/PDF |
| #2 | 2026-10-28 | feat: recent searches and plan cost breakdown |

### Operations

| PR | Merged | Title |
|---|---|---|
| #1 | 2026-08-30 | chore: decommission GCP deploy pipeline |

Production on Cloud Run was shut down and the GCP project deleted; `deploy.yml` became manual-only. See [Deployment](Deployment.md).

---

## Before pull requests (2026-05-17 to 2026-07-05)

About 100 commits went straight to `main`. Highlights, from the git history:

- **2026-05-17 to 05-21: first version and production.** The initial commit brought the multi-agent planner: FastAPI backend, three-phase orchestrator with static-first visa, SIM, tips and transport, SSE streaming through a Web Worker, React frontend, JWT login with admin-created accounts, saved plans and preferences. The same days set up GCP Cloud Run deployment with Terraform and GitHub Actions, CI with ruff, bandit, pip-audit and Trivy, the docs site with its custom homepage, deterministic activity-link resolution (Serper as a second tier) in place of model-invented URLs, and a chat agent with session memory and routing.
- **2026-05-21 to 05-31: more agents and views.** Places to See (Serper data plus Claude). The weather section with traveller profiles and accessibility needs. Chat itinerary overhaul (multi-city route ordering, specialist routing). Destination discovery (*Surprise me*), the Travel Ease confidence score, the emergency card, the packing list, the flight price advisor and the Timeline view. A large batch of extra agents added on 05-30 was reverted the next day.
- **2026-07-04 to 07-05: multi-city, personalization and resilience.** Trip Remix presets; the itinerary stress test (health check); the Taste Graph; the layover optimizer; multi-city routing (up to 4 cities); the What's On events layer; public share links with a full-page PNG trip card; a more natural chat that answers from knowledge, with specialists only as a fallback. Fixes for API bursts and oversized multi-city outputs (global concurrency cap, compact retry), retries for severed SSE streams, responsive database operations under load, and backups that no longer lose WAL-only rows.
