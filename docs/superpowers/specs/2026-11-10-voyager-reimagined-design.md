# Voyager reimagined — whole-journey redesign, iOS app, accounts, social, telemetry (program design)

Status: design for the program. Each phase below gets its own implementation plan
(`docs/superpowers/plans/`) and ships as its own PRs. Owner's brief: 2026-11-10 (20 points, summarised in §1).
Decisions marked **[call]** are mine (the owner delegated them); everything else is from the brief.

## 1. Intent

Turn Voyager from "a search that produces a plan" into a companion for the **whole trip**:
*before* (dream, plan, book-watch, prepare), *during* (today, nearby, money, safety) and *after*
(recap, memories, share, where next). It has the same experience on **web, Android and a new native iOS app**.
The brief puts user experience first: fast, engaging, interactive, light and pleasant by default with dark mode,
in seven languages.

Success looks like this: a traveller signs up in under a minute with the method they like. They plan a trip
and get a price-drop moment that makes them smile. They use the app every day of the trip, come back afterwards
to relive and share it, and keep returning between trips for quizzes, ideas and alerts.

### Goals (from the brief)
1. Journey-centred redesign of web + Android; native iOS (iPhone + iPad) in its own repo with its own CI.
2. Sign-in: Google, Facebook (Meta), GitHub, and native username/email/password. Native sign-up sends a
   confirmation email valid **30 minutes**; the link activates the account and lands in the app. Forgotten-password reset.
3. Account area: avatar + name, settings and preferences, feature toggles and customisation.
4. Share plans, itineraries and status to Instagram, TikTok, X, Facebook and others.
5. Immersive, localised, push-based recommendations (mobile first).
6. Price alerts that delight and engage.
7. Gamification + social: share travel ideas, interact, quizzes, points.
8. Thorough telemetry for every interaction on all three clients, with zero UX cost.
9. Identical onboarding on all three clients.
10. Languages: English, Spanish, German, French, Hindi, Chinese (Simplified), Bengali.
11. Light theme by default; user-toggled dark mode.

### Non-goals
- Booking or payments inside the app (we link out; no PCI scope).
- Photo hosting (the e2-micro has a 30 GB disk). Photos stay on the device; recaps render on the device.
- Real-time chat between users (DMs). Social means public ideas, comments, follows, likes and quizzes.

### Anti-goals (shipping these counts as failure even if it "works")
- Anything that slows first paint, typing, scrolling or streaming. Telemetry, social and gamification are all
  off the critical path.
- Dark patterns: forced sharing, fake urgency, fake price drops, points for spam.
- Breaking the existing honesty rules (observed versus estimated prices, verification badges, static-first data).
- Breaking the deploy contract: backend changes are additive; old SPA ↔ new app and new SPA ↔ old app both work.

## 2. Constraints

- **Infra**: one always-free e2-micro (1 GB RAM, shared vCPU), SQLite, Caddy, AI behind a GCP spend cap.
  New features must fit, so there is no new database server, queue or paid service unless the owner adds one.
- **Two-way compatibility** (CLAUDE.md): new endpoints are feature-detected by clients. Nothing gets removed or
  renamed without a deprecation step. Mobile apps in the field lag even further, so the same rule applies to them.
- **Self-registration opens the AI to strangers.** The spend cap stays. **[call]** Add per-user daily AI quotas
  on top of the 10-minute windows. Unverified accounts cannot run AI.
- **Store rules that shape the design** (verified requirements, not preferences):
  - App Store 4.8: an app offering third-party social login must also offer an equivalent privacy-focused login.
    **[call]** Add **Sign in with Apple** on iOS, and on web/Android too so one account works everywhere.
  - App Store 5.1.1(v) and Google Play: an app with in-app sign-up must offer **in-app account deletion**.
  - App Store 1.2 / Play UGC policy: user-generated content needs **report, block, filtering and a moderation
    queue**. These are part of the social phase, not an add-on.
  - Privacy labels (App Store) and Data safety (Play) must declare the telemetry we collect.
- **Instagram login** for personal accounts is not available. Meta retired the Instagram Basic Display API on
  2024-12-04, and Instagram Login now serves only business/creator accounts. **[call]** "Continue with Facebook"
  covers Meta. Instagram stays a *sharing* target.
