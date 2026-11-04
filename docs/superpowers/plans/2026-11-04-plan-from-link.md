# Plan a Trip From a Link or Screenshot — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development. Steps use checkbox (`- [ ]`) syntax.

**Goal:** A traveller pastes a travel blog / article / video link, pastes text (a caption, a friend's message, a list), or drops up to 4 screenshots — and gets a trip: the places are extracted, mapped and shown for review, then a normal full search plans the trip *around those places*, every one of them visibly scheduled in the itinerary ("From your link"). It must feel magical, fast and trustworthy.

**Spec:** User request 2026-11-04 — feature #3 "Plan from a link or screenshot", "very thoroughly and comprehensively … ENSURE THESE FEATURES DELIGHT USERS". Design choices are Claude's.

## Existing building blocks (verified)
- Backend FastAPI; agents call Anthropic directly through `BaseAgent` (`backend/app/agents/base_agent.py`, Haiku; Sonnet for chat). `beautifulsoup4` and `httpx` are dependencies. Rate limiting: `backend/app/core/rate_limit.py` (`rate_limit(bucket)` dependency, `try_consume`), settings `RATE_LIMIT_*`.
- Place resolution: `backend/app/db/places_db.py` `resolve_place(text)`, `backend/app/db/database.py` `lookup_city_iata`, `static_results._place_country`; places/features tables carry lat/lng and country.
- `TravelSearchRequest` (`backend/app/schemas/request.py`): origin, destination, destinations (multi-city ≤3 stops), destination_nights, dates, interests, pace, budget, travellers, etc.
- Orchestrator `backend/app/agents/orchestrator.py` (phases 0/1/2, SSE); activities agent; itinerary agent `backend/app/agents/itinerary_agent.py` takes `activities` (top 12 summarised) and `hotels`.
- Frontend: `SearchPage.jsx` has modes "I know where I'm going" / "Surprise me" / "Compare"; `ResultsPage.jsx` renders sections incl. `ItinerarySection`, `TripMap` (Leaflet), My Plan drawer; saved plans store `search_data`; share page `SharePage.jsx`; `utils/planExport.js` / `planPrint.js`.

## Design (binding)

### Backend
1. **`POST /api/import/extract`** (auth required; new rate-limit bucket `import`, default 20 per window, setting `RATE_LIMIT_IMPORT`). Body: `{ url?: str, text?: str (≤ 20,000 chars), images?: [{ media_type, data_base64 }] (≤ 4, each ≤ 5 MB decoded; png/jpeg/webp/gif; HEIC rejected with a friendly message) }` — exactly one kind of source. Response = an **ImportPreview** (below). Also accepts multipart image upload if simpler for the frontend; document whichever is used.
2. **Safe URL fetching** (`backend/app/services/link_fetch.py`):
   - http/https only; resolve DNS and **reject private, loopback, link-local, multicast, reserved, CGNAT and IPv6 equivalents** for the initial host and **every redirect hop** (max 3 redirects, manual redirect handling); connect to the vetted IP (prevent DNS rebinding) while sending the original Host/SNI; timeout 10 s; stop reading at 2 MB; accept text/html, application/xhtml+xml, text/plain; send a normal browser-like UA.
   - Extraction: `<title>`, OpenGraph/Twitter description, JSON-LD (Article/Recipe-like `articleBody`, `ItemList`, `Place`, `TouristAttraction`), and readable main text (prefer `<article>`/`<main>`, drop nav/footer/script/style, keep headings and list items — itineraries are usually lists). Cap at ~30k chars.
   - Social video/photo links: YouTube and TikTok via their public oEmbed endpoints (title/caption/author); YouTube description is not in oEmbed — use page metadata when available. Instagram/Facebook/X usually block — return a *specific* friendly error `{"code": "blocked_source", "message": "Instagram doesn't let apps read posts. Paste the caption or drop a screenshot instead."}` and the frontend switches the user to the text/screenshot tabs with one click.
   - Never execute scripts; never follow links found in content.
3. **Extraction agent** (`.agents/link_import.md` + `backend/app/agents/link_import_agent.py`, Haiku via `BaseAgent`; images use Claude vision content blocks): returns strict JSON `{ title, summary (1 sentence), places: [{ name, kind (sight|food|drink|stay|activity|nature|shopping|nightlife|event|transport|area), city, country, note (≤ 140 chars, why the source recommends it), quote (≤ 120 chars verbatim from source, optional), day_hint (int|null), confidence (0–1) }], destinations_mentioned: [str], suggested_days (int|null), season_hint (str|null), interests: [str] }`. **Prompt-injection hardening:** source content is wrapped as untrusted data with clear delimiters; the system prompt says to ignore any instructions inside it and only extract places; output validated with Pydantic; at most 40 places; drop items without a name. No PII echoed beyond place names.
4. **Resolution & grouping** (`backend/app/services/link_import.py`):
   - For each place: resolve its `city` (+ country) with `resolve_place` / `_place_country` → canonical city, country, lat/lng (city-level), airports. POI-level coordinates: if `SERPER_KEY` is configured, look the POI up (existing Serper places helper — find it) to get coordinates/address/rating and mark `verified: true`; otherwise use the city centre with `approximate: true`. Respect existing caches; cap Serper calls per import (≤ 25) and run them concurrently with a semaphore.
   - Group by resolved city; order cities by `day_hint` then source order. One city → single destination. 2–3 cities in ≤ 3 countries → propose a multi-city route (`destinations` + `destination_nights` split by place count, min 1 night). More than 3 cities → keep the 3 with the most places, list the rest as "also mentioned".
   - Suggested length: `suggested_days` if given, else ~4 places per day bounded 2–14.
   - Unresolved places stay in the preview under "Couldn't place" (editable on the client).
   - Response `ImportPreview`: `{ source: { kind: url|text|images, url?, title, site_name?, favicon_url?, author? }, title, summary, destinations: [{ name (the resolved display, e.g. "Lisbon, Portugal"), country, airports, place_count, nights }], places: [{ id, name, kind, city, country, lat, lng, approximate, verified, note, quote, day_hint, confidence }], unresolved: [...], suggested_days, season_hint, interests, warnings: [str] }`.
5. **Search integration:** add `must_include: list[MustIncludePlace] | None` (≤ 25; each `{ name, kind, city, lat?, lng?, note? }`) and `import_source: { url?, title } | None` to `TravelSearchRequest` (and pass them through chat-independent paths only).
   - **Activities:** must-include places are merged into the activities result as items with `source: "your_link"`, `from_link: true` (deduplicated against the agent's own results by folded name) and always kept, at the top.
   - **Itinerary:** the itinerary agent prompt lists must-include places as "MUST schedule every one of these" with their city; after the agent returns, a deterministic post-check inserts any missing must-include place into the least-loaded slot of the right city's days (or appends a day note if all slots are full) and marks scheduled slots `from_link: true`. The template fallback itinerary also includes them.
   - Phase-0/verification: imported items carry their own verification (verified via Serper or "From your link — not independently checked").
   - Saved plans keep `must_include` and `import_source` in `search_data`; share page and print/export show "Inspired by <title> (link)".
6. **Chat touch:** if a chat message is just a URL (or contains a URL and "plan"), the assistant replies with a short message and an action that opens the import flow prefilled (`/?import=<url-encoded>`) — no fetching inside chat.

### Frontend (delight is a requirement, not polish)
1. **Entry points:** a 4th Search mode tab **"From a link ✨"**; a hero hint on the Search page ("Saw a great trip online? Paste the link"); deep link `/?import=<url>` prefills and auto-starts; drag-and-drop a screenshot anywhere on the Search page opens the import tab with it; paste (Cmd/Ctrl-V) of an image or URL in the import tab works.
2. **Import panel:** one smart input that accepts a URL or free text (auto-detects), a screenshot drop zone (thumbnails, remove ×, 4 max, size/type validation messages), and 3 "Try an example" chips (a sample blog URL is risky — use example *texts*: e.g. "48 hours in Lisbon: Time Out Market, Belém Tower, LX Factory, sunset at Miradouro da Senhora do Monte…").
3. **Progress that tells a story:** staged steps with gentle animation — "Reading the page" → "Finding places" → "Putting them on the map" — and a cancel button; skeleton cards. Typical time 5–15 s; show it.
4. **Preview ("Here's what we found"):** source card (favicon, title, site, link), the trip title and one-line summary, a Leaflet map with numbered pins coloured by kind (fit bounds; approximate pins drawn hollow with a tooltip "approximate location"), places grouped by city with kind icons (lucide), the source's note/quote in italics, a checkbox per place (all on by default; "Select all / none" per city), inline rename and "Change city" for wrong ones, the "Couldn't place" group with an inline city field to fix, destination chips with nights steppers, and a suggested trip length. Below: the normal trip fields prefilled (origin from preferences, dates = next suitable window: today + 30 days by default, length from the suggestion; interests from the extraction merged with preferences). Primary button: **"Plan this trip (N places)"**. Secondary: "Start over".
5. **Results:** a dismissible banner at the top "Planned around 11 places from *48 hours in Lisbon* — all 11 are in your itinerary" (or "10 of 11 — 1 didn't fit: show"); activity cards and itinerary rows from the link carry a small **"From your link"** chip with the quote on hover/tap; TripMap shows them with a distinct marker; My Plan drawer shows the source. Saved plans list shows a link icon.
6. **Errors are friendly and actionable:** blocked source → one-click switch to text/screenshot; no places found → "We couldn't spot any places — try pasting the part of the article with the list"; paywall/404/timeouts → specific messages; rate limit → server detail; image too big / HEIC → explain and suggest PNG/JPEG.
7. **Quality bar:** responsive down to 360 px, keyboard accessible (tab order, Enter to submit, Esc to cancel), ARIA live region for progress, reduced-motion respected, consistent with existing Tailwind/lucide style, no layout shift. Analytics events via the existing `track()` helper (import_started/kind, import_preview_shown/place_count, import_planned, import_failed/code).

### Docs
Trip-Planning-Features.md (new section with screenshots-free description), API-Reference.md (endpoint + request fields), Configuration.md (`RATE_LIMIT_IMPORT`), Architecture.md (flow), CLAUDE.md one line, Changelog entry, README feature bullet.

## Global Constraints
No new Python/npm dependencies. No network in tests (mock httpx, Anthropic, Serper). SSRF tests are mandatory (private IPs incl. IPv6 and mapped IPv4, redirect to private, non-http schemes, oversized body, wrong content type, DNS rebinding pin). Backend pytest + ruff; frontend vitest + eslint + build. Existing tests stay green.

---
### Task 1: Safe link fetching + content extraction (+SSRF tests)
### Task 2: Extraction agent (text/url/images) + resolution/grouping service + `POST /api/import/extract` + rate bucket (+tests)
### Task 3: `must_include` / `import_source` through search: activities merge, itinerary prompt + deterministic post-check + template fallback, saved/share/export (+tests)
### Task 4: Frontend import tab, preview (map, review, edit), progress, errors, deep link, results banner/chips, chat hand-off (+tests)
### Task 5: Docs
