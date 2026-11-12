# Feature Parity

Which user-facing features each Voyager client has. The web column comes from this repository; the Android column from the [Android app's README](https://github.com/rupakc/travel-planner-android#features) (status "every feature module is merged and integrated on `main`") as of 2026-11-10; iOS does not exist yet. Phase numbers are from the [design spec](superpowers/specs/2026-11-10-voyager-reimagined-design.md) (section 11). Update this page in the same change that adds a client feature.

Legend: ✅ shipped · ⏳ Phase N planned · — not offered · ? not stated in the Android README, so not confirmed.

## Account and settings

| Feature | Web | Android | iOS |
|---|---|---|---|
| Sign in with username and password, change password | ✅ | ✅ | ⏳ Phase 7 |
| Create an account, verify email, reset password | ✅ | ⏳ Phase 8 | ⏳ Phase 7 |
| Sessions list and revoke one (mobile sign-ins; `GET/DELETE /auth/sessions`) | — | ⏳ Phase 8 | ⏳ Phase 7 |
| Sessions: sign out everywhere, refresh tokens on mobile | ✅ | ⏳ Phase 8 | ⏳ Phase 7 |
| Account area: profile, avatar, settings, linked sign-in methods | ✅ | ⏳ Phase 8 | ⏳ Phase 7 |
| Export my data and delete my account | ✅ | ⏳ Phase 8 | ⏳ Phase 7 |
| Daily AI allowance and verified-email requirement | ✅ | ⏳ Phase 8 | ⏳ Phase 7 |
| XP, badges, levels and streaks (can be hidden) | ✅ | ⏳ Phase 8 | ⏳ Phase 7 |
| Social sign-in buttons (Apple, Google, Facebook, GitHub) | ✅ buttons always shown; sign-in works once the provider credentials are set, "coming soon" until then | ⏳ Phase 8 | ⏳ Phase 7 |
| Admin: users and feedback | ✅ | — (README lists traveller-facing flows only) | ⏳ Phase 7 |
| Admin: Analytics tab (telemetry summary) | ✅ | — | ⏳ Phase 7 |
| Preferences, two-way bound to the search form; Taste Graph | ✅ | ? (Settings and per-feature visibility are device-local per the README) | ⏳ Phase 7 |
| Light and dark theme (see [Theming](Theming.md)) | ✅ | ✅ | ⏳ Phase 7 |
| Languages (see [Internationalization](Internationalization.md)) | ✅ en, es, de, fr, hi, zh, bn | English and Spanish; ⏳ Phase 8 for de, fr, hi, zh, bn | ⏳ Phase 7 |
| Telemetry and consent prompt (see [Telemetry](Telemetry.md)) | ✅ | ⏳ Phase 8 | ⏳ Phase 7 |
| Feedback widget | ✅ | ? | ⏳ Phase 7 |
| Onboarding | ✅ coach-mark tour | ✅ traveller-type onboarding (different flow) | ⏳ Phase 7 |

## Search

| Feature | Web | Android | iOS |
|---|---|---|---|
| Known destination search | ✅ | ✅ | ⏳ Phase 7 |
| Surprise me (discover) | ✅ | ✅ | ⏳ Phase 7 |
| Compare 2-3 destinations | ✅ | ✅ | ⏳ Phase 7 |
| Plan from a link, text or screenshots | ✅ | ✅ | ⏳ Phase 7 |
| Multi-city trips | ✅ | ? | ⏳ Phase 7 |
| Traveller panel and accessibility needs | ✅ | ? | ⏳ Phase 7 |
| Recent searches | ✅ | ? | ⏳ Phase 7 |

## Results

| Feature | Web | Android | iOS |
|---|---|---|---|
| Streamed results, section by section | ✅ | ✅ | ⏳ Phase 7 |
| Verification chip and popover per section | ✅ | ✅ | ⏳ Phase 7 |
| Estimates labelled as such | ✅ | ✅ | ⏳ Phase 7 |
| Individual sections (flights, weather, hotels, activities, places, walking tours, events, visa, SIM, tips, emergency card, getting around, forex, packing list, pricing advice) | ✅ | ? | ⏳ Phase 7 |
| Day-by-day itinerary, drag and drop, stress-test Re-check | ✅ | ? | ⏳ Phase 7 |
| Best-value package | ✅ | ? | ⏳ Phase 7 |
| Budget planner | ✅ | ? | ⏳ Phase 7 |
| Fare calendar and price insights | ✅ | ? | ⏳ Phase 7 |
| Trip Remix | ✅ | ? | ⏳ Phase 7 |
| Trip map | ✅ | ? | ⏳ Phase 7 |

## My Plan and sharing

| Feature | Web | Android | iOS |
|---|---|---|---|
| Select items into My Plan, save and load plans | ✅ | ✅ | ⏳ Phase 7 |
| Share link | ✅ | ✅ | ⏳ Phase 7 |
| Public share viewer | ✅ | ✅ deep link | ⏳ Phase 7 |
| Export to calendar (.ics) and print/PDF | ✅ | ✅ | ⏳ Phase 7 |
| Cost breakdown | ✅ | ? | ⏳ Phase 7 |

## Trips and the journey

| Feature | Web | Android | iOS |
|---|---|---|---|
| Trips hub, trip phases and next-up card | ✅ | ⏳ 8 | ⏳ 7 |
| Prep checklist and trip-ready meter | ✅ | ⏳ 8 | ⏳ 7 |
| Offline pack (emergency card, currency, phrases, plan) | ✅ | ⏳ 8 | ⏳ 7 |
| Today view and daily check-in | ✅ | ⏳ 8 | ⏳ 7 |
| Expenses with currency converter | ✅ | ⏳ 8 | ⏳ 7 |
| Journal and place ratings and visits | ✅ | ⏳ 8 | ⏳ 7 |
| Recap, passport stamps and countries visited | ✅ | ⏳ 8 | ⏳ 7 |
| Explore, Play and You tabs | ✅ | ⏳ 8 | ⏳ 7 |

## Chat

| Feature | Web | Android | iOS |
|---|---|---|---|
| Streaming chat with plan commands and planning | ✅ | ✅ | ⏳ Phase 7 |

## Alerts and nearby

| Feature | Web | Android | iOS |
|---|---|---|---|
| Fare watch and price watches (hotel, activity, trip) | ✅ | ✅ | ⏳ Phase 7 |
| Notification inbox and unread bell | ✅ | ✅ | ⏳ Phase 7 |
| Alert e-mail | ✅ | ? | ⏳ Phase 7 |
| Push notifications | — (a toast, or a native notification while the tab is open) | ⏳ Phase 6 (FCM wired, inert until configured) | ⏳ Phase 6 |
| Price story (chart, lowest, typical range, verdict) | ✅ (behind `PRICE_ALERTS_V2_ENABLED`) | ⏳ | ⏳ Phase 7 |
| Drop moment, savings tally and Deal-hunter XP | ✅ (same flag) | ⏳ | ⏳ Phase 7 |
| One-tap watch and suggestions | ✅ (same flag; needs `SERPAPI_KEY`) | ⏳ | ⏳ Phase 7 |
| Weekly digest, quiet hours, caps and grouping (preferences) | ✅ (same flag) | ⏳ | ⏳ Phase 7 |
| Local trip reminders | — | ✅ | ⏳ Phase 7 |
| "Search the web now" on a watch | ✅ | ✅ | ⏳ Phase 7 |
| Near me | ✅ | ✅ | ⏳ Phase 7 |