- **Telemetry and the law.** The brief says users should not be aware of telemetry. **[call]** Telemetry is
  *invisible in the experience* (no lag, no nagging, batched in the background). It is **not undisclosed**:
  it appears in the privacy policy and store labels, can be switched off in Settings → Privacy, and EU/UK users
  get a one-time consent choice as ePrivacy/GDPR require. Collecting it secretly would expose the owner to
  GDPR fines and app-store removal. No cross-app tracking, so there is no App Tracking Transparency prompt.
- **Things only the owner can provide.** Every feature that depends on them is config-gated and hidden until
  configured, the same pattern as `SERPAPI_KEY`:
  Google OAuth client, GitHub OAuth app, Meta app (Facebook Login + Instagram Stories sharing),
  Apple Developer Program (Sign in with Apple, APNs, TestFlight/App Store), an SMTP sender,
  optionally a TikTok developer app (Share Kit), and Xcode installed locally (optional; CI builds on macOS runners).

## 2a. Owner decisions (2026-11-10)

- **Domain**: build on the current sslip.io host for now (a limited product–market-fit run with selected
  users). Make a later move to a custom domain a config change:
  - One setting, `PUBLIC_BASE_URL`, drives every absolute URL: OAuth redirect URIs, verify/reset links, share
    pages, OG tags, emails and the Caddy site host.
  - `GET /api/config` reports the canonical base URL. The mobile apps read it at startup and use it for API
    calls once it's served from a host they already trust.
  - Universal links / app links are declared for a list of hosts in one build setting per app, so adding the
    new domain is one line plus a store update. Old sslip.io links keep redirecting.
  - A runbook section in `docs/Deployment-GCP.md` lists the switch steps (DNS, `SITE_HOST`, provider consoles,
    AASA/assetlinks).
  - Known limitation until then: Google OAuth may refuse an sslip.io redirect URI. If it does, Google sign-in
    stays hidden until the domain exists; GitHub, Facebook and native sign-in are unaffected.
- **Budget**: stay on free tiers. Price alerts must fit SerpAPI's 250 searches/month: watches are prioritised
  (nearest departure, closest to target), re-check intervals adapt, and every price shows an honest
  "checked N days ago" label. One-tap watch and suggestions never fire a live search by themselves. AI gets strict
  per-user daily quotas, and moderation uses the cheapest model only on posts that the keyword filter can't
  decide.
- **Sign-up mode [call]**: `SIGNUP_MODE=open|invite` (default `open`, per the brief). For a PMF cohort the owner
  can switch to invite codes without a deploy of new code.

## 3. The journey (information architecture, same on all clients)

Bottom tabs on mobile, top nav on web; on iPad and wide web, a sidebar:

| Tab | Purpose |
|---|---|
| **Trips** (home) | Every trip as a card in its phase: *Dreaming → Planning → Ready → On the road → Memories*. The current or next trip is pinned at the top with a phase-aware "what now" panel. |
| **Explore** | Search / chat / compare / from-a-link / surprise-me (existing modes, one entry point), plus the community ideas feed. |
| **Alerts** | Price watches with a live price story (see §6). |
| **Play** | Daily quiz, challenges, badges, level, leaderboard, scratch map of countries. |
| **You** | Avatar, name, profile, settings, preferences, privacy. |

A trip's phase follows its dates (the user can override it). Each phase changes the trip screen:

- **Before**: plan (existing results + My Plan), a countdown, a **prep checklist** built from existing data
  (visa lead time, packing list, SIM, forex, emergency card, documents, insurance reminder), price watches,
  a pre-trip stress test, and share the plan.
- **During**: a **Today** view (today's slots with derived times, next-up card, walking directions out to
  maps apps), Near me (existing `/nearby`), an offline pack (emergency card, phrases, address card in the local
  script, currency converter with the last-known rate), an expense log, and status sharing ("Day 3 in Lisbon").
- **After**: an auto-generated **recap** (route map, days, places, distance, countries, spend versus budget),
  place ratings, journal notes, a recap card to share, a scratch-map update + badges, and "where next"
  (existing discovery, seeded from the trip and the Taste Graph).

## 3a. Data model for trips [call]

A **trip is a saved plan** with new nullable columns `phase`, `start_date`, `end_date`, `title`. A Dreaming trip
has no dates. New child tables hold `trip_expenses`, `trip_journal` and `trip_ratings`, keyed by plan id. The old
SPA reads plans exactly as today and ignores the new columns.

