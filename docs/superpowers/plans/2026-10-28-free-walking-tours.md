# Free Walking Tours Section Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A new "Free Walking Tours" section on the Results page, right after "Places to See". It recommends free walking tours for each destination city, found by crawling GuruWalk, FreeTour.com, SANDEMANs NewEurope and FreeWalkingTour.com. Every card links to the original tour page.

**Architecture:**
- A deterministic crawler service fetches each provider's public city page, then parses structured data (JSON-LD `Event`) or HTML cards into one normalized tour shape.
- A new specialist agent, `WalkingToursAgent`, runs the crawl per destination city. It asks the LLM (Haiku, via `BaseAgent.execute`) to pick and explain the best tours for this traveler, choosing **by candidate id only**. URLs always come from the crawl and never from the LLM.
- If the LLM fails, a rating-based ranking is used, so a successful crawl never yields a blank section.
- The agent streams as a normal Phase-1 section (`type: "walking_tours"`).
- The frontend adds a section component plus full My Plan support: drawer, saved-plan viewer, share page and print.

**Tech Stack:** FastAPI, httpx (async), BeautifulSoup4, ddgs (fallback discovery), pytest; React 18, Tailwind, vitest (+ jsdom).

**Spec:** the user request and the design in this conversation, summarised in "Design facts" below.

## Design facts (verified against the live sites, 2026-10-28)

| Provider key | Display name | City page | Parse | Notes |
|---|---|---|---|---|
| `guruwalk` | GuruWalk | `https://www.guruwalk.com/{slug}` | JSON-LD `@type: Event` (≈10/page): `name, url, image, description, aggregateRating{ratingValue, reviewCount}, offers{price:0}` | robots disallows `/search`; city pages allowed |
| `freetour` | FreeTour.com | `https://www.freetour.com/{slug}` | JSON-LD `Event`, same fields | robots allows user-initiated agents; only `/company/`, `/booking/`, `/account/` disallowed |
| `freewalkingtour` | FreeWalkingTour.com | `https://freewalkingtour.com/{slug}/` | HTML cards `a.relative.block.h-full` (href `/{slug}/{tour}/`); card text e.g. `"Pay what you wish Welcome to Barcelona: Old Town and Modernism 4.9 116 reviews 2h 30m Book now"`; image `src` may be relative `/_ipx/...` | Keep only cards containing "Pay what you wish" (others are paid private tours). Unknown city → HTTP 500 |
| `sandemans` | SANDEMANs NewEurope | `https://www.neweuropetours.eu/sandemans-tours/{slug}/` | `a[href*="/sandemans-tours/{slug}/"]` with link text; keep titles containing "free" (case-insensitive), dedupe by href | Paid "Private Tour" links must be dropped |

- Unknown cities return 404 (or 500 on freewalkingtour). Treat any non-200 response as status `"none"` for that provider.
- Requests use the honest User-Agent `VoyagerTravelPlanner/1.0 (trip-planning assistant; fetches city tour listings on behalf of a user)`. It is accepted by all four sites.

## Global Constraints

- The section key is `walking_tours` everywhere: SSE `type`, `AGENT_ORDER`, selections key, agent name and `.agents/walking_tours.md`.
- It is placed immediately after `places_to_see` in `AGENT_ORDER` and in the orchestrator lists.
- **LLM output never supplies URLs.** The prompt says so, and the code ignores any URL the LLM returns. Card links are crawled URLs whose host matches the provider's domain.
- Agent prompts always pair each city with its country (repo rule; see `docs/agents.md` "How to add a new agent").
- Fetch only the four city-page URL patterns above. One request per provider per city, timeout 12 s, all providers in parallel, results cached in `get_cache()` under `walking_tours:{provider}:{slug}`.
- Chat is knowledge-only: **no** chat wiring.
- No new dependencies (httpx, bs4 and ddgs are already in `backend/requirements.txt`).
- Frontend links use `target="_blank" rel="noopener noreferrer"` and pass through `safeUrl` (exported from `frontend/src/utils/planPrint.js`).
- Copy: section label `Free Walking Tours`; badge label `Walking Tours`; price notes are `Free · tip-based` (guruwalk, freetour, sandemans) and `Pay what you wish` (freewalkingtour).

