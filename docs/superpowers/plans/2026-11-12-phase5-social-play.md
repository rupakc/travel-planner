# Phase 5 — Social + Play Implementation Plan

> **For agentic workers:** use superpowers:subagent-driven-development. Steps use `- [ ]` checkboxes. Commit author and committer must be exactly `rupakc <4364388+rupakc@users.noreply.github.com>`; verify with `git log -1 --format='%an <%ae> / %cn <%ce>'` before the first push.

**Goal:** profiles, an ideas feed with real moderation, daily quiz and topic packs, asynchronous head-to-head, weekly leaderboards and challenges, all safe by default and costing no live AI calls.

**Spec:** `docs/superpowers/specs/2026-11-10-voyager-reimagined-design.md` §5, §5a (Social and Play rows), §11. **Contract (binding, written first):** `docs/Social-API.md`. Build on `app/game/` (engine, `rules.json`, `hide_game`), `docs/Sharing-API.md`, `docs/Notifications-API.md`.

## Owner-question rulings (main controller, 2026-11-12)

1. **Two flags, both default `false`** until the final review: `SOCIAL_ENABLED` (profiles, feed, moderation) and `PLAY_ENABLED` (quiz, h2h, boards, challenges; also needs `GAME_ENABLED`). Off: routes 404, `features.social|play` = 0, the SPA hides entry points. Final task flips both if the review is clean.
2. **Identity.** A user-chosen handle is the only public identity (never username/email). No profile exists until the user creates one; default visibility `private`; each extra field is its own opt-in; leaderboards opt-in. A handle can change once per 30 days.
3. **Moderation without AI cost.** Spec §2a mentions a Flash-Lite classifier. Ruling: this phase ships a deterministic keyword filter (reject list, review list, URL/email-like tokens held), reports (auto-hide at 3 distinct verified reporters), blocking, per-user limits, restrictions and an admin queue, and **no model call**. An optional classifier is a follow-up behind the same hook (`services/moderation.py::classify`). Unverified users cannot publish ideas or comments.
4. **`hide_game` scope.** The setting is labelled "Hide Play & points", so it hides Play, XP, level, badges and leaderboards (routes 403 `game_hidden`, excluded from boards, no quiz notifications, no game fields on their profile). The feed and profiles are social, not game, and remain. One-line change if the owner reads it wider.
5. **Quiz bank is committed data, no AI.** `backend/app/game/quiz/bank.json` (entities: countries with capital, landmarks with country, dishes with country) plus a deterministic generator. Prompts are templates translated in the SPA (`play` namespace); country names are localised from `countries.csv`; capital, landmark and dish names ship in English (with optional per-language `names` where known, English fallback). Packs: flags, capitals, landmarks, cuisine. Etiquette and "where is this" images are deferred (need curated content and image rights). Bank minimum: 80 countries with capitals, 40 landmarks, 40 dishes, every country alpha-2 valid; a test checks consistency and that every distractor pool has >= 3 entries.
6. **Scoring** is server-side: 100 per correct plus up to 50 speed bonus linear over 15 s, computed from server timestamps. Daily quiz = same five questions per UTC day (seeded by date), once per user. XP values in the contract; streak `quiz` via `touch_streak`.
7. **Leaderboards** score = the ISO week's quiz and h2h points. Global is opt-in only (top 50); friends = people I follow (approved) plus me. Handles only.
8. **Weekly challenge** = five questions about the country of the user's next upcoming trip when the bank has >= 3 entries for it, else a featured pack of the week (deterministic by ISO week). Computed from existing trips data; no new tables for it beyond sessions.
9. **Head-to-head** is asynchronous, 48 h expiry, limits 5 open and 10 per day, only against non-private, unblocked handles; opponent score hidden until both finish; both get `h2h_complete` XP.
10. **Remix** reuses `utils/remix` semantics server-side: saving an idea creates a new plan in the saver's account from the whitelisted snapshot. The author earns `idea_saved` once per (saver, idea), never for self-saves, only from verified savers. No XP for posting, liking, following or commenting.
11. **Limits:** ideas 5/day, comments 30/day, reports 20/day, follows 200/day, h2h 10/day; sizes: title 80, caption 500, comment 300, bio 160, note 200, snapshot 64 KB. Buckets `social_write` 30, `social_read` 120 per 10 min, `play` 60, plus `admin` for the queue. Tests run with limits off, plus one test that enables them.
12. **Rendering:** all user text plain, escaped by React, no `dangerouslySetInnerHTML`, no markdown, no auto-links. Public surfaces stay behind sign-in and carry no OG data (feed is not crawled).
13. **Notifications** use `notify_center.enqueue_category` with dedupe keys (`social`: idea saved, new follower; `quiz`: h2h invite/result). Text via the shared catalog in 7 languages.
14. **Sharing kinds** `quiz` and `status` extend Phase 4's `POST /shares` additively (see contract). Telemetry enums grow additively.

