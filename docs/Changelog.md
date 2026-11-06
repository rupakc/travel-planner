# Changelog

Changes since the project started on 2026-05-17. From 2026-08-30 on, every change went through a pull request; dates are merge dates (UTC). A "(#N)" inside a PR title refers to a backlog item, not a PR.

---

## Unreleased: Gemini on Vertex AI

- **Gemini replaces Claude by default.** Every model call now goes through one provider seam, `backend/app/core/llm.py`. `LLM_PROVIDER=gemini` (default) uses Gemini on Vertex AI with Application Default Credentials (no API key; `GCP_PROJECT`, `GCP_LOCATION` default `global`): **Gemini 3.5 Flash-Lite** (`gemini-3.5-flash-lite`, thinking `minimal`, JSON mode) for every specialist agent, packing, pricing advisor, itinerary, stress test, link import, discovery, layover, chat itinerary and chat routing/extraction; **Gemini 3.8 Flash** (`gemini-3.8-flash`, thinking `low`) for chat answers, streamed token by token, and the planning narrative. `LLM_PROVIDER=anthropic` keeps Claude (Haiku 4.5 / Sonnet 4.6) for local development and rollback. Agent prompts are unchanged. New settings: `LLM_PROVIDER`, `GCP_PROJECT`, `GCP_LOCATION`, `GEMINI_MODEL_AGENT`, `GEMINI_MODEL_CHAT`, `GEMINI_THINKING_AGENT`, `GEMINI_THINKING_CHAT` (see [Configuration](Configuration.md#llm)).
- **Monthly AI spend cap.** When the Vertex AI spend-cap budget trips, users see "AI limit reached for this month — try again on the 1st." in search sections (`error_code: "ai_limit"`, one banner on the Results page), as a chat reply, and as `503` from `/api/discover`, `/api/import/extract` and `/api/nearby`, instead of failures; further calls are skipped for 5 minutes. `/health/agents` reports `llm_provider` and `llm: "spend-cap"`.
- **Token usage per call.** Every model call logs an `llm_usage` line (label, model, input/output/thinking tokens, latency; never content).
- **LLM eval harness.** `backend/scripts/llm_eval.py` runs six saved searches on a chosen provider/model and compares two runs per section (validity, item counts, required fields, verification levels, cost) in a Markdown report. Manual only, never in CI.
- Dependencies: `google-genai` 2.34.0 added; the unused `claude-agent-sdk` and `python-dotenv` removed (pydantic-settings still brings python-dotenv for `.env`). Docker Compose passes `LLM_PROVIDER`, `GCP_PROJECT` and `GCP_LOCATION`.

## Unreleased: fixes from the Android end-to-end run

- **Check now is live.** `POST /api/fare-watches/{id}/check` and `POST /api/price-watches/{id}/check` no longer answer from the 30-minute result cache, so pressing Check now can show a new price; the fresh answer refreshes the cache. Their SerpAPI calls are reserved from the daily budget and the owner's share as before (a Check now right after a search is no longer free). Scheduled checks and a new watch's baseline still reuse cached prices (`core/cache.fresh_reads`).
- **Fare alerts name cities.** A fare watch whose labels are bare airport codes (as the Android app saves them, "JFK" → "LIS") now reads "New York → Lisbon" in alert titles, emails and pushes, using the local airport data; an unknown code stays as it is.
- **Chat plan commands know the items.** The plan-command model now sees a compact, bounded line per flight, hotel and activity (name, price, rating…, with a ref) instead of only counts, so "add the cheapest hotel" works; the server fills the full result item in from the ref.
- **Hotel alert numbers agree.** A Google nightly rate on another taxes basis than the stay's total (e.g. $73.60 a night before taxes next to $294 for 3 nights with taxes) is replaced by the total's per-night share, and hotel drop/target alerts (in-app, email and push) now read "That's the total for 3 nights, 2 guests ($98 a night) on Google Hotels, taxes and fees included.", as on the Alerts page.

## Unreleased: backend for the Android app

- Push alerts: `POST /api/devices`, `GET /api/devices`, `DELETE /api/devices/{id}` and `POST /api/devices/unregister` (sign-out) manage the app's FCM tokens (table `devices`, at most 20 per user, tokens shown masked and never in URLs). With `FCM_SERVICE_ACCOUNT_FILE` set, every new fare- or price-watch notification is also pushed to the owner's devices over FCM HTTP v1 in the background as data-only messages (data `title`, `body`, `kind`, `notification_id`, `link`; the app builds the notification itself), only tokens FCM reports as dead are pruned, and failures never affect the alert. `/health` reports `push_configured`. `google-auth` is now a direct dependency.
- Near me: `POST /api/nearby {lat, lng, interests?, limit?}` returns the nearest known place with its region (local GeoNames data, up to 75 km) and the activities agent's things to do there, cached an hour per ~5 km cell; `404 no_place` when nothing is near. light_ai bucket.

## 2026-11-05: price watch for hotels, activities and whole trips

- Watch a hotel's stay price, an activity's per-person price or a whole saved trip's total, next to the flight fare watch. *Watch price* on hotel and activity cards, in My Plan and in chat; *Watch whole trip* on saved plans. The Alerts page gets tabs per kind and a card per kind (trip cards show a per-part breakdown).
- Honest prices: every part is observed (a live Google Hotels, Google Flights or Google result) or a labelled estimate. Estimates are frozen and never alert, a watch with no live part can't be created, activity prices come from Google results for GetYourGuide / Viator listings (those sites are never scraped) in the listing's currency, and a trip's flight is the cheapest fare on your dates.
- Alert steps: fares and hotels max($15, 5 %), activities max(1 unit, 5 %), trips max($25, 4 %) on the total, with the same anti-spam rules as fares. One scheduler loop, one daily SerpAPI budget and one active-watch limit for all kinds.
- `/api/price-watches` (CRUD, match, check, unsubscribe; `422 no_live_price` with suggestions, `422 target_currency_mismatch`), tables `price_watches` and `price_watch_history`, a `PriceSource` registry, notification kinds `hotel_*`, `activity_*`, `trip_*`, and kind-aware alert emails. See [Trip Planning Features](Trip-Planning-Features.md#price-watch-hotels-activities-and-trips).

## Unreleased: plan a trip from a link or screenshot

- New Search mode, **From a link ✨**. Paste a travel blog, YouTube or TikTok link, a caption or a message, or drop up to 4 screenshots. The places come back on a map for review (tick, rename, move between stops, place the unplaced, set nights), then a normal search plans the trip around them.
- `POST /api/import/extract`, with SSRF-safe link fetching (public addresses only on every redirect hop, pinned IP, 10 s and 2 MB limits), YouTube and TikTok oEmbed, friendly errors for Instagram, Facebook, X and Threads, and a hardened `link_import` extraction agent. Rate bucket `import`, default 20 (`RATE_LIMIT_IMPORT`).
- `TravelSearchRequest.must_include` and `import_source`. Imported places lead Activities and are always scheduled in the itinerary by a deterministic post-check (`from_link` slots, `link_extras`, `link_coverage`). Results show a coverage banner and "From your link" tags; the share page, print and calendar export credit the source.
- Chat replies to a pasted trip link with a "Plan a trip from this link" button that opens the import flow.
- Hardening:
  - bounded gzip/deflate decompression (other encodings refused), with parsing off the event loop;
  - nonce-fenced prompts;
  - a strict, city-aware scheduling match and a logistics guard on every day;
  - screenshots shrunk in the browser, with 32 MB nginx and 30 MB backend body limits;
  - `POST /api/import/resolve-place` to place spots by town;
  - deep links that survive the login redirect.

## Unreleased: documentation and housekeeping

- **Fare watch and price alerts** (branch `feat/price-alerts`): watch a single-destination trip's live fare from the Flights header, the fare calendar, My Plan or a saved plan; a background scheduler re-checks it about twice a day within a daily SerpAPI budget and notifies on a meaningful drop, a target price, a new Google-rated low or a cheaper date ±3 days, never on the baseline, never for a rise, never for small drifts (repeats need a further max($15, 5 %) drop unless the price rebounded) and at most once a day; each user gets at most 30 % of the daily SerpAPI budget. New `/alerts` page, header bell with toasts and optional browser notifications, optional SMTP email with a one-click stop link, and an email field on Preferences. New tables `fare_watches`, `fare_watch_history`, `fare_watch_quota`, `notifications`; new settings `FARE_WATCH_*`, `SMTP_*`, `APP_BASE_URL`. See [Trip Planning Features](Trip-Planning-Features.md#fare-watch-and-price-alerts).
- Developer docs consolidated into one set of pages (this site and the GitHub wiki share them), with new pages for trip-planning features, place and airport data, testing and CI, and this changelog.
- Added an MIT `LICENSE` file.
- App footer credits the place data: "Place data © GeoNames (CC BY 4.0) · Airport data: OurAirports".
- `docker-compose.yml` now builds the backend from the repo root, so `docker compose up --build` works.
- `get_optional_user` treats a deactivated user's token as anonymous.
- Removed the unused `knowledge_planner.py` and the unused `tools` / `max_turns` agent frontmatter fields.
- Place resolution (GeoNames `allCountries`, CC BY 4.0): countries resolve by their native and other-language names ("Deutschland", "Brasil", "Nippon", "Suomi"; KSA, PRC, ROK and ROC, and names that are also a town's, as qualifiers only); a suburb no longer beats a namesake with its own named airport ("Peoria" → PIA, "Pontevedra" → Spain); 31,995 notable islands, parks, glaciers, caves, mountains, regions, sites and famous districts resolve to their airports ("Kakadu" → DRW, "Grand Teton" → JAC, "Ealing" → LHR); district names many cities share give no answer ("Centar", "Chinatown"). See [Place and Airport Data](Place-and-Airport-Data.md).

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