### Data contract (backend produces, frontend consumes)

```json
{
  "results": [{
    "id": "guruwalk-barcelona-0",
    "name": "Free Tour of the Old Town",
    "provider": "GuruWalk",
    "provider_key": "guruwalk",
    "url": "https://www.guruwalk.com/walks/564-free-tour-...",
    "image_url": "https://media.guruwalk.com/...",
    "description": "…",
    "rating": 4.9, "review_count": 1234,
    "duration": "2h 30m",
    "price_note": "Free · tip-based",
    "city": "Barcelona",
    "reason": "Covers the Gothic Quarter — matches your history interest",
    "top_pick": true
  }],
  "sources": [{"provider": "GuruWalk", "provider_key": "guruwalk", "city": "Barcelona",
               "url": "https://www.guruwalk.com/barcelona", "count": 10, "status": "ok"}]
}
```

- `status` is one of `"ok" | "none" | "error"`.
- If every provider for every city returns `"error"`, the agent returns `{"error": "..."}`.
- `rating`, `review_count`, `duration`, `image_url`, `description` and `reason` may be `null`.

## Review Focus

1. **Destination formats.** `"Tokyo, Japan (HND)"`, `"Kraków"` (diacritics), `"New York City"` and a bare IATA code all need a usable slug, plus discovery when the slug misses. → `test_city_slug_*` and `test_split_city_country_*` in Task 1, and `test_discovery_fallback_used_on_404` in Task 2.
2. **Malformed provider pages.** Broken JSON-LD, missing fields, non-numeric ratings, relative image URLs or HTML changes must yield fewer cards, never a crash or an error for the whole section. → `test_parse_*_tolerates_*` in Task 1.
3. **LLM misbehaviour.** Unknown ids, duplicate ids, invented URLs, an `{"error"}` result or empty recommendations. Cards must still show (heuristic fallback), with only crawled URLs. → `test_agent_*` in Task 3.
4. **Partial outages.** One or more providers time out or are blocked: the section shows what was found. Only a total failure is an error. → `test_fetch_city_tours_partial_failure` and `test_all_providers_fail_returns_error` in Tasks 2–3.
5. **Untrusted links in the UI.** A `javascript:` or other-domain URL in data must not render as a live link. → `walking tours card never renders unsafe links` in Task 5.

---

### Task 1: Provider parsers and city helpers (pure functions)

**Files:**
- Create: `backend/app/services/walking_tours.py`
- Test: `backend/tests/test_walking_tours_parsers.py`, with small handwritten HTML fixtures inline in the test (mirroring the structures in Design facts; never committed copies of the real pages)

**Interfaces — Produces:**
- `PROVIDERS: dict[str, dict]` keyed by provider key, each holding `name`, `domain`, `city_url: Callable[[str], str]`, `price_note`
- `city_slug(city: str) -> str`: NFKD → ASCII; lowercase; anything outside `[a-z0-9]` becomes a single `-`; strip leading and trailing `-`
- `split_city_country(destination: str) -> tuple[str, str | None]`: drops a trailing `(XXX)` IATA code, splits on the first comma, strips whitespace
- `parse_jsonld_tours(html: str, provider_key: str, city: str) -> list[dict]`
- `parse_freewalkingtour(html: str, slug: str, city: str) -> list[dict]`
- `parse_sandemans(html: str, slug: str, city: str) -> list[dict]`
- All parsers return tour dicts in the data-contract shape, with `id = f"{provider_key}-{slug}-{n}"`, `reason=None`, `top_pick=False`. They keep only URLs whose host equals or ends with the provider domain, cap at 10 tours, drop duplicate URLs, and never raise (they return `[]` on garbage).

