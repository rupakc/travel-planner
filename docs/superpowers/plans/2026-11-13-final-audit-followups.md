# Final requirements audit: parked items (2026-11-13)

Everything not done in the final pass, with the reason. Done items are in the PRs web #203-#213 and Android #117-#123.

## Owner-blocked (config-gated, inert, tested with fakes)
- OAuth app credentials: Google, Facebook, GitHub, Apple (buttons show "coming soon" until `/api/auth/providers` says configured).
- SMTP sender plus `SIGNUP_ENABLED=true` (sign-up, verify, reset, digest and alert email).
- `SERPAPI_KEY` (live prices, one-tap watch, suggestions; `503 live_prices_off` without it).
- Android release keystore and `assetlinks.json` with its SHA-256 (APKs are debug-signed; app links open via chooser until then).
- Apple Developer account (iOS app, APNs key), optional `PUBLIC_BASE_URL` / custom domain, Meta App ID / TikTok app for Stories/Share Kit (iOS).

## Parked by ruling
- Android on-device arrival (geofence) recommendations: needs background location; Play data-safety and battery cost; the opt-in Near-me-seeded local notification stays.
- Weather-change push for today's outdoor slots: needs a polling weather source outside the free-tier budget.
- Android Deal hunter progress track, Trips-hub bucket ring, passport-stamp animation and confetti (cosmetic).
- Scratch map is a country/flag list on both clients (no drawn map); home-tab section customisation not built.

## Backend items skipped (W6 triage, see PR #207)
- Grouped push `data.kind` for mixed groups (needs to know how Android uses it).
- Claim-before-send message loss (needs a retry/ack protocol).
- Save/unsave/save plan cap (unsave semantics are in the frozen Social-API).
- Restricted users can like/follow/report (product ruling).
- `for_you` cursor (keyset over a time-dependent score), `quiz_sessions` pruning (retention decision plus migration).
- Phase 6 `_candidates` column trim (needs a downstream audit).

## Other
- Share card images are English-only and non-Latin headlines fall back (bundle a Noto subset in `services/share_card.py`).
- Native-speaker review of hi / bn / zh and of the alert-text catalogue (`alert_text_catalog.py`).
- Quiz reminder candidate query is `LIMIT 1000` ordered by id with no rotation; add rotation past 1000 active players.
- Android: `TpTab` / `TpDropdownMenuItem` lack an `interactionSource` parameter; about 125 tids use a file-name fallback and shared row composables give every caller the same tid (route tells them apart).
- Android registry snapshot is a hand-synced copy of the web registry (regenerate when the registry changes).
- Android tests missing for the `playGraph` nav deep link and the `TravelApp` `onOpenPlay` wiring.
- Web: `docs/Feature-Parity.md` iOS cells for two rows are left to the iOS controller.
- Web has no Android-style refresh-token families, so the sessions list mostly shows mobile sign-ins.
