# Phase 4 follow-ups

Shipped: share model and routes (`/api/shares`), OG page and PNG cards, Caddy crawler route, ShareDialog, entry points (plan, recap, savings), public page kinds, My shares, `docs/Sharing-API.md`. Flag `SHARING_V2_ENABLED` is now on by default.

## Owner
- Set `PUBLIC_BASE_URL` in production (`app.env`) so OG URLs and share links use the public host; without it the request origin is used.
- After the first real share, paste a link into the WhatsApp, X, Facebook and LinkedIn debuggers to confirm previews (needs the live VM; the Caddy route was validated only with `caddy validate` and a local container).
- Native-speaker review of the `share` namespace in hi, bn, zh (model-translated).
- Instagram Stories needs the Meta App ID, TikTok Share Kit needs a developer app: both belong to the iOS/Android phases.

## Deferred scope
- Quiz-score share (no quiz until Phase 5) and status share ("Day 3 in Lisbon" stays a native text share).
- Android and iOS adopt `docs/Sharing-API.md` (Feature-Parity rows say planned).
- Card text is English; non-Latin headlines fall back to English because the default font lacks glyphs. Bundle a Noto subset to localise cards.
- PlanViewModal keeps its old inline share button.
- The public page showed an empty flight row for synthetic data (E2E note); recheck with real data.
- `GET /api/config` is cached 5 min, so a flag-off window keeps the new dialog briefly (it shows a generic error on 404).
- Recap stats count planned, not visited, items.
- Share views are not counted by design; add privacy-safe aggregate counts only if wanted.
- IPv6 /64 keying now applies to all anonymous rate limits (watch for shared-NAT false positives).
- The origin scrub also drops a destination equal to the origin string.
- Card images stay cached up to 5 min after revoke (documented).