- [ ] **Step 1: Write the failing tests**
  - `test_city_slug_basic`: `"Barcelona"→"barcelona"`, `"New York"→"new-york"`, `"Kraków"→"krakow"`, `"Mexico City"→"mexico-city"`, `"  São Paulo "→"sao-paulo"`
  - `test_split_city_country`: `"Tokyo, Japan (HND)"→("Tokyo","Japan")`, `"Lisbon"→("Lisbon",None)`, `"Paris, France"→("Paris","France")`
  - `test_parse_jsonld_extracts_events`: two `Event`s nested in `@graph` / `itemListElement` → 2 tours with `name`, `url`, `image_url`, `rating=4.9`, `review_count=120`, `price_note="Free · tip-based"`, `provider="GuruWalk"`
  - `test_parse_jsonld_tolerates_bad_blocks`: an unparseable `ld+json` block plus a valid one gives 1 tour; ratings as strings (`"4.8"`) are converted to float; a missing `aggregateRating` gives `rating=None`
  - `test_parse_jsonld_drops_foreign_urls`: an `Event` whose url is on `evil.example` is dropped
  - `test_parse_freewalkingtour_cards`: fixture with 3 cards, one without "Pay what you wish" → 2 tours. Values: `name="Welcome to Barcelona: Old Town and Modernism"`, `rating=4.9`, `review_count=116`, `duration="2h 30m"`, absolute `url="https://freewalkingtour.com/barcelona/barcelona-historic-centre-spain/"`, relative image made absolute, `price_note="Pay what you wish"`
  - `test_parse_sandemans_keeps_free_only`: links "Free Tour of Barcelona", "Barcelona Gaudí & Modernism Free Tour" and "3-hour Barcelona Private City Tour", plus a duplicate → 2 tours
  - `test_parsers_return_empty_on_garbage`: `""` and `"<html>nothing</html>"` give `[]` for all three parsers
- [ ] **Step 2:** Run `cd backend && /usr/local/bin/python3 -m pytest tests/test_walking_tours_parsers.py -q`. Expected: fails on import.
- [ ] **Step 3:** Implement the functions with BeautifulSoup (`html.parser`). The freewalkingtour card text is parsed with regexes: rating `(\d\.\d)`, reviews `(\d+)\s+reviews?`, duration `(\d+h(?:\s*\d+m)?|\d+m)`. The name is the card text after removing the price phrase and everything from the rating onwards.
- [ ] **Step 4:** Run the tests. Expected: all pass. Then run `uvx ruff@0.15.13 check backend/ && uvx ruff@0.15.13 format --check backend/`.
- [ ] **Step 5:** Commit: `feat(walking-tours): provider parsers and city helpers`.

### Task 2: Crawler: fetch, discovery fallback, caching

**Files:**
- Modify: `backend/app/services/walking_tours.py`
- Test: `backend/tests/test_walking_tours_fetch.py`

**Interfaces:**
- Consumes: Task 1.
- Produces: `async def fetch_city_tours(city: str, *, client: httpx.AsyncClient | None = None) -> tuple[list[dict], list[dict]]`, which returns `(tours, sources)`. `sources` has one entry per provider, in the shape of the data contract.
  - Providers are fetched in parallel (`asyncio.gather`), with a 12 s timeout each and the User-Agent from Design facts.
  - A non-200 response gives `"none"`; an exception or timeout gives `"error"`.
  - Results are cached per `(provider, slug)` with `get_cache()`; failures are not cached.
  - **Discovery fallback:** when a guruwalk or freetour city page returns non-200, run one `ddgs` text search `site:{domain} {city} free walking tour`, executed off the event loop. Take the first result URL that matches `^https://www\.{domain}/[a-z0-9-]+/?$`, fetch it and parse it. If nothing is found, the status stays `"none"`.

- [ ] **Step 1: Failing tests.** Use `httpx.MockTransport` routing by URL; never hit the network.
  - `test_fetch_city_tours_all_ok`: 4 fixture pages give tours from 4 providers and 4 `sources` with `status="ok"` and the right `count`
  - `test_fetch_city_tours_partial_failure`: guruwalk raises `httpx.ConnectTimeout`, freewalkingtour returns 500, the others are ok. Expected sources: `error`, `none`, `ok`, `ok`; tours only from the ok providers
  - `test_fetch_uses_cache`: the second call for the same city performs 0 transport requests (clear the cache between tests)
  - `test_discovery_fallback_used_on_404`: freetour `/lisboa-x` gives 404. A monkeypatched discovery returns `https://www.freetour.com/lisbon`, which serves the fixture, so status is `ok`
  - `test_requests_send_honest_user_agent`: every request's `User-Agent` starts with `VoyagerTravelPlanner/1.0`
