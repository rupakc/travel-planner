# Feature Parity

Which user-facing features each Voyager client has. The web column comes from this repository; the Android column from the [Android app's README](https://github.com/rupakc/travel-planner-android#features) (status "every feature module is merged and integrated on `main`") as of 2026-11-13 (Phases 1 to 5 merged on `main`, plus the final-audit parity fixes); iOS does not exist yet. Phase numbers are from the [design spec](superpowers/specs/2026-11-10-voyager-reimagined-design.md) (section 11). Update this page in the same change that adds a client feature.

Legend: ✅ shipped · ⏳ Phase N planned · — not offered · ? not stated in the Android README, so not confirmed.

## Account and settings

| Feature | Web | Android | iOS |
|---|---|---|---|
| Sign in with username and password, change password | ✅ | ✅ | ⏳ Phase 7 |
| Create an account, verify email, reset password | ✅ | ✅ password strength meter (same rules as web); a verify link opened while signed in asks to sign out first (web swaps accounts) | ⏳ Phase 7 |
| Sessions list and revoke one (`GET/DELETE /auth/sessions`) | ✅ (Account → Security; hidden on an older backend) | ✅ | ⏳ Phase 7 |
| Sessions: sign out everywhere, refresh tokens on mobile | ✅ | ✅ | ⏳ Phase 7 |
| Account area: profile, avatar, settings, linked sign-in methods | ✅ | ✅ including linking Google, GitHub and Facebook | ⏳ Phase 7 |
| Export my data and delete my account | ✅ | ✅ | ⏳ Phase 7 |
| Daily AI allowance and verified-email requirement | ✅ | ✅ an `email_unverified` refusal raises a banner with a send-link action | ⏳ Phase 7 |
| XP, badges, levels and streaks (can be hidden) | ✅ | ✅ |
| Hide community (`hide_community`: hides Ideas, profile and social surfaces) | ✅ | ✅ Ideas entry, profile, publish launcher and social notification switch | ⏳ Phase 7 |
| Social sign-in buttons (Apple, Google, Facebook, GitHub) | ✅ buttons always shown; sign-in works once the provider credentials are set, "coming soon" until then | ✅ same four buttons including Apple, "coming soon" note until the provider is configured; system browser + PKCE | ⏳ Phase 7 |
| Admin: users and feedback | ✅ | — (README lists traveller-facing flows only) | ⏳ Phase 7 |
| Admin: Analytics tab (telemetry summary) | ✅ | — | ⏳ Phase 7 |
| Preferences, two-way bound to the search form; Taste Graph | ✅ | ? (Settings and per-feature visibility are device-local per the README) | ⏳ Phase 7 |
| Light and dark theme (see [Theming](Theming.md)) | ✅ | ✅ | ⏳ Phase 7 |
| Languages (see [Internationalization](Internationalization.md)) | ✅ en, es, de, fr, hi, zh, bn | ✅ en, es, de, fr, hi, zh, bn (hi, zh, bn awaiting native-speaker review) | ⏳ Phase 7 |
| Telemetry and consent prompt (see [Telemetry](Telemetry.md)) | ✅ | ✅ every tap, toggle, change and submit reported through shared UI wrappers (tid and route only); the consent prompt itself is not confirmed | ⏳ Phase 7 |
| Feedback widget | ✅ | ? | ⏳ Phase 7 |
| Onboarding | ✅ coach-mark tour; welcome and notifications copy shared with Android | ✅ traveller-type onboarding; same copy as web in all 7 languages, no first-run feature picker (feature toggles stay in Settings → Features, the Settings retake keeps the picker) | ⏳ Phase 7 |

## Search

| Feature | Web | Android | iOS |
|---|---|---|---|
| Known destination search | ✅ | ✅ | ⏳ Phase 7 |
| Surprise me (discover) | ✅ uses the signed-in user's Taste Graph | ✅ | ⏳ Phase 7 |
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
| Public share viewer | ✅ | ✅ deep link, plus paste-a-link; recap, savings, quiz and status kinds | ⏳ Phase 7 |
| Share links 2.0: choose what is revealed (dates, origin, name), share card (link and story sizes), list and revoke links | ✅ | ✅ share sheet with the card PNG, My shares with revoke ([Sharing API](Sharing-API.md)) | ⏳ planned ([Sharing API](Sharing-API.md)) |
| Share a trip recap or savings card as a link | ✅ | ✅ | ⏳ planned |
| Link previews (Open Graph page and card.png for crawlers) | ✅ server-side, all clients | ✅ same links | ✅ same links |
| Export to calendar (.ics) and print/PDF | ✅ | ✅ | ⏳ Phase 7 |
| Cost breakdown | ✅ | ? | ⏳ Phase 7 |

## Trips and the journey

| Feature | Web | Android | iOS |
|---|---|---|---|
| Trips hub, trip phases and next-up card | ✅ | ✅ | ⏳ 7 |
| Prep checklist and trip-ready meter | ✅ | ✅ | ⏳ 7 |
| Offline pack (emergency card, currency, phrases, plan) | ✅ queued offline writes show a "rejected" state when the server refuses them (for example a per-trip cap) | ✅ | ⏳ 7 |
| Today view and daily check-in | ✅ | ✅ | ⏳ 7 |
| Expenses with currency converter | ✅ | ✅ | ⏳ 7 |
| Journal and place ratings and visits | ✅ | ✅ | ⏳ 7 |
| Recap, passport stamps and countries visited | ✅ | ✅ (the scratch map is a country list; passport stamps are not built) | ⏳ 7 |
| Explore, Play and You tabs | ✅ | ✅ | ⏳ 7 |

## Social and Play

| Feature | Web | Android | iOS |
|---|---|---|---|
| Social profile (handle, privacy, opt-in fields) | ✅ | ✅ | ⏳ 7 |
| Follows, follow requests and blocks | ✅ | ⏳ 8 | ⏳ 7 |
| Ideas feed, publish from a plan or recap, like, save (remix) | ✅ | ✅ | ⏳ 7 |
| Comments and helpful marks | ✅ | ⏳ 8 | ⏳ 7 |
| Reports and admin moderation queue | ✅ | ⏳ 8 (reports) | ⏳ 7 (reports) |
| Daily quiz and topic packs | ✅ | ✅ | ⏳ 7 |
| Head-to-head challenges | ✅ | ⏳ 8 | ⏳ 7 |
| Weekly leaderboards (global, friends) | ✅ | ✅ | ⏳ 7 |
| Weekly "Know before you go" challenge | ✅ | ⏳ 8 | ⏳ 7 |
| Quiz and trip-status share cards | ✅ | ✅ | ⏳ 7 |
| Social and quiz notifications (daily quiz reminder, likes and comments on your ideas, head-to-head) | ✅ | ✅ | ⏳ 7 |

Both are behind `SOCIAL_ENABLED` / `PLAY_ENABLED` (`features.social`, `features.play`). Contract: [Social and Play API](Social-API.md).

## Chat

| Feature | Web | Android | iOS |
|---|---|---|---|
| Streaming chat with plan commands and planning | ✅ | ✅ | ⏳ Phase 7 |

## Alerts and nearby

| Feature | Web | Android | iOS |
|---|---|---|---|
| Fare watch and price watches (hotel, activity, trip) | ✅ | ✅ | ⏳ Phase 7 |
| Notification inbox and unread bell | ✅ | ✅ | ⏳ Phase 7 |
| Alert e-mail | ✅ localised to the account language (server-side `data.i18n`) | ? | ⏳ Phase 7 |
| Push notifications | — (a toast, or a native notification while the tab is open) | ✅ FCM, per-category channels (inert until configured) | ⏳ Phase 6 |
| Price story (chart, lowest, typical range, verdict) | ✅ (behind `PRICE_ALERTS_V2_ENABLED`) | ✅ (needs `features.alerts_api` / `price_alerts_v2`) | ⏳ Phase 7 |
| Drop moment, savings tally and Deal-hunter XP | ✅ (same flag; savings card follows the light/dark theme, drop-moment badge) | ✅ ("caught a drop", never "saved"); the Deal-hunter track, bucket ring and passport stamp are not built | ⏳ Phase 7 |
| One-tap watch and suggestions | ✅ (same flag; needs `SERPAPI_KEY`) | ✅ (needs `live_prices`; Results cards only so far) | ⏳ Phase 7 |
| Weekly digest, quiet hours, caps and grouping (preferences) | ✅ (same flag; digest text localised) | ✅ | ⏳ Phase 7 |
| Local trip reminders | — | ✅ | ⏳ Phase 7 |
| Notification settings (categories, quiet hours, daily cap) | ✅ (Account → Notifications; shown when `features.notifications_api`) | ✅ (Settings → Notifications) | ⏳ Phase 7 |
| Localized notification text catalog (`/notifications/catalog`) | — (server-side) | ✅ (used for on-device "near you" text) | ⏳ Phase 7 |
| Trip-phase pushes (T-30, T-7, T-1, morning brief) | — | ✅ taps open the trip Today tab; the morning-brief switch now also turns the local trip switch on | ⏳ Phase 6 |
| "Search the web now" on a watch | ✅ | ✅ | ⏳ Phase 7 |
| Near me | ✅ | ✅ (a background geofence arrival notification is not built, by ruling) |
| Weather-change push | — | — (not built) | ⏳ Phase 7 |

## Known gaps

- Android: background geofence arrival notification (not built, by ruling), weather-change push (not built on any client), Deal-hunter track, bucket ring and passport stamp, scratch map is a country list.
- Android: one-tap watch on a saved plan or chat, a watch offer on save and Recap "Where next" are in review and not counted as shipped here.
- Android: follows, comments, head-to-head and the weekly challenge remain Phase 8.