## 4. Accounts and identity

- **Native sign-up**: username, email, password (zxcvbn-style strength meter on the client; server minimum
  10 characters, checked against a top-10k common-password list). The account is created `pending`. A verify
  email goes out with a single-use, random 256-bit token (only its SHA-256 stored), expiring 30 minutes after
  issue. The link opens `/verify?token=…`; on web that activates, signs in and redirects into the app. Mobile
  uses universal links / app links for the same URL, so the link opens the app. Resending invalidates the
  previous token, rate-limited. Pending accounts that are never verified are purged after 7 days **[call]**.
- **Password reset**: request by email. The response is identical whether or not the account exists (no
  enumeration). Same token rules, 30 minutes **[call]**. A successful reset revokes the user's other sessions.
- **Sessions [call]**: keep the HS256 JWT but add a per-user `token_version` claim so sessions can be revoked,
  plus a refresh token for mobile so users aren't signed out every 24 h. Existing tokens keep working (a
  missing claim is treated as version 0).
- **OAuth (Google, GitHub, Facebook, Apple) [call]**: a server-side authorization-code flow with PKCE + state.
  Web uses a redirect; mobile uses `ASWebAuthenticationSession` / Custom Tabs with a callback to the app's
  universal link. Email-verified provider identities link to an existing account with the same verified email;
  anything else creates a new account. One user can have several identities (new `user_identities` table).
  `GET /api/auth/providers` lists the configured providers, so clients show only working buttons.
- **Account area**: avatar (provider photo, an uploaded image resized to 256 px WebP and stored on disk under
  2 MB, or generated initials), display name, handle; language, theme (system/light/dark), currency, units,
  home-tab sections and feature toggles (e.g. hide Play, hide community), notification categories + quiet hours,
  privacy (profile visibility, telemetry opt-out), connected sign-in methods, change password, export my data
  (JSON), delete account.
- **Admin-created users keep working.** `is_first_login` keeps its meaning.
- **Identity key [call]**: `username` stays the immutable internal key, so plans, preferences, recent searches,
  taste, feedback and devices need no migration. OAuth sign-ups pick a username once, with a suggestion
  prefilled. The public *display name* can change; the username can't.
- **Account linking [call]**: a provider identity links automatically only to an account whose email **we**
  have verified (new `email_verified` column). Admin-created emails start unverified and are verified by a link
  from the account page. Otherwise linking happens only from the account page while signed in. This prevents
  account takeover by email.

## 5. Social, sharing and gamification

- **Profiles**: public handle, avatar, home country, countries visited (scratch map), level, badges, and
  published ideas. Visibility: public / followers / private.
- **Ideas feed**: publish a plan or a recap as an *idea* (a snapshot copy; private notes and prices are
  optional). Like, save to my trips ("remix", which exists as `utils/remix`), comment, follow. Ranking is
  chronological plus engagement plus taste match, computed in SQLite.
- **Safety**: report (with reasons), block, keyword filter, and a cheap Flash-Lite moderation classification of
  new posts/comments before they go public (a borderline post is held for the admin queue). Per-user posting
  limits. Admin moderation tab.
- **Quizzes**: a daily 5-question quiz plus topic packs (flags, capitals, cuisine, landmarks, etiquette,
  "where is this?"). The question bank is generated offline by script, auto-checked by a second model pass and
  committed as data in seven languages, so a quiz costs **no live AI calls**. Questions and answers are
  validated server-side, timing is scored, and there are streaks.
- **Points (XP) ledger**, append-only with idempotency keys: quiz answers, daily streaks, a completed trip
  recap, published ideas that others save, verified email, and a price watch that catches a drop. Points are
  never awarded for raw volume of posts/likes, so spam earns nothing. Levels, ~30 badges, weekly friends + global
  leaderboards.
- **Sharing**: every plan, itinerary, recap, status, quiz score and price-drop win can become a **share card**
  (1080×1920 story and 1200×630 link sizes) with a link to a public page. That page is server-rendered with
  Open Graph/Twitter tags, so previews look right on X/Facebook/WhatsApp/LinkedIn.
  - Mobile: the native share sheet. On iOS, Instagram Stories through its documented URL scheme (needs the
    Meta App ID); TikTok through Share Kit when configured, otherwise the share sheet.
  - Web: the Web Share API with files where supported; otherwise X/Facebook/WhatsApp/LinkedIn intents,
    copy link and download image.