- [ ] **Step 2:** Run the tests and confirm they fail.
- [ ] **Step 3:** Implement. Keep the discovery search in a module-level `async def _discover_city_url(provider_key, city) -> str | None` so tests can monkeypatch it.
- [ ] **Step 4:** Run `tests/test_walking_tours_*.py` and ruff. All must pass.
- [ ] **Step 5:** Commit: `feat(walking-tours): parallel crawler with caching and discovery fallback`.

### Task 3: WalkingToursAgent, agent definition, orchestrator, route, schema

**Files:**
- Create: `.agents/walking_tours.md`, with frontmatter `name: walking_tours`, a description, `tools: []` and `max_turns: 1`. The body follows the events.md / places.md conventions: a "What to Find" section, a "Rules" section, and an output example of the **recommendation** JSON below. It must state "Never output URLs".
- Create: `backend/app/agents/walking_tours_agent.py`, `class WalkingToursAgent(BaseAgent)` with `__init__(self, agents_dir)` and `async def run(self, request: TravelSearchRequest) -> dict`
- Create: `backend/app/api/routes/walking_tours.py`, `POST /walking-tours`, mirroring `routes/events.py`
- Modify: `backend/app/main.py`: register the router with tag `walking_tours`
- Modify: `backend/app/agents/orchestrator.py`:
  - import and `self.walking_tours = WalkingToursAgent(agents_dir)`
  - in `run()`, add it to the gather after `self.events.run(request)`, as `walking_tours = safe(phase1_results[10], {"results": []})`, and add `"walking_tours"` to the returned dict after `"places_to_see"`
  - in `stream_run()`, add it to the `agent_status` list after `"places_to_see"` and add `"walking_tours": self.walking_tours` to `phase1_agents`
- Modify: `backend/app/schemas/travel.py`: add `WalkingTour`, `WalkingTourSource` and `WalkingToursResponse` per the data contract, and `walking_tours: dict = {}` on `TravelSearchResponse`
- Test: `backend/tests/test_walking_tours_agent.py`

**Interfaces:**
- Consumes: `fetch_city_tours`, `split_city_country` from Tasks 1–2.
- **Recommendation format the LLM returns:** `{"recommendations": [{"id": str, "reason": str, "top_pick": bool}]}`, best first.
- `run()` behaviour:
  1. Determine the cities: `request.destinations` if multi-city, else `[request.destination]`.
  2. Crawl every city concurrently.
  3. If every source has status `error`, return `{"error": "Couldn't reach the walking-tour sites right now"}`.
  4. If no tours were found, return `{"results": [], "sources": [...]}` without calling the LLM.
  5. Otherwise build the prompt:
     - each city with its country (use `split_city_country`, and add "(identify the country)" when it is `None`)
     - interests, `request.traveler_context` and `request.serendipity_context`
     - when multi-city, the coverage rule "4–6 per city"
     - one line per candidate: `id | name | provider | rating | reviews | duration | description[:200]`
     - ask for 4–8 picks per city, at most 2 `top_pick` per city, and a reason of at most 20 words tied to the traveler
  6. Merge the answer: keep only known ids, the first occurrence of each, in the LLM's order, setting `reason` and `top_pick` from it. Any URL-like field from the LLM is ignored.
  7. If the LLM returned an error, or nothing usable remains: rank by `rating * log1p(review_count)` (unknown values last), keep 8 per city, `reason=None`, `top_pick=False`.
  8. Return `{"results": [...], "sources": [...]}`.

