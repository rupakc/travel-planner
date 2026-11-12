# Phase 5 follow-ups

Phase 5 (Social + Play) shipped on 2026-11-12 with `SOCIAL_ENABLED` and `PLAY_ENABLED` on by default after the opus final review. Nothing here blocks that; each item is a candidate for a later PR.

## Product
- Optional AI moderation classifier behind `services/moderation.py::classify` (spend-cap aware).
- Translated entity names for the quiz bank; etiquette and "where is this" packs (need curated content and image rights).
- Push reminders for the daily quiz; comment threads; mobile apps (Android, iOS) adopting `docs/Social-API.md`.
- Per-user salt for the weekly challenge so answers cannot be shared (all users currently get identical questions).
- Social and quiz notification links to `/u/{handle}` and `/feed/{id}` (today both go to `/feed`).

## Correctness
- Quiz rewards: retry the XP/streak award when a transient error left a finished session without rewards.
- Head-to-head: strict 48 h expiry for an already-accepted match; `h2h_complete` farming with alt accounts.
- Idea feed: stable cursor for `for_you` (offset over a time-dependent score), exclude blocked commenters from counts, a report on an approved item should not permanently shield it from auto-hide, repeat reports should not burn the daily report quota.
- Comments and h2h lists keep showing a handle after the author goes private; account delete leaves `reports` rows about the deleted profile and `remix_of.handle` in copied plans.
- Save, unsave, save again creates a new plan each time (cap it).
- A restricted user can still edit bio/handle, like, follow and report.
- `avatar_url` embeds the internal user id; serve avatars by handle or an opaque token.
- Idea snapshot size check should measure the JSON, not `str(snap)`.

## Performance and ops
- Prune `quiz_sessions.questions_json` after N days; paginate the admin queue in SQL; index/limit the `for_you` scoring.
- Rollback note: an older backend lists `quiz`/`status` shares with a negative surrogate `plan_id` (status shares would render as plan shares); ship further share kinds one release ahead of any rollback.

## Tests and UX
- `SharePage` test "emits share_view with the kind" and `test_push` full-suite runs were flaky in CI (the latter hardened in #198); find the leaked background tasks.
- Leaderboard: label "friends" scope empty state; `/play` should not fetch `/play/state` for hide_game users (403 console noise).
