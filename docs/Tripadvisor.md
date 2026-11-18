# Tripadvisor Ratings

Live Tripadvisor ratings for the top-rated attractions around a trip's destination, shown on the Results page in their own card after **Places to see**. They come from Tripadvisor's **Terra** API (Discover package; the legacy Content API was retired on 2026-08-31) and are fetched only when a signed-in traveller presses **Show Tripadvisor ratings**.

The feature is off by default. It is on only when `TRIPADVISOR_ENABLED=true` **and** `TRIPADVISOR_API_KEY` is set; then `GET /api/config` reports `features.tripadvisor: true`. With the flag off, the endpoint answers `404` and the web app never shows the card (an older backend has no flag, so the card stays hidden there too).

## How it works

1. The traveller presses **Show Tripadvisor ratings** (one button per city on a multi-city trip).
2. `POST /api/tripadvisor/attractions {"destination": "Paris"}` resolves the destination with the local place data (`resolve_place`) to a point.
3. First view of that destination: one `GET /locations/nearby` call (`category=ATTRACTION`, radius `TRIPADVISOR_RADIUS_KM`, `size` = `TRIPADVISOR_PAGE_SIZE`, Tripadvisor's own order: rating, descending). The returned **location IDs only** are saved for the destination.
4. Later views: one multi-get `GET /locations?id=…` for the saved IDs, shown in the saved order.
5. The answer goes straight to the browser, which keeps it in component state. It is never cached or stored anywhere.

Every call sends `X-API-Key` (never logged or returned) and `version=1` to `TRIPADVISOR_BASE_URL` (`https://terra.tripadvisor.com/api`). Search and nearby calls are spaced at least 1 s apart, Terra's limit for those endpoints. Nothing calls Terra from background jobs, prefetching, the search stream, chat or tests (an autouse fixture in `backend/tests/conftest.py` fails any test that would).

## Terms encoded

From Tripadvisor's [API Master Terms](https://docs.terra.tripadvisor.com/docs/api-master-terms.md), [Caching Policy](https://docs.terra.tripadvisor.com/docs/caching-policy.md), [Linking Policy](https://docs.terra.tripadvisor.com/docs/linking-policy.md), [display requirements](https://docs.terra.tripadvisor.com/docs/display-requirements.md) and [usage-based pricing](https://docs.terra.tripadvisor.com/docs/usage-based-pricing.md):

| Term | How the app follows it |
|---|---|
| No caching, copying or storing of content, except the Location ID (for speed) | The only Tripadvisor data stored is `tripadvisor_location_ids` (destination key → list of integer IDs). No response cache, not in the search cache, plans, share links, offline pack, trip snapshots, telemetry props or logs. Logs hold the path, HTTP status and billed count only. A test scans every table for content after two calls. |
| Tripadvisor mark and a link back on the content | The card shows the Tripadvisor logo (linked to tripadvisor.com). Every name and review count links to the location's Tripadvisor page (`urls.tripadvisor.main`). A location without such a link is dropped. |
| Show content as returned; don't change sort or ranking order | Values are shown unchanged (a subset of fields: name, rating bubble image, review count, ranking text, category), in Tripadvisor's order. |
| Keep Licensed Content separate; don't combine it with other ratings | Its own labelled card, never merged into our Places to see list, our rankings, verification badges, the best-value package, the budget planner or the itinerary. |
| Not near booking functions run by others | Not in the Hotels or Activities sections (they carry third-party booking links). |
| Not indexable, not reachable by bots | Loaded only after a click, by a signed-in user, from an authenticated API that answers with `Cache-Control: no-store` and `X-Robots-Tag: noindex, nofollow, noarchive`; the card carries `data-nosnippet`; never on the public share page or OG cards. |
| No AI or machine-learning use | Tripadvisor content never reaches an LLM: not chat, agents, the stress test or anything else. A test fails if any LLM entry point is called during a lookup. |
| Review text must not be in the page source | Reviews and photos are not fetched at all. |

## Budget

Discover bills per **billable entity**: one per location ID returned by search, nearby and multi-get; one per reviews or photos call; 4xx/5xx responses are not billed. The first 1,000 entities are free once per account lifetime, then about $0.015 each.

The app keeps a hard cap in SQLite (`api_budget`, row `tripadvisor`: `used`, `cap`, `warned_at`, `exhausted_at`), so it survives restarts and is included in the VM backup (every non-place table is).

- **Reserve, then refund.** Before a call, the app reserves the most entities the call can bill, inside `BEGIN IMMEDIATE`, so concurrent requests can never take more than the cap between them. Near the cap, the reservation shrinks the request (a smaller `size`, fewer IDs). After the response it refunds what was not billed: fewer IDs returned, any 4xx/5xx, or a connection that never opened. A timeout after the request was sent keeps the reservation, since it may have been billed.
- **Cap.** `TRIPADVISOR_BUDGET_CAP` (default 1000). At the cap no call is made and the endpoint answers `{"status": "paused"}`; the card says "Tripadvisor ratings are paused right now."
- **Owner notice**, once per cap value at 80 % (800 of 1000) and once at the cap:
    - a `WARNING` log line `tripadvisor_budget level=warn|exhausted used=N cap=M`;
    - an email to `ADMIN_EMAIL` (else the seeded admin account's email) when `SMTP_HOST` is set;
    - `GET /health` reports `tripadvisor: {configured, enabled, used, cap, paused}` and `tripadvisor_budget_ok` (false from 80 % on), so an uptime check can content-match `"tripadvisor_budget_ok":true` (see [Deployment on GCP](Deployment-GCP.md#tripadvisor-ratings));
    - the admin page's Analytics tab shows used / cap.
- **Resuming.** Add payment details in the Terra dashboard, raise `TRIPADVISOR_BUDGET_CAP` and restart the app. A new cap value re-arms both notices.

The counter is the app's own conservative count; Terra's dashboard is the billing source of truth.

## API

### POST /api/tripadvisor/attractions

Signed-in users only (`401` otherwise); bucket `tripadvisor` (`RATE_LIMIT_TRIPADVISOR`, 10 per 10 minutes); `404` when the feature is off.

```json
{"destination": "Paris"}
```

→ `200`, with `Cache-Control: no-store` and `X-Robots-Tag: noindex, nofollow, noarchive`:

```json
{
  "status": "ok",
  "items": [
    {
      "id": 188757,
      "name": "Louvre Museum",
      "rating": 4.5,
      "rating_image_url": "https://www.tripadvisor.com/img/…/4.5-….svg",
      "num_reviews": 123456,
      "ranking": "#3 of 3,000 things to do in Paris",
      "category": "Art Museums",
      "web_url": "https://www.tripadvisor.com/Attraction_Review-…",
      "photos_url": "https://www.tripadvisor.com/…",
      "write_review_url": "https://www.tripadvisor.com/UserReview-…"
    }
  ],
  "attribution": {"name": "Tripadvisor", "logo_url": "https://static.tacdn.com/img2/brand_refresh/Tripadvisor_lockup_horizontal_secondary.svg"}
}
```

`status` is `ok`, `empty` (no attractions found) or `paused` (budget cap; `items` empty). Errors: `422 unknown_destination` (no point for that destination; no call made), `502 tripadvisor_unavailable` (Terra failed; not billed), `429` rate limit.

Clients must keep the answer in memory only and show it with the logo and links as above.

### GET /api/admin/tripadvisor/budget

Admin only: `{"enabled", "configured", "used", "cap", "warn_at", "paused", "exhausted_at"}`.