- [ ] **Step 1: Failing tests.** Follow the pattern of `test_events.py`: `WalkingToursAgent.__new__`, with `execute` as an `AsyncMock` and `fetch_city_tours` patched.
  - `test_agent_prompt_has_city_country_interests_candidates`: the prompt contains `"Barcelona"`, `"Spain"`, the interests, every candidate id, and `"Never"` plus `"URL"`
  - `test_agent_merges_llm_picks_in_order`: the LLM returns ids `[c3, c1]` with reasons; results are `[c3, c1]` with those reasons and `top_pick` set
  - `test_agent_ignores_unknown_and_duplicate_ids_and_llm_urls`: the LLM returns `[bogus, c2, c2 {url:"https://evil.example"}]`, giving exactly `[c2]` with its crawled url
  - `test_agent_falls_back_when_llm_errors`: `execute` returns `{"error":"x"}`, giving rating-ranked results with `reason=None` and no `"error"` key
  - `test_agent_no_tours_skips_llm`: `execute` is not awaited and `results == []`
  - `test_all_providers_fail_returns_error`: every source is `error`, so the result has an `"error"` key
  - `test_agent_multi_city_coverage`: 2 destinations produce two crawls and a prompt containing both cities and `"per city"`
  - `test_definition_loads`: `load_agent_definition(settings.agents_dir, "walking_tours").name == "walking_tours"`
  - `test_orchestrator_wiring`: `inspect.getsource(orchestrator)` contains `self.walking_tours = WalkingToursAgent(agents_dir)`, `self.walking_tours.run(request)` and `"walking_tours": self.walking_tours`
  - `test_route_returns_agent_result` and `test_route_rejects_bad_body` (422), with `WalkingToursAgent.run` patched
- [ ] **Step 2:** Run and confirm they fail.
- [ ] **Step 3:** Implement everything listed under Files.
- [ ] **Step 4:** Run the full backend suite `cd backend && /usr/local/bin/python3 -m pytest -q` (expect 273 + the new tests, 2 warnings), then ruff and `bandit -q -r backend/app/ -ll --skip B105,B106,B608`.
- [ ] **Step 5:** Commit: `feat(walking-tours): specialist agent, orchestrator wiring and /api/walking-tours`.

### Task 4: Live crawl smoke check (manual, not CI)

- [ ] Run `fetch_city_tours` against the real sites for Barcelona, Lisbon, Prague, Tokyo, New York and Kraków from a one-off script in the session scratchpad, not the repo. Record the per-provider counts and spot-check 2 URLs per provider (HTTP 200, page title matches the tour name). Fix any parser drift found, adding a regression test to Task 1's file for it.

### Task 5: Frontend section component

**Files:**
- Create: `frontend/src/components/WalkingToursSection.jsx`: `export default function WalkingToursSection({ data, selections, onSelect })`
- Modify: `frontend/src/utils/planPrint.js` only if `safeUrl` is not already exported (it is; just import it)
- Test: `frontend/src/components/WalkingToursSection.test.jsx` (jsdom; use the `createRoot` + `act` pattern from `RecentSearches.test.jsx`)

**Interfaces:**
- Consumes: the data contract.
- Calls `onSelect('walking_tours', tour)`; a tour is selected when `selections.walking_tours` contains an item with the same `url`.

**Behaviour and copy:**
- `data?.error`: show "Couldn't reach the walking-tour sites this time — the rest of your plan is unaffected."
- Empty `results`: show "No free walking tours listed for this destination on GuruWalk, FreeTour.com, SANDEMANs or FreeWalkingTour.com."
- Cards, top picks first, in a 2-column grid on `sm` and up. Each card shows:
  - image (`referrerPolicy="no-referrer"`, hidden on error)
  - provider badge, plus a `Top pick` badge when `top_pick`
  - name as a link to `safeUrl(url)`
  - rating with "(n reviews)", and duration
  - `price_note`
  - `reason` when present, in italic
  - a city chip when the results span more than one city
  - an "Add"/"Added" toggle button
  - "View on {provider} ↗" as a link
- Footer: "Searched: GuruWalk (10) · FreeTour.com (10) · …", from `sources`.

- [ ] **Step 1: Failing tests**
  - `renders a card per tour linking to the original page`: name and "View on GuruWalk" anchors have the tour `href`, `target="_blank"` and `rel` containing `noopener` and `noreferrer`
  - `walking tours card never renders unsafe links`: `url: "javascript:alert(1)"` produces no anchor with that href, and the name renders as plain text
  - `shows top picks first and their reasons`
  - `Add toggles selection via onSelect`
  - `error and empty states`
  - `lists searched sources with counts`
