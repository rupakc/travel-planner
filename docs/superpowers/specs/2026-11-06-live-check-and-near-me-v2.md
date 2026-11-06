# Live "Search the web now" + Near Me v2 — design & API contract

Status: decided (user, 2026-11-06). Sources: official Google terms/docs summarised in
`scratchpad/gcp-plan/gemini-tools-facts.md` (Service Terms §20(k) Grounding with Google Search,
§20(m) Grounding with Google Maps; Agent Platform pricing).

## Decisions
1. **Watches and alerts stay on SerpAPI.** Google's §20(k) forbids background (non-user-prompted)
   grounded checks, storing grounded results to build a database, and analysing them. So Gemini web
   search is **never** used by the scheduler, never stored, never compared with baselines, never feeds
   alerts, notifications or price history.
2. **New: "Search the web now"** — a user-initiated Gemini call with Google Search grounding for one
   watch (fare, hotel, activity, trip). The answer is returned to the requesting user only, displayed
   once with its sources, and not persisted anywhere (no DB, no cache, no logs of content). Clients
   keep it in memory only (Android: ViewModel state, not Room/DataStore; web: component state).
3. **Near Me v2** uses Gemini with **Grounding with Google Maps** around the user's coordinates and
   returns four sections: places to see, places to eat, places to shop, places to stay — each item
   with an "Open in Google Maps" link. Results go only to the requesting user; **no server-side
   cache** (Maps terms allow storing grounded results only for display evaluation ≤ 90 days or chat
   history); clients keep them in memory only. `place_id` may be stored (allowed) but we don't need to.
4. **Background "nearby" notifications must not call Maps grounding.** The Android worker only posts
   an invitation ("See what's near you") that opens Near Me, where the user's own request runs.
5. Both features use the existing per-user `light_ai` rate limit, require sign-in, and count against
   the Gemini spend cap (₹1,800). Free allowances: 5,000 Search-grounding queries + 5,000 Maps
   queries per month (shared across Gemini models), then $14 / 1,000 queries.
6. Attribution/display: show sources directly under the content they support ("Sources" list with
   titles + links); Near Me shows "Google Maps" attribution text per Google's guidelines and each
   item's Maps link. Do not modify grounded text or intersperse ads/other content inside it.
   Search Suggestions: we display the returned search queries as a "Searched for" line linking to
   Google Search (permitted to skip the Search Suggestions widget under the pricing page's volume
   condition; record that in docs).

7. **Provider ruling:** grounding exists only on the `gemini` provider. With `LLM_PROVIDER` resolved to
   `anthropic` (local dev), `/api/live-check` and `/api/nearby` with `sections: true` answer
   503 `{"detail":{"code":"grounding_unavailable","message":"Live web and map results need the Gemini provider."}}`;
   v1 nearby is unaffected. One shared seam: `core/llm.py` gains `generate_grounded(...)` (text output,
   returns text + grounding chunks + web search queries + usage) used by both features; tests stub it.
   JSON mode is not combined with grounding (uncertain on Vertex) — parse structured bits from the text
   and take links only from grounding metadata.

## API contract

### `POST /api/live-check` (auth required, `light_ai` bucket)
Request:
```json
{"kind": "flight" | "hotel" | "activity" | "trip", "watch_id": 123}
```
- `kind=flight` uses `/api/fare-watches/{id}` ownership; other kinds `/api/price-watches/{id}`; 404 if
  the watch isn't the caller's. The server builds the prompt from the stored watch spec (route + dates
  + travellers / hotel + dates + guests / activity + city + date / trip parts). No free-text prompt
  from the client.

Response 200:
```json
{
  "kind": "hotel",
  "watch_id": 123,
  "checked_at": "2026-11-06T18:00:00Z",
  "summary": "Plain-text answer from Gemini (grounded), unmodified.",
  "quotes": [
    {"label": "Booking.com, 3 nights", "amount": 412.0, "currency": "EUR", "source_index": 0}
  ],
  "sources": [{"title": "…", "uri": "https://…"}],
  "searched_for": ["memmo alfama lisbon price 1-4 dec 2026"],
  "disclaimer": "From a live web search just now. Prices change quickly — check the provider before booking. Not used for your price alerts."
}
```
- `quotes` may be empty; each quote must cite a source by index; amounts are copied from the grounded
  answer (never invented); unparseable → omitted.
- Errors: 404 `{"detail":"Watch not found"}`; 429 rate limit (string detail); 503
  `{"detail": {"code":"ai_limit"|"ai_billing", "message": "…"}}` (same friendly copy as other AI
  routes); 502 `{"detail":{"code":"live_check_failed","message":"…"}}` when the model returns no
  grounded answer.
- Never written to the DB, never logged with content (usage log line only: tokens, search query
  count, latency).

### `POST /api/nearby` v2 (auth required, `light_ai`)
Request (backward compatible):
```json
{"lat": 38.72, "lng": -9.14, "limit": 8, "sections": true, "language": "en"}
```
- `sections` absent/false → **v1 behaviour unchanged** (`{place, items}` from the activities agent),
  so already-installed apps keep working.
- `sections: true` → v2:
```json
{
  "place": {"name": "Lisbon", "region": null, "country": "Portugal", "country_code": "PT",
            "lat": 38.72, "lng": -9.14, "distance_km": 0.4},
  "sections": [
    {"id": "see",  "title": "Places to see",  "items": [ITEM, …]},
    {"id": "eat",  "title": "Places to eat",  "items": [ITEM, …]},
    {"id": "shop", "title": "Places to shop", "items": [ITEM, …]},
    {"id": "stay", "title": "Places to stay", "items": [ITEM, …]}
  ],
  "attribution": "Google Maps",
  "sources": [{"title": "…", "uri": "https://maps.google.com/…"}]
}
```
ITEM:
```json
{"name": "Time Out Market", "summary": "One-line why, from the grounded answer",
 "maps_uri": "https://maps.google.com/?cid=…", "place_id": "ChIJ…", "category": "eat"}
```
- Each item must come from a Maps grounding chunk (uri/title/placeId); items without a Maps link are
  dropped (no invented places). `limit` per section (1..10, default 6). Sections may be empty (UI
  shows a friendly empty state). `place` still resolved from the local places DB (unchanged).
- Errors: v1's 404 `no_place` / 502 `agent_error` codes unchanged; plus 503 `ai_limit`/`ai_billing`.
- No server cache for v2.

## Clients
- **Web:** new top-level "Near me" page (`/nearby`) — browser geolocation with a clear permission
  explainer and a manual "use a city instead" fallback (typed place → coordinates via
  `/api/airports/search` or the places DB if available; else skip), four sections with cards,
  "Open in Google Maps" links (new tab, `rel=noopener`), Google Maps attribution, loading/empty/error
  states, a11y as the rest of the app. Alerts page: "Search the web now" on every watch card (fare,
  hotel, activity, trip) showing the result panel (summary, quotes with source links, Searched for,
  disclaimer), never cached in storage.
- **Android:** Near me screen uses v2 (`sections: true`) with four sections, Maps intent links
  (geo/Maps URI), attribution; results kept in ViewModel memory only (remove any Room/DataStore cache of
  nearby results; keep only the coarse location cell). Nearby notification worker posts only an
  invitation (no API call). Alerts: "Search the web now" on watch cards, same panel; memory only.
