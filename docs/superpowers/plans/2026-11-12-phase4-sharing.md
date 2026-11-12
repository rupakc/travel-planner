# Phase 4 — Sharing Implementation Plan

> **For agentic workers:** use superpowers:subagent-driven-development. Steps use `- [ ]` checkboxes.

**Goal:** Any plan, trip recap or savings tally becomes a **share card** (link size 1200x630, story size 1080x1920) plus a **public page** whose Open Graph/Twitter tags make previews right on X, Facebook, WhatsApp, LinkedIn and chat apps. The sharer picks what is revealed. Links can be listed and revoked.

**Spec:** `docs/superpowers/specs/2026-11-10-voyager-reimagined-design.md` §5 "Sharing", §5a (Memories, Price alerts rows), §8 telemetry, §2a `PUBLIC_BASE_URL`.

## Owner-question rulings (main controller, 2026-11-12)

1. **Privacy defaults.** A new share reveals only: trip title, destination(s), number of days and the plan's selections. Hidden unless the sharer ticks them: exact dates (`dates`: `hidden` default, `month`, `exact`), origin (`show_origin`), traveller display name (`show_name`). Email, nationality, visas, permits and accessibility are never exposed. OG tags and OG images show at most the month and year, even when `dates=exact`.
2. **Legacy links keep working.** The old `POST /plans/{id}/share` (no body) and its tokens behave as today, because the previous SPA and the apps rely on them. New shares come from `POST /api/shares`, which always applies the options. `GET /api/share/{token}` answers for both kinds of token.
3. **Crawler pages.** Caddy serves the SPA, so crawlers (User-Agent match on a fixed list) asking for `/share/<token>` are proxied to the app's `GET /api/share/{token}/page`, a small server-rendered HTML page with OG/Twitter tags, `noindex`, and a link into the SPA. People get the SPA as before. If the app answers 4xx/5xx or is an older build, Caddy falls back to the SPA `index.html`. No inline script anywhere (CSP).
4. **One renderer for cards.** The server draws the PNG (Pillow, no new dependency) at `GET /api/share/{token}/card.png?size=link|story`, so web, iOS and Android show identical cards and OG images use it. Rendered PNGs sit in a small in-process TTL cache.
5. **Kinds in this phase:** `plan` (covers itinerary), `recap`, `savings`. **Deferred:** quiz score (no quiz until Phase 5) and status (ephemeral "Day 3 in Lisbon" stays a native text share). Both are in the follow-ups.
6. **No XP for sharing.** Raw volume earns nothing (§5a guardrail). The Memories (recap) and Price-alerts (savings card) touches already exist, so the sharing "gamified touch" is the card itself. Sharing never gates a feature and `hide_game` is untouched.
7. **Search engines.** Every public share page and image sends `X-Robots-Tag: noindex` and `<meta name="robots" content="noindex">`.
8. **Rollout.** Flag `SHARING_V2_ENABLED` (default `false`, switched to `true` in the last task if safe). Off: `/api/shares*`, `/page`, `card.png` answer 404 and `features.sharing` is 0; the SPA keeps the old share button.
9. **Revocation.** Revoke deletes the row (or clears the legacy token); the public routes then 404 at once. Cached PNGs are keyed by token and the cache is cleared for that token on revoke; `Cache-Control: public, max-age=300` is the only residual exposure and is documented.
10. **Views are not counted** (no tracking of anonymous visitors). Telemetry `share_view` fires from the SPA only, with the kind.

## Global constraints