- [ ] **Step 2:** Run `cd frontend && NODE_OPTIONS=--experimental-require-module npx vitest run src/components/WalkingToursSection.test.jsx` and confirm it fails.
- [ ] **Step 3:** Implement with Tailwind, matching the `PlacesToSeeSection` card styling in `ResultsPage.jsx`. Import icons under aliases if a name could shadow a global; never import `Map` bare.
- [ ] **Step 4:** Tests pass; `npx eslint src/ --max-warnings 0` is clean.
- [ ] **Step 5:** Commit: `feat(walking-tours): results section component`.

### Task 6: Results page wiring and My Plan drawer

**Files:**
- Modify: `frontend/src/pages/ResultsPage.jsx`. Line numbers are from HEAD 65fd6a9 and may shift slightly:
  - icon import `Footprints`
  - `AGENT_CONFIG` entry `walking_tours: { label: 'Free Walking Tours', icon: Footprints, color: 'teal' }`
  - `AGENT_ORDER`: insert `'walking_tours'` right after `'places_to_see'`
  - `BADGE_LABELS.walking_tours = 'Walking Tours'`
  - `LOADING_MESSAGES.walking_tours`: 3 messages, e.g. "Checking GuruWalk and FreeTour.com…", "Reading SANDEMANs and FreeWalkingTour.com…", "Picking tours for your interests…"
  - status list (~3524): `walking_tours: 'loading'`
  - `renderers`: `walking_tours: () => <WalkingToursSection data={data} {...sectionProps} />`
  - selections: initial state (~3386) and reset (~3466) get `walking_tours: []`; `selectedCount` (~3613)
  - `handleSelect`: toggle by `url`; `handleRemoveSelection`: remove by `url`
  - `MyPlanDrawer`: a "Walking tours (n)" block after the places block, with name, provider, the city if set, a link via `safeUrl` and a remove button
- Modify: `frontend/src/utils/planHelpers.js`: `EMPTY_SELECTIONS.walking_tours = []` and `countSelections` counts them
- Test: `frontend/src/utils/planHelpers.test.js`: `countSelections counts walking tours`, and `EMPTY_SELECTIONS` has `walking_tours: []`

- [ ] Steps: failing test → fails → implement → `vitest run`, eslint and `vite build` all pass → commit `feat(walking-tours): results page wiring and My Plan support`.

### Task 7: Saved plans, share page and print

**Files:**
- Modify: `frontend/src/components/PlanViewModal.jsx`:
  - initial `sel` gets `walking_tours: []`
  - `removeItem` gets a branch by `url`
  - `hasSelections` includes walking tours
  - add a "Walking Tours" `Section` after the events section, with links via `safeUrl`
- Modify: `frontend/src/pages/SharePage.jsx`: the PNG `listSection`, the hero summary line ("N free walking tours") and a `DetailCard` "Free Walking Tours" with links via `safeUrl`
- Modify: `frontend/src/utils/planPrint.js`: `section('Free walking tours', list(sel.walking_tours, t => esc(t.name) + muted provider/city + link(t.url, 'View tour')))` after 'Places to see'
- Test: `frontend/src/utils/planPrint.test.js`: `includes selected walking tours with safe links`; a `javascript:` url gives no link
- [ ] Steps: failing test → fails → implement → `vitest run`, eslint and build → commit `feat(walking-tours): saved plans, share page and print`.

### Task 8: Docs, whole-branch review, end-to-end test, PR and merge (coordinator)

- Docs:
  - `CLAUDE.md`: agent count "Thirteen", the list, the API table row `POST /api/walking-tours`, and the My Plan selections list
  - `docs/Agent-System.md` and `docs/agents.md`: agent table, how-to, and multi-city table
  - `docs/API-Reference.md` and `docs/api.md`: SSE type `walking_tours` and the endpoint
  - `docs/Frontend.md`, `docs/Home.md` (sections list), `docs/Sharing-and-Plans.md`, `docs/Multi-City-Trips.md` and `README.md`
- An independent whole-branch code review, with its findings fixed.
- End to end:
  - an isolated backend and frontend, as in the `verify` skill
  - a real search for a single city (Barcelona) and a multi-city trip (Lisbon → Porto)
  - the section renders after Places to See, cards open the original tour pages, and Add → My Plan → Save → View/Share/Print all include the tours
  - no console errors, and no regressions in the other sections
- Then the full CI-equivalent checks, a PR, a green CI and the merge into `main`.
