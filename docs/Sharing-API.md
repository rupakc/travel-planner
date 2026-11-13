# Sharing API

> Frozen with Phase 4. **Changes:** later changes are additive only (new fields, endpoints, kinds, options or error codes; nothing renamed, removed or re-typed). Every change needs a contract-change note in its PR and an update to this page in the same PR.

Share links 2.0 turns a plan, a trip recap or the price-alert savings tally into a **share link**, a **share card** (a PNG drawn by the server) and a **public page** whose Open Graph tags give a proper preview on X, Facebook, WhatsApp, LinkedIn and chat apps. The sharer chooses what is revealed, and can list and revoke links. The old `POST /api/plans/{id}/share` and its tokens are unchanged and keep working (see Legacy links).

## API contract

All paths are under `/api`. JSON in and out, except the page (HTML) and the card (PNG). Management routes need `Authorization: Bearer <access_token>` and act only on the caller's shares. Errors use the Phase 1 envelope `{"detail", "error_code"}`; timestamps are ISO 8601 UTC. Routes that depend on the flag answer `404` when `SHARING_V2_ENABLED` is off.

### Discovery (additive)

`GET /config` gains `features.sharing: 0 | 1` (`1` when `SHARING_V2_ENABLED` is on). Clients show the new share flow only when it is `>= 1`, and otherwise keep the legacy plan share (a backend without the field is the same as `0`).

### POST /shares

Auth, bucket `share_manage`.

```json
{"kind": "plan", "plan_id": 12,
 "options": {"dates": "hidden", "show_origin": false, "show_name": false},
 "locale": "en"}
```