## 6. Price alerts that delight

Keep every honesty rule. Add:
- A **price story** per watch: sparkline/history, the lowest seen, "typical" range, a target price slider,
  and a plain-language advisor line (existing pricing-advisor). Estimates stay labelled and frozen.
- **A drop moment**: a push/email with the amount and percentage saved; in the app, an animated drop card and
  a "you're saving $X" counter (reduced motion respected).
- A **savings tally** across all watches, a shareable "I saved $X" card, and XP for drops.
- **Smarter watching**: one-tap "watch this" on any flight/hotel/activity/trip card. Smart suggestions on what
  to watch when a plan is saved. A weekly digest (opt-in) instead of noise.
- **Anti-spam**: the existing evaluate() rules plus quiet hours, a per-category daily cap and grouped notifications.

## 7. Immersive notifications

- **Server-sent (FCM for Android as today; direct APNs for iOS: a new sender next to `services/push.py`, and
  `/api/devices` additively accepts `platform: "ios"`)**: price drops, trip
  countdown (T-30 visa check, T-7 packing, T-1 check-in + weather), a morning brief on each trip day, a weather
  change for today's outdoor slots, the daily quiz, and social events (follows, likes, comments, saves).
  Delivery respects categories, quiet hours in the device's timezone, and a global cap (3/day, price drops exempt).
  Text is localised server-side from the same string catalogue.
- **Location-aware recommendations [call]**, computed **on the device**: the app uses significant-location-change
  / geofences (opt-in, explained when asked). On arrival somewhere new during a trip, the app calls `/nearby`
  and shows a local notification ("You're near Belém — Pastéis de Belém is 4 min away"). The server never
  stores a location history, which keeps the privacy labels and the 1 GB box simple.

## 8. Telemetry

- **One event schema for all three clients** (`docs/Telemetry.md`, versioned):
  `{event, ts, session_id, anon_id, user_id?, platform, app_version, locale, screen, props}`.
  Event families: lifecycle (app open/background, session), navigation (screen view + time on screen),
  interaction (tap/toggle/submit, with a stable element id instead of text), search/chat funnel (submit, first
  section, all sections, abandon), section engagement (expand, select into plan, link-out), share, alert,
  social, quiz, onboarding steps, performance (TTFB, time to first section, cold start, frame drops),
  and errors (crashes, API failures).
- **Never collected**: free text the user typed, precise location, email/name in props, other users' content.
- **Zero-cost delivery**: buffered in memory and flushed every 10–20 s or 50 events, on backgrounding, and through
  `sendBeacon` / `BGTaskScheduler` / WorkManager. Persisted offline (IndexedDB / file) with a cap. Sent gzipped.
  The client never awaits it. On the server, `POST /api/telemetry` is a fast append into a **separate SQLite
  file** (`telemetry.db`, WAL) so it never contends with user data, plus a nightly rollup into daily aggregates,
  raw events kept 90 days **[call]**. It is a **new pipeline**: the existing `POST /api/analytics/events` (signed-in only, writes log lines) stays
  as it is. The new endpoint accepts anonymous events, and `props` is a **closed per-event schema** (enums,
  numbers, ids), so free text cannot get in. Raw events are **not** backed up to GCS; daily aggregates are
  **[call]**.
- **Consent gate [call]**: clients show the one-time choice when the device region or timezone is EU/EEA/UK/CH.
  The VM has no geo-IP and adding one isn't worth it. Everyone has the Settings switch.
- **Admin analytics tab**: daily actives, funnels, retention cohorts, feature usage, alerts, quiz, performance.

## 9. Look, feel, language

- **Design system [call]**: one token set (colour, type, spacing, radius, elevation, motion) defined once in the
  main repo as JSON and generated into Tailwind CSS variables, Android Material 3 theme values and iOS asset
  catalog/colour sets. Android already ships a designed light + dark theme, so the token set starts from Android's palette and
  is reconciled in the design phase. Android is restyled only where the new design deliberately changes it.
  Light is the default: warm off-white, an ocean-teal primary, a sunset-coral accent.
  The dark theme is designed rather than inverted. Motion is short and purposeful, and `prefers-reduced-motion`
  is respected. Final visual direction is set in the design phase with mockups before building.