- Two-way compatibility (CLAUDE.md): no existing route changes shape; every new field is additive; the new SPA feature-detects `features.sharing >= 1` from `GET /api/config` and otherwise keeps the old share flow. Schema: `CREATE TABLE IF NOT EXISTS` only; the new table joins the GCS user-table backup set (follow how Phase 3 added `alerts_*` tables).
- Public output exposes nothing private: all text is HTML-escaped; no email; names only with `show_name`; never raw `search_data`, only the whitelist. Add tests that feed hostile names (`<script>`, quotes) and assert escaping.
- Rate limits (new buckets, settings `RATE_LIMIT_SHARE_PUBLIC` 120 and `RATE_LIMIT_SHARE_MANAGE` 30 per 10 min): public routes by client IP, `/api/shares*` by user. Document in docs/Configuration.md. Tests run with limits off, so add one test that enables them.
- i18n: all new strings in 7 languages in one new namespace `share` (server-rendered page text and card text are English plus the sharer's `locale`, see Task 2). `catalog.test.js` passes. Informal es/de, `vous` in fr.
- Telemetry: new events in `telemetry/registry.py` and `docs/Telemetry.md` (registry test): `share_open` (`kind`), `share_create` (`kind`, `dates`), `share_action` (`kind`, `target`: native, copy, download, x, facebook, whatsapp, linkedin), `share_revoke` (`kind`), `share_view` (`kind`). Props are enums only. Every control carries `data-tid`.
- Theme tokens, no hard-coded colours (cards drawn on the server use a fixed brand palette from `frontend/design/tokens.json` values copied once into the renderer, with a test that they match the token file).
- Python 3.12, `ruff check backend/`, `cd frontend && npx eslint src/ --max-warnings 0`, `mkdocs build --strict`, backend and frontend suites green.

## API contract (docs/Sharing-API.md, additive-only after Task 9)

All under `/api`, JSON, errors `{"detail","error_code"}`. `GET /config` gains `features.sharing: 0|1`.

- `POST /shares` (auth, `share_manage`): `{"kind":"plan"|"recap"|"savings","plan_id":int?,"options":{"dates":"hidden|month|exact","show_origin":bool,"show_name":bool},"locale":"en"?}`. `plan_id` required for plan and recap (404 `plan_not_found` if not the caller's). Idempotent per (user, kind, plan_id): returns the existing share and updates its options. Answers `{"token","kind","url","card_url":{"link","story"},"options","created_at"}`. 404 `sharing_disabled` when the flag is off. 422 `invalid_kind`.
- `GET /shares` (auth): `{"shares":[{token,kind,title,url,options,created_at}]}`, newest first, max 100.
- `DELETE /shares/{token}` (auth): 204, 404 `share_not_found` if not the caller's.
- `GET /share/{token}` (public, `share_public`): existing shape for plan tokens (`name, created_at, updated_at, search_data, selections`) plus, for new shares, `kind`, `options`, `owner_name` (only with `show_name`), and for recap/savings a `card` object (`headline`, `stats[]`, `destination?`, `period?`). 404 for unknown or revoked.
- `GET /share/{token}/page` (public): HTML with OG/Twitter tags (`og:title`, `og:description`, `og:image` = absolute `card.png?size=link`, `og:url`, `twitter:card=summary_large_image`), `noindex`, `<a href=/share/token>`.
- `GET /share/{token}/card.png?size=link|story` (public): PNG, `Cache-Control: public, max-age=300`, `X-Robots-Tag: noindex`.

Card content: brand line, headline (`7 days in Lisbon`, `My trip to Japan: recap`, `Caught drops worth $X`), up to three stat chips (counts only: activities, hotels, places; recap: places visited, countries; savings: drops caught), month and year only when `dates` is not `hidden`, the sharer's display name only with `show_name`. Plan card never includes origin unless `show_origin`.

## Tasks (each its own PR; 3 waves)

Wave A (parallel): T1, T3. Wave B: T2 (needs T1), T4 (needs T1 contract only). Wave C: T5, T6, T7 after T4. Then T8 (docs), T9 (switch on).

### Task 1 — Backend share model and routes (haiku-sized plan, sonnet implements)
Files: `backend/app/db/shares_db.py` (new, table `shares(token PK, username, kind, plan_id, options_json, created_at)`, index on username, plan), `backend/app/services/share_public.py` (pure: build the public snapshot from a plan or savings summary + options; whitelist; date policy), `backend/app/api/routes/shares.py`, config flag + buckets, `client_config.py`, `main.py` wiring and backup set, extend `GET /share/{token}` in `plans.py` to fall back to `shares`.
- [ ] Failing tests first: `tests/test_shares_api.py` (create/list/revoke, idempotent, not-yours 404, flag off 404, options privacy: default hides dates/origin/name; `exact` returns dates; `show_name` adds owner_name; legacy token path unchanged byte-for-byte; revoked 404; hostile names stored raw but JSON-safe; rate limit test), `tests/test_share_public.py` (pure snapshot cases).
- [ ] Implement, ruff, full backend suite, PR, `gh pr checks --watch --fail-fast`, merge.

### Task 2 — OG page and card renderer
Files: `backend/app/services/share_card.py` (Pillow draw, `render(snapshot, size) -> bytes`, TTLCache 64 x 10 min, `invalidate(token)`; use `ImageFont.load_default(size=)`; wrap text; a CJK/Devanagari/Bengali headline falls back to the plain English headline, since the default font lacks those glyphs), routes `/share/{token}/page` and `/share/{token}/card.png` in `shares.py`, `public_base_url` fallback to the request origin, `tests/test_share_page.py`, `tests/test_share_card.py` (valid PNG, exact size 1200x630 and 1080x1920, deterministic, no date text when hidden: assert via the snapshot passed to the renderer, not OCR).
- [ ] Tests (escaping, tags present and absolute, noindex headers, 404 without tags for revoked, month-only even when exact, cache invalidated on revoke), implement, PR, merge.

### Task 3 — Caddy crawler route (deploy kit)
Files: `deploy/gcp/Caddyfile`, `deploy/gcp/tests/test_caddyfile_spa.py` (extend, follow its style).
- [ ] Matcher `@crawler` (header_regexp User-Agent `(?i)facebookexternalhit|twitterbot|whatsapp|linkedinbot|slackbot|discordbot|telegrambot|pinterest|skypeuri|embedly|googlebot|bingbot|applebot|iMessage|redditbot|mastodon`) combined with `path_regexp share ^/share/([A-Za-z0-9_-]{8,64})$`; `rewrite * /api/share/{re.share.1}/page`; reuse the proxy block; `handle_response` fallback to the SPA index on 4xx/5xx. Add tests: validity (`caddy validate` through the existing harness if present, else the text-level checks the file already uses), the ordering (the crawler handle precedes the SPA handle), crawler UA regex positives and negatives, a browser UA gets the SPA. `shellcheck` unaffected. PR, merge.

### Task 4 — Frontend share foundation
Files: `src/utils/share.js` (`sharingEnabled(config)`, `buildIntent(target,{url,text})` for x/facebook/whatsapp/linkedin, `shareFiles` via Web Share API with feature detection, `cardUrl(token,size)`), `src/services/api.js` (`createShare`, `listShares`, `revokeShare`, `getSharedPage`), `src/components/share/ShareDialog.jsx` (options form, card preview `<img>` from `card_url.link`, actions native/copy/download/intents, revoke; focus trap and Esc like `SavingsShareCard`), i18n namespace `share` x7, registry events, `docs/Telemetry.md`, tests for the util, dialog states (loading, error, copy fallback) and catalog.
- [ ] Failing tests, implement, eslint, `npm test`, PR, merge.

### Task 5 — Entry points
Plan share in Results and Chat My Plan, TripPage, `Recap.jsx` (kind `recap`, replaces its direct `sharePlan` when `features.sharing`), `SavingsTally`/`SavingsShareCard` (adds "Share link" opening the dialog with kind `savings`; the existing canvas card is unchanged). Old backend (`features.sharing` missing/0) keeps the old behaviour. Tests per entry point for both mixes.

### Task 6 — Public page and management
`SharePage.jsx` renders `kind`, shows options only if present, "Plan your own trip" CTA, `share_view` telemetry, an `owner_name` byline only if present, robots `noindex` meta set at runtime. New `components/share/MyShares.jsx` in the Account page (list, copy, revoke with confirm). Tests.

### Task 7 — Parity and unit tests for mixed versions
`docs/Feature-Parity.md` rows (web done, Android and iOS "planned": the contract is the adoption path). Mixed-version tests: new SPA on a backend without `/shares` (404) and without `features.sharing`; old SPA token flow on the new backend (`tests/test_share_legacy_compat.py` if not already in Task 1).

### Task 8 — Docs
`docs/Sharing-API.md` (the contract above, final), `docs/API-Reference.md` rows, `docs/Configuration.md` (`SHARING_V2_ENABLED`, buckets, `PUBLIC_BASE_URL` for OG), `docs/Privacy.md` (what a share reveals), `docs/Deployment-GCP.md` (crawler route), `CLAUDE.md` Sharing paragraph, mkdocs nav, `mkdocs build --strict`.

### Task 9 — Browser E2E, final review, switch on
Local stack with the fake SerpAPI: create a share for each kind, view as an anonymous visitor, fetch `/page` with a crawler UA and `card.png`, revoke and confirm 404, mobile width and dark theme screenshots. One opus whole-branch review, fixes, then `SHARING_V2_ENABLED` default `true`.

## Review focus
1. A hostile trip name in the page, the OG tags and the PNG. 2. Exact dates never reach OG or the card. 3. Revoked token: page, JSON and PNG all 404 and the cache is cleared. 4. Caddy: browsers still get the SPA, crawlers get the page, and an old app build falls back to the SPA. 5. Old SPA and old tokens on the new backend; new SPA on the old backend. 6. Rate-limit keys use the real client IP, not the Caddy address.