- `kind`: `plan` (a plan, covers its itinerary), `recap` (a trip's memories recap) or `savings` (the price-alert savings tally). `plan_id` is required for `plan` and `recap` and ignored for `savings`. **Added in Phase 5 (additive):** `quiz` (extra request field `session_id`: the caller's *finished* quiz session, `404 session_not_found` otherwise; `404 play_disabled` while Play is off; idempotent per session; the card is the pack and correct answers out of the total, e.g. `Flags quiz: 4/5`, never time, points or answers) and `status` (optional `plan_id`: an active, on-the-road trip of the caller, else the caller's first active trip; `422 no_active_trip` when there is none; the card is `Day N in Place` from server data and the link answers `404` once the trip is over). Neither carries `search_data`/`selections`; both return a `card` like `recap`, and the name is shown only with `show_name`. More kinds may be added later; clients treat an unknown `kind` as a plain link.
- `options` (all optional, private defaults shown): `dates` is `hidden | month | exact`; `show_origin` and `show_name` are booleans. Any other value falls back to the private default.
- `locale` (optional, at most 8 characters): the language of the server-rendered page (`en es de fr hi zh bn`; anything else is English).
- **Idempotent** per (user, kind, `plan_id`): a second call returns the same token and **replaces** its options.

Answer `200`:
```json
{"token": "…", "kind": "plan", "url": "https://host/share/<token>",
 "card_url": {"link": "https://host/api/share/<token>/card.png?size=link",
              "story": "https://host/api/share/<token>/card.png?size=story"},
 "options": {"dates": "hidden", "show_origin": false, "show_name": false},
 "created_at": "…Z"}
```
URLs are absolute: `PUBLIC_BASE_URL`, else the request's own base URL; the page's Open Graph URLs use the same rule.

Errors: `404 sharing_disabled`, `404 plan_not_found` (missing or not the caller's plan), `422 invalid_kind`, `429` (rate limit).

### GET /shares

Auth, `share_manage`. The caller's own shares, newest first, at most 100:
```json
{"shares": [{"token": "…", "kind": "plan", "title": "Lisbon in May", "url": "…",
             "options": {"dates": "hidden", "show_origin": false, "show_name": false},
             "created_at": "…Z"}]}
```
`title` is the plan's name (`Price alerts` for `savings`). Each row (and the `POST /shares` answer) also carries an additive `plan_id` (int, or `null` for `savings`). Additive field `legacy_plan_shares: [{"plan_id", "name", "url"}]` lists the caller's plans that still have a legacy share token (`url` is `<base>/share/<token>`; the token is exposed nowhere else). Errors: `404 sharing_disabled`.

### DELETE /shares/{token}

Auth, `share_manage`. Revokes the share: `204` with no body. The public routes answer `404` at once and the rendered card is dropped from the server cache. `404 share_not_found` when the token is not the caller's, and `404 sharing_disabled`. Revoking a legacy plan token is still `DELETE /plans/{id}/share`.

### GET /share/{token}

Public (no auth), bucket `share_public`, per client IP. Answers for both token kinds:

- A **legacy plan token** answers exactly as before: `name`, `created_at`, `updated_at`, `search_data` (whitelisted fields), `selections`.
- A **Phase 4 token** answers the same keys with the sharer's options applied, plus:
  - `kind`, `options` (the three options; no `locale`);
  - `owner_name`, only with `show_name`;
  - for `recap` and `savings`, `card`: `{"headline", "stats": [{"key", "count"}], "destination"?, "period"?}`. For `savings`, `search_data` and `selections` are empty objects and `name` is `Price alerts`.

`404` (`{"detail": "Shared plan not found"}`) for an unknown or revoked token, or while the flag is off for a Phase 4 token.

### GET /share/{token}/page

Public, `share_public`. Server-rendered HTML for link-preview crawlers: `<title>`, `description`, `og:type/site_name/title/description/image/image:width/image:height/url`, `twitter:card=summary_large_image` (+ title, description, image), `<meta name="robots" content="noindex, nofollow">`, a heading, and a link to the SPA page `/share/<token>`. `og:image` is the absolute `card.png?size=link`. There is no inline script and no tracking. Headers: `X-Robots-Tag: noindex, nofollow`, `Cache-Control: public, max-age=300`. `404 share_not_found` (a JSON error, no tags) for an unknown, revoked or disabled share; only Phase 4 tokens have a page (a legacy token answers `404`, and the SPA serves it as before).

Native clients do not need this route: it exists for crawlers (see Crawlers and Open Graph).

### GET /share/{token}/card.png?size=link|story

Public, `share_public`. A PNG: `size=link` is 1200x630 (the default, used by `og:image`), `size=story` is 1080x1920. Headers: `Content-Type: image/png`, `X-Robots-Tag: noindex, nofollow`, `Cache-Control: public, max-age=300`. `404 share_not_found` for an unknown or revoked token; `422` for another `size`. `503 card_busy` when too many cards are rendering at once (retry). One renderer serves every client, so web, iOS and Android show identical cards. Clients show or save the image as is and add their own caption and link.

**Languages (additive).** `?lang=en|es|de|fr|hi|zh|bn` renders the card in that language (headline, month, chips, "by"/"from"). Omitted, the share's own `locale` option is used, else English. A regional code (`es-MX`) is reduced to its language; an unknown value falls back to English (never a 4xx). Fonts are bundled OFL Noto subsets (`backend/app/assets/fonts`, rebuilt by `backend/scripts/build_card_fonts.py`). Devanagari and Bengali need libraqm (Pillow's wheel bundles it; the image installs `libfribidi0`); where raqm is missing, `hi`/`bn` cards are drawn as the English card. User text with a glyph the fonts lack (for example a Greek place name) is left out of the card rather than drawn as a box. The cache is keyed per language.

## Card and snapshot fields

The page and the card are drawn from one snapshot built from a whitelist (`services/share_public.py`); it never holds exact dates.

| Field | Meaning |
|---|---|
| `headline` | `7 days in Lisbon`, `Trip to Lisbon`, `My trip to Japan: recap`, `Caught drops worth $412`, or the plan name when there is no destination. A headline with glyphs the card font lacks (CJK, Devanagari, Bengali) falls back to a plain English one on the PNG. |
| `destination` / `destinations` | Up to 5 destination names (joined with ` / `). |
| `days` | Trip length from the dates, else from the itinerary; `null` when unknown. |
| `stats` | At most three chips of **counts only**: plan `activities`, `hotels`, `places`; recap `places`, `activities`; savings `drops_caught`, `targets_hit`. Zero counts are omitted; labels are singular for 1 (`1 hotel`). |
| `period` | `YYYY-MM`, only when `options.dates` is `month` or `exact`. |
| `origin` | Only with `show_origin`. |
| `owner_name` | Only with `show_name` (the display name, else the username; never an email: a name containing `@` is dropped). |

## Privacy defaults and the date scrub

A new share reveals only the title, destination(s), number of days and the plan's selections. Everything else is opt-in:

- `dates`: `hidden` (default) removes `departure_date` and `return_date` from `search_data` and scrubs the selections; `month` cuts every date to `YYYY-MM`; `exact` leaves the dates and selections as saved.
- `show_origin`: without it `origin` is removed from `search_data`.
- `show_name`: without it there is no `owner_name` anywhere.
- `search_data` is a whitelist (origin, destination(s), dates, interests, traveller counts, pace). Email, nationality, visas, permits, accessibility needs and the raw search request are never exposed.
- **Selections scrub** (`hidden` and `month`): any key whose name looks like a date or time (`date`, `time`, `departure`, `arrival`, `check_in`, `check_out`, …) is removed, and so is any string value that is an ISO date or datetime. With `month`, ISO date values become `YYYY-MM` and date-named keys keep that month. Prices and counts are untouched.
- **Always removed from new shares (every date mode):** owner-private free text (`itinerary_notes`, `itinerary_edits` and any `notes` field). Without `show_origin`, origin keys (`origin`, `leg_from`, ...), a return leg's destination and flight booking links are removed from selections in every date mode, including `exact`.
- **Dates in strings (`hidden`, `month`):** URL values that carry a date (`flt=...2026-05-01`, `checkin=`, ...) are dropped; an ISO date inside any other string drops the value (`hidden`) or becomes `YYYY-MM` (`month`). `time_of_day` and `duration*` keys are kept.
- **Timestamps:** `created_at` / `updated_at` of a new share are `null` with `dates=hidden`, `YYYY-MM` with `month`, as saved with `exact`. New plan shares may carry the whitelisted `search_data.import_source` (`{url, title}`) like legacy ones. A `recap` answers with empty `search_data` and `selections` (only `card`).
- **Plan names** are truncated to 200 characters on save; card headlines to 120.
- **Open Graph tags and the card show at most the month and year**, even with `dates=exact`.
- No XP, badge or other reward is given for sharing, and views are not counted (no tracking of visitors; the web app sends a `share_view` telemetry event, enum props only).

## Crawlers and Open Graph

Production Caddy serves the SPA at `/share/<token>`. A request whose `User-Agent` matches the fixed crawler list (facebookexternalhit, Twitterbot, WhatsApp, LinkedInBot, Slackbot, Discordbot, TelegramBot, Pinterest, Skype, Embedly, Googlebot, Bingbot, Applebot, iMessage, Redditbot, Mastodon) and whose path is `/share/<8 to 64 URL-safe characters>` is rewritten to `/api/share/<token>/page`. People get the SPA as before. If the app answers `4xx` or `5xx` (revoked share, flag off, an older build without the route) Caddy serves the SPA `index.html` instead, so a link never breaks. Both images ship independently, so either order of deploy is safe. The absolute URLs in the tags come from `PUBLIC_BASE_URL`, else the request's base URL (behind Caddy that is the public host). Search engines are told not to index: the page, the card and every public share answer carry `noindex`.

## Rate limits

Buckets per 10 minutes, in-process sliding window: `share_public` (default 120, per client IP, IPv6 clients keyed by /64: `GET /share/{token}`, `/page`, `/card.png`) and `share_manage` (default 30, per signed-in user: `/shares` create, list, revoke). Over the limit: `429` with `Retry-After` and a string `detail`. Settings `RATE_LIMIT_SHARE_PUBLIC`, `RATE_LIMIT_SHARE_MANAGE`.

## Caching and revocation

Rendered cards sit in a small in-process TTL cache (64 entries, 10 minutes) keyed by token, size and content; revoking clears the token's entries and every public route answers `404` immediately. The one residual exposure is the HTTP cache: `Cache-Control: public, max-age=300` means a browser, proxy or link-preview service that already fetched a page or card may keep showing it for up to five minutes (and previews that chat apps stored on their side can last longer; a revoked link cannot be recalled from them). Treat a revoked share as "stops working within minutes".

## Legacy links

`POST /plans/{id}/share` (no body, `{"share_token"}`), `DELETE /plans/{id}/share` and the legacy tokens keep their request and response shapes, and `GET /share/{token}` answers them byte for byte as before; they ignore the options above (dates and origin are as the legacy whitelist). New clients should use `POST /shares` when `features.sharing >= 1`.

## Quiz and status shares (Phase 5)

Nothing is deferred for Phase 5: `kind: "quiz"` (`session_id`, the caller's finished quiz session; the card shows the pack and score out of 5, never time or answers) and `kind: "status"` (`plan_id`, an active trip of the caller; `422 no_active_trip` otherwise; the card reads "Day N in Place") are served additively, see [Social and Play API](Social-API.md).