## Global constraints

- Two-way compatibility (CLAUDE.md): additive schema (`CREATE TABLE IF NOT EXISTS`; new tables join the GCS/VM user-table backup set like `shares`), no existing route changes shape, the SPA feature-detects `features.social|play` and tolerates the old backend, old SPA unaffected.
- Telemetry: closed registry additions with matching `docs/Telemetry.md` rows (registry test): `social_profile_view`, `social_profile_save` (`visibility`), `social_idea_publish` (`kind`), `social_idea_open`, `social_idea_like`, `social_idea_save`, `social_comment`, `social_follow` (`state`), `social_report` (`target`,`reason`), `social_block`, `social_feed_view` (`scope`), `play_state_view`, `play_quiz_start` (`mode`,`pack`), `play_quiz_answer` (`correct`: bool, `elapsed_s`: int), `play_quiz_done` (`mode`,`correct`: int), `play_h2h_create`, `play_h2h_open`, `play_h2h_result` (`winner` enum), `play_board_view` (`scope`), `play_challenge_view`, `admin_mod_action` (`action`). No handles, ids or text. Every control has `data-tid`.
- i18n: new lazy namespaces `social` and `play` (plus `game` badge names and notification templates) in all 7 languages; register in `routeNamespaces.js` and `index.js` globs; `catalog.test.js` green. Informal es/de, `vous` fr.
- Theme tokens only (light default, dark supported), 16px mobile gutters, reduced motion respected, buttons >= 44px.
- Gates per PR: `ruff check backend/`, `cd backend && python3 -m pytest -q`, `cd frontend && npx eslint src/ --max-warnings 0 && NODE_OPTIONS=--experimental-require-module npm test` (frontend PRs), `mkdocs build --strict`.
- Docs: each task that deviates from `docs/Social-API.md` updates it in the same PR. `docs/Configuration.md` rows for new settings.

## Tasks (each its own PR in worktree `.claude/worktrees/p5-tN`; 4 waves, max 3 agents at once)

Wave A (parallel): **T1, T3**. Wave B: **T2** (needs T1), **T4** (needs T1, T3), **T6** (needs T3). Wave C: **T5** (needs T2, T4), **T7** (needs T1, T2 contract), **T8** (needs T3, T4 contract), **T9** (needs T2). Wave D: **T10**, **T11**, then E2E, final review, flip.

### T1 — Social core backend
`db/social_db.py` (tables `social_profiles`, `social_follows`, `social_blocks`, `social_limits`), `services/social_profile.py` (handle rules, reserved words reuse `db/reserved_usernames.py`, privacy projection pure function), `api/routes/social.py` (profile, handles/check, follow, requests, blocks), flags + buckets in `core/config.py`, `main.py` wiring, `client_config.py` features, backup set, Configuration.md. Tests: privacy matrix (every opt-in field absent by default, hidden-game omits level/badges, private/followers/blocked 404), handle validation, follow states, block removes follows, never leaks username/email, rate-limit test.

### T2 — Ideas, comments, moderation backend (needs T1)
`db/social_ideas_db.py` (`ideas`, `idea_likes`, `idea_saves`, `comments`, `reports`, `restrictions`), `services/moderation.py` (pure `check(text) -> allow|review|reject` with committed lists `services/moderation_terms.json`; `classify` hook stub returning None), `services/idea_snapshot.py` (reuse `share_public` whitelist), `services/feed_rank.py` (SQL ranking), routes in `social.py` (or `social_ideas.py`) and `admin_social.py`, game rules `idea_saved` and `comment_helpful` + badges (`rules.json`, additive). Tests: hostile text stored plain and returned as JSON-safe, filter outcomes, held visibility, auto-hide at 3 verified reporters, blocked pairs, limits, snapshot never contains dates/origin/name/email, remix creates plan, XP once and not for self, admin queue and restrict.