- **i18n [call]**: a canonical catalogue `i18n/<locale>.json` (ICU MessageFormat for plurals). Generators emit
  Android `strings.xml` and iOS `.xcstrings`, and CI fails on missing keys. Dates/numbers/currency are formatted
  per locale. Noto Sans Devanagari/Bengali/SC fallbacks are loaded only when needed. AI outputs come back in
  the user's language (a language instruction in agent prompts). Static tables keep English content, with UI
  chrome translated. Translations are machine-drafted, then reviewed by a second model for meaning; **native
  speaker review of hi/bn/zh is recommended before marketing in those languages**.
- **Onboarding (identical on all clients)**: it replaces Android's current onboarding but keeps its
  traveller-type result as part of step 2 **[call]**. 5 steps sharing the same keys, order and copy: welcome → how you
  travel (interests/pace) → home airport + passport (for visa) → notifications (contextual ask) →
  first trip or explore. It is skippable and resumable, and its progress is telemetered. The existing
  OnboardingTour becomes the in-app coach marks after onboarding.

## 10. iOS app

- Repo `rupakc/travel-planner-ios` (public, MIT, like Android). **SwiftUI**, Swift 6, **iOS 17+**
  **[call]**. iOS 17 runs on iPhone XS/XR (2018) and newer, and on iPads from the 6th generation.
  Going lower would mean giving up Observation and modern SwiftUI for a very small share of devices.
- Architecture: feature modules as Swift packages; Observation; async/await. Server-sent events read with
  `URLSession.bytes`, parsed off the main actor. Swift Codable models mirror the API. MapKit for maps.
  Keychain for tokens. No heavy third-party dependencies (Firebase Messaging only if FCM→APNs is chosen over
  direct APNs **[call: direct APNs from the backend with an Apple auth key; no Firebase on iOS]**).
- iPad: `NavigationSplitView`, multi-column results, keyboard shortcuts, pointer support.
- Performance budget: cold start < 400 ms to first frame on an iPhone XS; 60/120 fps scrolling;
  lazy stacks; image downsampling; no main-thread JSON.
- CI: GitHub Actions `macos-15`. On every PR: build, SwiftLint, unit tests, snapshot tests and a UI-test smoke
  run on iPhone + iPad simulators. On main: an archive, uploaded to TestFlight once signing secrets exist.
- Parity: a written parity matrix (web ↔ Android ↔ iOS) lives in the main repo's docs and gates "done".

## 11. Phases (order and why)

| # | Phase | Ships | Depends on |
|---|---|---|---|
| 0 | **Foundations** | Design tokens + light/dark on web, i18n framework + the 7 catalogues for existing web UI, telemetry pipeline (backend + web SDK), parity matrix | — |
| 1 | **Accounts** | Sign-up/verify/reset, OAuth (config-gated), sessions, account area, delete/export, daily AI quotas | 0 |
| 2 | **Journey redesign (web)** | Trips hub, phases, prep checklist, Today, offline pack, expenses, recap, shared onboarding | 0, 1 |
| 3 | **Price alerts 2.0** | Price story, drop moment, savings, one-tap watch, digest | 2 |
| 4 | **Sharing** | Share cards, public OG pages, share flows | 2 |
| 5 | **Social + gamification** | Profiles, ideas feed, moderation, quizzes, XP, badges, leaderboards | 1, 4 |
| 6 | **Notifications** | Server categories/quiet hours/caps, trip-phase pushes, APNs | 1, 2 |
| 7 | **iOS app** | Full parity, starting once Phase 1's API is stable; tracks web phases from then on | 1 |
| 8 | **Android parity** | All new features + tokens + i18n + onboarding + telemetry | each phase |

Phases 7 and 8 run in parallel with 2–6 once the API for a phase is merged. Each phase follows the same loop:
plan → parallel implementation agents in worktrees → tests → three independent review passes → fix → PR → merge
(green CI deploys).

## 12. Left to the builder
Exact component structure, endpoint shapes (within §4–§8 and the compatibility rule), the copy (first in
English, then translated), badge list and point values (tuned with telemetry later), and the visual details
inside the token system.