### T3 — Quiz engine backend
`game/quiz/bank.json` + `game/quiz/engine.py` (pure: deterministic question builder, scoring), `db/quiz_db.py` (`quiz_sessions`, `quiz_answers`), `api/routes/play.py` (`state`, `quiz`, `answer`, `history`), rules `quiz_daily`, `quiz_perfect`, `quiz_pack`, streak `quiz`, badges, `PLAY_ENABLED`, bucket `play`, hide_game 403. Tests: bank consistency, determinism by date and seed, daily once, resume, server timing (monkeypatch clock), wrong answer, re-answer idempotent, XP caps, expiry, hidden-game, flag off. No network anywhere.

### T4 — Head-to-head, leaderboards, challenge backend (needs T1, T3)
`db/play_db.py` (`h2h_matches`), routes in `play.py`, `services/leaderboard.py` (weekly SQL), `services/challenge.py` (next-trip country via `trips_db`/plans, featured fallback), rules `h2h_complete`, `challenge_complete`, badges. Tests: lifecycle, limits, block, privacy of boards (opt-in, hidden-game excluded, handles only), friends scope, week boundaries, challenge selection with and without trips.

### T5 — Notification senders (needs T2, T4)
Hook the four kinds into `notify_center.enqueue_category` (fire-and-forget, never breaks the request), catalog templates in 7 languages (`notify_text.py`), remove "no sender yet" wording in `docs/Notifications-API.md` (additive note). Tests: dedupe, category off, hidden-game gets no quiz kinds, text per locale.

### T6 — Share kinds quiz and status (needs T3)
Extend `shares.py`/`share_public.py`/`share_card.py` additively (`session_id`, status from active trip); telemetry `_SHARE_KIND` enum; Sharing-API.md additive note. Tests: card content has no time/answers, not-yours 404, status needs an active trip (`422 no_active_trip`).

### T7 — Social UI (needs T1, T2 contract)
`pages/FeedPage.jsx`, `pages/ProfilePage.jsx` (`/u/:handle`, own profile editor), `components/social/` (IdeaCard, PublishIdeaDialog from plan/recap entry points, Comments, ReportDialog, BlockButton, HandleField), `services/socialApi.js`, route + NavBar entry only when `features.social`, namespace `social` x7, telemetry, tests. Plain-text rendering test with `<img onerror>` strings.

### T8 — Play UI (needs T3, T4 contract)
Extend `PlayPage.jsx`: Daily quiz card, pack grid, `QuizRunner` (timer display, big options, reveal, reduced motion), result with XP and share button, H2H list/create, `Leaderboard` (scope tabs, opt-in prompt), weekly challenge card; routes `/play/h2h/:id`; hidden-game renders nothing; namespace `play` x7, telemetry, tests.

### T9 — Admin moderation tab (needs T2)
`components/admin/ModerationQueue.jsx`, tab in `AdminPage.jsx` (probed like Invites, hidden on 404), approve/remove/restrict, tests, i18n in `adminTelemetry`-style new ns `adminSocial` x7.

### T10 — Share UI for quiz/status (needs T6, T8)
Add share entry to quiz result and the Today screen's status; ShareDialog kinds; `share` namespace strings x7.

### T11 — Docs and parity
`docs/Feature-Parity.md` rows (web done, Android/iOS planned), `docs/API-Reference.md` index rows, `docs/Telemetry.md` consistency, CLAUDE.md pointer lines, Social-API.md freeze header text final. Then local-stack browser E2E (fake SerpAPI only), one opus whole-branch review, fixes, flip flags (`SOCIAL_ENABLED`, `PLAY_ENABLED` default true) if clean, write `2026-11-12-phase5-followups.md`.

## Follow-ups seeded now
Optional AI moderation classifier, translated entity names for the bank, etiquette and "where is this" packs, push reminders for the daily quiz, comment threads, mobile apps adopting Social-API.
