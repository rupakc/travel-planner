# Phase 1 — Accounts + game engine Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let strangers sign up (native username/email/password with a 30-minute confirmation link, or Apple, Google, Facebook or GitHub), recover a password, stay signed in on mobile, manage an account area (avatar, name, settings, connected sign-in methods, export, delete), and use AI only once verified and within a daily quota. Add the XP/badge/streak engine with its first two hooks, onboarding complete and email verified.

**Architecture:** The plan is additive. The `users` table gains columns, and twelve new tables hold tokens, identities, sessions, invites, settings, quotas and the game. One wave-0 task freezes the whole schema, and another freezes every seam in shared files: settings, router stubs registered in `main.py`, the error envelope, URL building, game hooks and the quota dependency. After that, each later task owns its own files. OAuth is a server-side authorization-code flow. Provider state lives in SQLite, and a browser-binding cookie or a client PKCE verifier protects the one-time handoff code, so tokens never travel in a URL. Each provider is a small adapter behind one protocol. Game values (points, caps, badges, levels) are a JSON config file, not code.

**Tech Stack:** FastAPI + SQLite, PyJWT (HS256 sessions; RS256/ES256 provider tokens through `cryptography`), httpx (provider calls; `httpx.MockTransport` in tests), Pillow (avatars), stdlib `smtplib` through `services/alert_email.send_message`; React 18 + react-router 6, i18next (existing), vitest.

**Spec:** `docs/superpowers/specs/2026-11-10-voyager-reimagined-design.md` (§2 constraints, §2a owner decisions, §4 Accounts and identity, §5a gamification, §8 telemetry, §11 Phase 1). Style model: `docs/superpowers/plans/2026-11-10-phase0-foundations.md`.

## Global Constraints

- **Two-way compatibility (CLAUDE.md).** The new backend keeps serving the previous SPA and the Android app in the field. `POST /api/auth/login`, `GET /api/auth/me`, `POST /api/auth/change-password`, `PUT /api/auth/email` and `GET /api/auth/providers` keep their current request fields and response keys; changes are additive. The new SPA works against the previous backend: a 404 from any new endpoint, or a `/api/config` without the `auth` block, hides that feature without an error (no "Create account", no Account sections, no game chip).
- **Contract freeze.** The "API contract" section below is frozen at the end of wave 0 because the iOS and Android apps build against it. Changing it after that needs a contract-change note in the PR and an update to `docs/Accounts-API.md` in the same PR.
- **Identity key.** `users.username` stays the immutable internal key. No existing table is migrated. New tables key on `users.id`.
- **Existing tokens keep working.** A JWT without `tv` counts as `token_version` 0. Admin-created users keep `is_first_login` semantics and count as verified for AI (`signup_method = 'admin'`).
- **Every absolute URL** (email links, OAuth `redirect_uri`, avatar URLs, mobile redirects) comes from `core/urls.public_base_url()` = `PUBLIC_BASE_URL`, else `APP_BASE_URL`, with the trailing `/` stripped. Moving to a custom domain is a config change.
- **Providers are config-gated.** A provider counts as configured only when all its credentials are non-empty. Unconfigured providers still show their button on every client, and tapping one shows the existing "coming soon" note. Setting the credentials and restarting the app container is all it takes: no code change and no client update.
- **PKCE S256 + `state`** on Google, GitHub and Facebook. Apple documents no PKCE, so Apple uses `state` + `nonce` (checked in its `id_token`). Mobile clients must also send their own S256 `challenge`, which binds the handoff code to the app.
- **Auto-link only to an account whose email we have verified** (`users.email_verified = 1`), and only from a provider identity whose email is verified *and trusted*. Google, Apple and GitHub (primary verified email) are trusted. Facebook is untrusted unless `FACEBOOK_EMAIL_TRUSTED=true`. A pending (unverified) native account is never linked.
- **Secrets never in logs or URLs.** Verify/reset tokens, handoff codes, refresh tokens, provider codes and secrets are never logged and never put in an API URL. The one exception is the dev link log (see Task 8), which runs only when SMTP is unset *and* `EMAIL_LOG_LINKS=true` or the base URL host is `localhost`/`127.0.0.1`. The SPA removes `?token=` / `?code=` from the address bar with `history.replaceState` before its first request.
- **Stored secrets are hashes.** Every random token is ≥ 256 bits from `secrets.token_urlsafe(32)`, and only its SHA-256 hex is stored. Apple's refresh token, which account deletion needs in order to revoke, is stored Fernet-encrypted with a key HKDF-derived from `JWT_SECRET_KEY` (info `b"voyager-identity-secret"`).
- **Passwords.** Server minimum is 10 characters, at most 128, not in the committed top-10k list (case-insensitive), and not equal to the username or the email's local part. The rule applies to sign-up, reset, change-password and admin-set passwords (admin temporary passwords included).
- **Unverified accounts cannot run AI; the daily quota sits on top of the 10-minute windows.** Both are enforced in the `_limited(...)` router dependencies and in `ChatAgent._full_plan_refusal`. Admins are exempt from the quota, not from the windows.
- **Game guardrails (§5a).** Awards are computed server-side only from server-observed events, never from client claims or telemetry. Every award is idempotent (a unique `idem_key`) and capped per rule per day. There are no points for volume, and the game never gates a core feature. `hide_game` hides every game element on every client, while XP still accrues.
- **Free tiers only.** No new service: SMTP (existing settings), SQLite and local disk for avatars.
- **i18n.** Every new user-visible string is in all 7 languages (`en es de fr hi zh bn`). Each frontend task creates **its own new namespace** and edits no existing namespace JSON. The backend email strings live in `backend/app/i18n/emails/<lang>.json`, with their own parity test. Brand "Voyager", provider names and codes are never translated.
- **Telemetry.** Phase 1 events are added once to the closed registry (Task 4). Props are enums, ints and ids only: never an email, username or display name.
- Python 3.12, `ruff check backend/` clean; `cd frontend && npx eslint src/ --max-warnings 0`; `mkdocs build --strict`; `cd backend && python3 -m pytest -q` and `cd frontend && npm test` keep passing. Every interactive element gets a `data-tid`.

## Review Focus

1. **Email link prefetch and double clicks.** Mail scanners (Outlook Safe Links, Gmail) GET every link, and people click twice. Opening `/verify?token=…` must never consume the token (only the SPA's POST does). A second POST on a used token answers `409 token_used`, and the page shows "already confirmed, sign in" rather than an error. Tests in Task 27 (`test_verify_twice_is_token_used`) and Task 16 (`renders already-confirmed on token_used`).
2. **Concurrent refreshes from a mobile app.** Two requests refresh at the same moment with the same refresh token. The loser gets `401 refresh_stale` inside the 30 s grace window, and the family is **not** revoked. Reuse after the grace window revokes the family. Tests in Task 7 (`test_refresh_reuse_within_grace_keeps_family`, `test_refresh_reuse_after_grace_revokes_family`).
3. **Pre-account-takeover through linking.** An attacker signs up natively with the victim's email and leaves it pending; later the victim uses Google with the same email. The pending row must be deleted, never linked. A Facebook (untrusted) email never auto-links. An admin-created account with an unverified matching email gets `email_in_use_unverified`, not a link. Tests in Task 32 (`test_pending_native_account_is_replaced_not_linked`, `test_untrusted_email_never_links`, `test_unverified_existing_email_is_refused`).
4. **Mixed versions.** The old SPA on the new backend: login works, a pending account's 403 `detail` is shown as text, and the additive fields are ignored. The new SPA on the old backend: `/api/auth/signup`, `/api/account`, `/api/game/me` and `/api/config.auth` all 404 or are missing, and the UI hides those features with no console errors. Tests in Task 7 (`test_login_response_keeps_legacy_keys`) and Task 5 (`old backend hides signup and account sections`).
5. **Username and email collisions.** `Jane` vs `jane`, a username held by a pending account whose link expired, two sign-ups racing for one name, and two redemptions racing for an invite's last use. Comparisons are case-insensitive, an expired pending holder is released, the insert runs inside `BEGIN IMMEDIATE`, and invite consumption is a conditional `UPDATE`. Tests in Task 2 (`test_username_taken_is_case_insensitive`, `test_expired_pending_releases_username`), Task 9 (`test_last_use_cannot_be_redeemed_twice`) and Task 27 (`test_signup_race_one_wins`).

---

## API contract (frozen at the end of wave 0)

All paths are under `/api`. JSON in and out. Unless noted, auth means `Authorization: Bearer <access_token>`.

### Conventions

- **Error envelope** for every new error: `{"detail": "<English sentence>", "error_code": "<code>"}`, plus extra keys where listed. Clients render text from `error_code` (web: the `errors` namespace) and fall back to `detail`. Malformed bodies keep FastAPI's default `422 {"detail": [...]}`. Every `429` carries `Retry-After` (seconds).
- **`client`** is optional on every endpoint that issues a session: `"web"` (default), `"ios"` or `"android"`. Mobile clients receive a `refresh_token`. Optional `device_name` is a string of at most 64 characters.
- **`locale`** is optional: one of `en es de fr hi zh bn`. It selects the email language and is stored as `users.locale`.
- **Timestamps** are ISO 8601 UTC with `Z`. Days are `YYYY-MM-DD` (UTC unless stated).

### Shared objects

`User`, returned by login, `/auth/me`, sessions and `/account`. Every legacy key is kept:
```json
{"id": "6f1c…uuid", "username": "jane_doe", "display_name": "Jane", "email": "jane@example.com",
 "email_verified": true, "is_admin": false, "requires_password_change": false,
 "account_verified": true, "has_password": true, "signup_method": "password",
 "avatar_url": "https://<base>/api/avatars/6f1c….webp?v=3"}
```
`display_name` falls back to `username`. `avatar_url` is `null` when there is no avatar (clients draw initials). `account_verified` is `signup_method == "admin" or verified_at is not null`. `signup_method` is one of `admin|password|oauth`.

`Session`:
```json
{"access_token": "<jwt>", "token_type": "bearer", "expires_in": 86400,
 "refresh_token": "rt_…", "user": User}
```
`refresh_token` is present only for `client` ios/android. `expires_in` is 86400 for web and 3600 for mobile. The JWT claims are `sub` (username), `uid`, `tv`, `is_admin`, `is_first_login`, `iat`, `exp`.

`GameDelta`. It is empty when nothing was awarded, and it is always present where listed:
```json
{"xp": 150, "awards": [{"rule": "email_verified", "points": 50}],
 "badges": [{"id": "verified", "earned_at": "2026-11-11T10:00:00Z"}],
 "level_up": {"from": 1, "to": 2}}
```
When nothing was awarded: `{"xp": <total>, "awards": [], "badges": [], "level_up": null}`. When the game is disabled: `null`.

`Settings`. Every key is always present, and PATCH accepts any subset; unknown keys return 422:
```json
{"language": null, "theme": "system", "currency": "USD", "units": "metric", "timezone": null,
 "hide_game": false, "hide_community": false, "profile_visibility": "public", "telemetry_opt_out": false}
```
`language` is one of the 7 codes or `null`. `theme` is `system|light|dark`. `currency` matches `^[A-Z]{3}$`. `units` is `metric|imperial`. `timezone` is an IANA name that `zoneinfo` accepts, or `null`. `profile_visibility` is `public|followers|private`.

### Discovery

| Method, path | Auth | Request | 200 response | Errors |
|---|---|---|---|---|
| `GET /config` (additive) | — | — | existing keys plus `"auth": {"signup_mode": "open"\|"invite", "signup_available": bool, "password_reset_available": bool, "min_password_length": 10, "verify_ttl_s": 1800}`, and `features.accounts: true`, `features.game: bool` | — |
| `GET /auth/providers` (filled in) | — | — | `{"providers": [{"id": "apple"\|"google"\|"facebook"\|"github", "configured": bool, "start_url": "/api/auth/oauth/<id>/start" \| null, "id_token": bool}]}`, always in the order apple, google, facebook, github | — |

`signup_available` = email delivery available (SMTP set, or dev link logging on). `password_reset_available` uses the same rule. `id_token` is true when native ID-token sign-in is configured (Apple and Google only).

### Native accounts

| Method, path | Auth | Request | Success | Errors |
|---|---|---|---|---|
| `POST /auth/signup` | — | `{"username", "email", "password", "display_name"?, "invite_code"?, "locale"?, "client"?}` | `202 {"status": "verification_sent", "email": "<as given, lower-cased>", "expires_in": 1800}`. The same response when the email already belongs to an active account: that owner gets an "already registered" email instead, and nothing is created | `409 username_taken`, `422 username_invalid`, `422 username_reserved`, `422 email_invalid`, `422 password_too_short`, `422 password_too_long`, `422 password_common`, `422 password_matches_identity`, `422 display_name_invalid`, `403 invite_required`, `403 invite_invalid`, `503 email_unavailable`, `429 rate_limited` |
| `POST /auth/verify-email/resend` | — | `{"email", "locale"?}` | `202 {"status": "verification_sent"}`, always (no enumeration) | `429 rate_limited`, `503 email_unavailable` |
| `POST /auth/verify-email` | — | `{"token", "client"?, "device_name"?}` | `200 {"status": "verified", "session": Session \| null, "game": GameDelta}`. `session` is set when the token activated a pending account and `null` when it confirmed an email on an already active account | `400 token_invalid`, `410 token_expired`, `409 token_used`, `409 email_changed` (the account's email is no longer the one the token was issued for) |
| `POST /auth/password-reset/request` | — | `{"email", "locale"?}` | `202 {"status": "reset_sent"}`, always | `429 rate_limited`, `503 email_unavailable` |
| `POST /auth/password-reset/confirm` | — | `{"token", "new_password", "client"?, "device_name"?}` | `200 {"status": "password_reset", "session": Session}`. It bumps `token_version` and revokes every refresh token. A pending account becomes active and verified (the email is proven) | `400 token_invalid`, `410 token_expired`, `409 token_used`, the password errors above |
| `POST /account/email/verify` | yes | `{"locale"?}` | `202 {"status": "verification_sent", "email": "…", "expires_in": 1800}` | `409 already_verified`, `422 no_email`, `503 email_unavailable`, `429 rate_limited` |

Username rule: lower-cased, then `^[a-z0-9_]{3,20}$`, not in `RESERVED_USERNAMES` (Task 2), and unique case-insensitively against every existing username. Email: the existing `_EMAIL_RE`, lower-cased, ≤ 254. `display_name`: NFC, stripped, 1–50 characters, no control characters. Tokens expire 30 minutes after issue and are single use. Issuing a new token of the same purpose invalidates the previous ones. Emails go to `<base>/verify?token=…` and `<base>/reset-password?token=…`.

### Sessions

| Method, path | Auth | Request | Success | Errors |
|---|---|---|---|---|
| `POST /auth/login` (additive) | — | `{"username", "password", "client"?, "device_name"?}`. `username` may also be the account's email | `200 Session`, with the legacy keys kept: `user.username`, `user.is_admin`, `user.requires_password_change`, `user.email` | `401` (unchanged text) for bad credentials, `403 {"error_code": "account_pending", "email_hint": "j•••@example.com"}` only when the password was right, `429` |
| `POST /auth/refresh` | — | `{"refresh_token"}` | `200 {"access_token", "token_type": "bearer", "expires_in": 3600, "refresh_token": "rt_…"}`, rotated | `401 refresh_stale` (an already-rotated token reused ≤ 30 s after rotation; the family is kept), `401 refresh_invalid` (unknown, expired, revoked, user inactive, or reused after the grace window, which revokes the family), `429` |
| `POST /auth/logout` | optional | `{"refresh_token"?}` | `204`, and revokes that refresh token's family | — |
| `POST /auth/logout-all` | yes | — | `204`; bumps `token_version` and revokes every refresh token | — |
| `POST /auth/change-password` (additive) | yes | `{"current_password", "new_password", "client"?}`. `current_password` may be `""` when `has_password` is false | `200 {"access_token", "token_type", "expires_in"}`, plus `refresh_token` for mobile. Bumps `token_version`, revokes every refresh token, and the new token keeps this session alive | `400` "Current password is incorrect" (unchanged), the password errors above as `400` with `error_code` |
| `GET /auth/me` (additive) | yes | — | `User` | `401 session_revoked` when `tv` is stale |
| `PUT /auth/email` (additive) | yes | unchanged | `{"email", "email_verified": false, "verification_sent": bool}`. A changed email starts unverified, and a link is sent when email is available | unchanged |

Any authenticated route answers `401 {"error_code": "session_revoked"}` when the JWT's `tv` ≠ `users.token_version`.

### OAuth

`<p>` is one of `apple`, `google`, `facebook`, `github`.

| Method, path | Auth | Request | Success | Errors |
|---|---|---|---|---|
| `GET /auth/oauth/<p>/start` | — (browser navigation) | query `client=web\|ios\|android`, `return_to=/path` (web; same-origin path, default `/`), `challenge=<b64url S256>` (required for ios/android), `redirect_uri=<allow-listed>` (ios/android; default `<base>/auth/callback`), `link=<ticket>` (optional) | `302` to the provider. Sets the cookie `tp_oauth=<binding>` (HttpOnly, Path `/api/auth/oauth`, Max-Age 600, `SameSite=None; Secure` on https, else `Lax`) | Unknown `<p>`: `404`. Not configured, bad `return_to`, missing `challenge` or bad `redirect_uri`: `302` to `<final>?error=<code>` |
| `GET`/`POST /auth/oauth/<p>/callback` | — (provider redirect; Apple uses POST `form_post`) | the provider's `code`, `state`, `error`, Apple's `user` | `302` to `<final>?code=<handoff>` | `302` to `<final>?error=<code>` |
| `POST /auth/oauth/exchange` | — (web also sends the `tp_oauth` cookie) | `{"code", "verifier"?, "device_name"?}` (the client type is the one given at start) | one of the three results below | `400 code_invalid` (unknown, expired, used, or the cookie/verifier doesn't match) |
| `POST /auth/oauth/complete` | — | `{"signup_token", "username", "display_name"?, "invite_code"?, "client"?, "device_name"?, "locale"?}` | `201 {"status": "signed_in", "session": Session, "game": GameDelta}` | `400 signup_token_invalid`, `409 username_taken`, `422 username_invalid`, `422 username_reserved`, `403 invite_required`, `403 invite_invalid` |
| `POST /auth/oauth/link-ticket` | yes | `{"provider", "client"?}` | `200 {"start_url": "/api/auth/oauth/<p>/start?link=<ticket>&client=web"}` (the ticket lasts 5 min and is single use) | `404 provider_unknown`, `409 provider_unavailable` |
| `POST /auth/oauth/<p>/id-token` (apple, google) | — | `{"id_token", "nonce"?, "authorization_code"? (apple), "display_name"?, "client": "ios"\|"android", "device_name"?}` | the same results as exchange | `404` when native is not configured for `<p>`, `400 id_token_invalid` |
| `DELETE /account/identities/<p>` | yes | — | `204` | `404 identity_not_found`, `409 last_sign_in_method` |

`<final>` is `<base>/auth/callback` for web, or the client's `redirect_uri` for mobile. `redirect_uri` must exactly match one entry of `OAUTH_MOBILE_REDIRECTS` (default `["voyager://auth/callback", "<base>/auth/callback"]`). Callback error codes: `cancelled`, `state_invalid`, `provider_error`, `provider_unavailable`, `email_in_use_unverified`, `identity_in_use`, `account_inactive`, `bad_request`. The handoff code lasts 120 s and is single use. Web exchange needs the `tp_oauth` cookie whose hash was stored at start. Mobile exchange needs `verifier`, with `b64url(sha256(verifier)) == challenge`.

Exchange / id-token results:
```json
{"status": "signed_in", "session": Session, "game": GameDelta, "return_to": "/"}
{"status": "needs_username", "signup_token": "…", "suggested_username": "jane", "display_name": "Jane Doe",
 "email": "jane@example.com", "invite_required": false, "return_to": "/"}
{"status": "linked", "provider": "github", "return_to": "/account"}
```
`signup_token` lasts 30 min. `email` is `null` when the provider gave none.

### Account

| Method, path | Auth | Request | Success | Errors |
|---|---|---|---|---|
| `GET /account` | yes | — | `{"user": User, "identities": [{"provider", "email", "linked_at"}], "settings": Settings, "onboarding": Onboarding}` | — |
| `PATCH /account` | yes | `{"display_name"}` | `{"user": User}` | `422 display_name_invalid` |
| `GET /account/settings` | yes | — | `Settings` | — |
| `PATCH /account/settings` | yes | a subset of `Settings` | `Settings` | `422` (FastAPI default) |
| `PUT /account/onboarding` | yes | `{"step": 0..5, "done": bool, "skipped"?: bool, "traveller_type"?: "^[a-z_]{1,32}$"}` | `{"onboarding": Onboarding, "game": GameDelta}` | `422` |
| `PUT /account/avatar` | yes | `multipart/form-data`, field `file` (jpeg/png/webp/gif), ≤ 2 MB | `200 {"avatar_url": "…"}` | `413 avatar_too_large`, `415 avatar_type`, `422 avatar_unreadable` |
| `DELETE /account/avatar` | yes | — | `200 {"avatar_url": null}` | — |
| `GET /avatars/<user_id>.webp` | — | — | `image/webp`, `Cache-Control: public, max-age=31536000, immutable` | `404` |
| `GET /account/export` | yes | — | `200 application/json` with `Content-Disposition: attachment; filename="voyager-export-<username>-<YYYY-MM-DD>.json"`: `{"format": "voyager-export", "version": 1, "exported_at", "account", "identities", "settings", "onboarding", "preferences", "plans", "recent_searches", "taste", "feedback", "fare_watches", "price_watches", "notifications", "devices", "game"}` | `429` |
| `DELETE /account` | yes | `{"password"}` when `has_password`, else `{"confirm_username"}` | `204`. Deletes everything the export lists, the avatar file and the user's telemetry rows, and revokes Apple tokens | `403 password_incorrect`, `400 confirmation_mismatch`, `409 last_admin` |
| `GET /account/quota` | yes | — | `{"day": "2026-11-11", "resets_at": "2026-11-12T00:00:00Z", "buckets": {"search": {"used": 3, "limit": 20}, "chat": …, "compare": …, "discover": …, "light_ai": …, "import": …}}`. `limit` is `null` when unlimited (admin, or quotas off) | — |

`Onboarding`: `{"step": 0, "done": false, "skipped": false, "traveller_type": null, "completed_at": null}`. Once `done` is true it stays true, and starter XP is awarded once, when `done && !skipped`.

### AI gate (on every `_limited(...)` route and chat full plans)

- `403 {"detail": "Confirm your email to use the AI planner.", "error_code": "email_unverified"}` for a signed-in user whose `account_verified` is false.
- `429 {"detail": "You've used today's AI allowance for <label>. It resets at midnight UTC.", "error_code": "ai_daily_quota", "bucket": "search", "resets_at": "…"}` with `Retry-After` = seconds to the next UTC midnight. Chat refuses in-stream with that text, the same way it handles the search bucket today.

### Game

| Method, path | Auth | Success | Errors |
|---|---|---|---|
| `GET /game/me` | yes | `{"xp": 150, "level": 2, "level_min_xp": 100, "next_level_xp": 250, "badges": [{"id", "progress", "target", "earned_at"}], "streaks": {"daily": {"current", "longest", "last_day", "freezes"}}, "recent": [{"rule", "points", "created_at"}], "hidden": false}` (`recent` is the last 10) | `404` when `GAME_ENABLED=false` |
| `GET /game/catalog` | — | `{"version": 1, "rules": [{"id", "points", "daily_cap", "once"}], "badges": [{"id", "rule", "target", "tier": "bronze"\|"silver"\|"gold", "icon": "<lucide name>"}], "levels": [{"level": 1, "min_xp": 0}, …]}` with `Cache-Control: max-age=300` | `404` when disabled |

Clients translate badge and rule names by id: `game:badges.<id>.name` / `.desc`, `game:rules.<id>`.

### Admin (additive)

| Method, path | Request | Success | Errors |
|---|---|---|---|
| `POST /admin/invites` | `{"max_uses": 1..1000 = 1, "expires_in_days": 1..365 = 14, "note"?: "≤ 80 chars"}` | `201 {"id", "code": "VOY-XXXX-XXXX", "code_prefix": "VOY-XXXX", "max_uses", "uses": 0, "expires_at", "note"}` (the code is shown only here) | `422` |
| `GET /admin/invites` | — | `[{"id", "code_prefix", "max_uses", "uses", "expires_at", "revoked_at", "note", "created_at"}]` | — |
| `DELETE /admin/invites/<id>` | — | `204` (revokes it) | `404` |

`GET /admin/users` rows also gain `signup_method`, `account_status`, `email_verified`, `display_name` (no tokens and no hashes).

---

## Shared-file hotspots and how conflicts are avoided

| Hotspot | Rule |
|---|---|
| `backend/app/main.py` (router list, lifespan, middleware) | Only Task 1 edits it. It registers **every** Phase 1 router (stub modules), the body-size limit for avatars, the table creation and the maintenance loop. Later tasks fill their own router module. |
| `backend/app/core/config.py` | Only Task 1, which adds every Phase 1 setting (list in Task 1). |
| `backend/app/db/users_db.py` | Only Task 2. It provides every user-row helper later tasks need. |
| `backend/app/api/routes/auth.py`, `backend/app/api/routes/admin.py` | Only Task 7 (admin invites live in the new `admin_invites.py`). |
| `backend/app/core/rate_limit.py`, `backend/app/agents/chat_agent.py`, `backend/tests/conftest.py` | Only Task 14. |
| `backend/app/api/routes/client_config.py` | Only Task 27. |
| `backend/app/telemetry/registry.py` + `docs/Telemetry.md` | Only Task 4, which adds every Phase 1 event up front. |
| Game award call sites | Task 1 freezes `backend/app/game/hooks.py` as no-op stubs. Task 10 fills the bodies. Tasks 12 and 27 call the hooks. |
| `frontend/src/services/api.js` | **Not edited in Phase 1.** Task 5 creates `services/authApi.js`, `accountApi.js`, `gameApi.js` and `apiError.js` with every call in the contract. UI tasks only import them. |
| `frontend/src/App.jsx`, `context/AuthContext.jsx`, `components/ui/NavBar.jsx`, `telemetry/routes.js` | Only Task 5. It adds every route, stub page and stub component. Each later task overwrites only its own stub file. |
| Locale JSON | One **new** namespace per task (named in each task). No Phase 1 task edits an existing namespace. Task 5 owns `errors` (every `error_code`). |
| `frontend/src/pages/AdminPage.jsx` | Only Task 26. |
| `frontend/src/components/auth/SocialSignInButtons.jsx` | Only Task 18. |
| `frontend/src/pages/LoginPage.jsx` | Only Task 15. |
| Docs (`CLAUDE.md`, `docs/Configuration.md`, `API-Reference.md`, `Deployment-GCP.md`, `Privacy.md`, `Feature-Parity.md`) | Only Task 36. Task 6 creates `docs/Accounts-API.md` and is the only Phase 1 edit to `mkdocs.yml`. |

---

## Wave 0 — seams and contract

### Task 1: Backend seams (settings, error envelope, URLs, router stubs, hooks, quota seam)

**Files:**
- Create: `backend/app/core/errors.py`, `backend/app/core/urls.py`, `backend/app/services/account_maintenance.py` (`async account_maintenance()`, the hourly loop below), `backend/app/core/session_payload.py`, `backend/app/core/ai_quota.py` (stub), `backend/app/game/__init__.py`, `backend/app/game/hooks.py` (stubs), `backend/app/api/routes/{signup,sessions,oauth,account,avatars,account_data,game,quota,admin_invites}.py` (each `router = APIRouter()`)
- Modify: `backend/app/core/config.py`, `backend/app/main.py`
- Test: `backend/tests/test_phase1_seams.py`

**Interfaces:**
- Consumes: Task 2 `create_account_tables()`, `purge_expired(now) -> dict[str, int]` (wired in the final step, after Task 2 merges).
- Produces:
  - `class ApiError(Exception): __init__(self, status: int, code: str, detail: str, *, headers: dict | None = None, **extra)`. The handler in `main.py` returns `{"detail", "error_code", **extra}`.
  - `public_base_url() -> str`; `public_url(path: str) -> str` (path starts with `/`).
  - `user_payload(user: dict) -> dict`: the `User` object in the contract. `avatar_url` is `public_url(f"/api/avatars/{id}.webp?v={avatar_rev}")` only when `avatar_source` is set **and** `$DATA_DIR/avatars/<id>.webp` exists. `has_password` is `password_hash != "!"`.
  - `game.hooks.on_email_verified(user_id: str) -> dict | None` and `on_onboarding_complete(user_id: str) -> dict | None`. The stubs return `None`.
  - `ai_quota.daily_quota(bucket: str) -> Callable`, a FastAPI dependency. The stub does nothing. `_limited(bucket)` becomes `[Depends(require_ai_access), Depends(rate_limit(bucket)), Depends(daily_quota(bucket))]`.
  - Settings (with these defaults): `signup_mode: Literal["open","invite"] = "open"`, `email_log_links: bool = False`, `account_token_ttl_minutes: int = 30`, `pending_purge_days: int = 7`, `refresh_token_days: int = 60`, `refresh_family_max_days: int = 365`, `mobile_access_token_minutes: int = 60`, `google_client_id/google_client_secret: str = ""`, `google_native_client_ids: list[str] = []`, `github_client_id/github_client_secret: str = ""`, `facebook_app_id/facebook_app_secret: str = ""`, `facebook_graph_version: str = "v24.0"`, `facebook_email_trusted: bool = False`, `apple_services_id/apple_team_id/apple_key_id/apple_private_key: str = ""`, `apple_native_client_ids: list[str] = []`, `oauth_mobile_redirects: list[str] = ["voyager://auth/callback"]` (`<base>/auth/callback` is always allowed as well), `ai_daily_quota_enabled: bool = True`, `ai_daily_quota_search: int = 20`, `…_chat: int = 100`, `…_compare: int = 40`, `…_discover: int = 20`, `…_light_ai: int = 200`, `…_import: int = 20` (0 = unlimited), `game_enabled: bool = True`, `game_rules_path: str = ""`, `rate_limit_auth_email: int = 10`, `rate_limit_email_address: int = 3`, `rate_limit_signup: int = 5`, `rate_limit_oauth: int = 30`, `rate_limit_refresh: int = 60`, `rate_limit_account: int = 30`.
  - `main.py`: includes the nine new routers with `prefix="/api"`. Adds `BodySizeLimit(prefix="/api/account/avatar", max_bytes=2*1024*1024 + 64*1024, message="That image is too big — use one under 2 MB.")`. In the lifespan, after `create_users_table()`, calls `create_account_tables()` and starts `account_maintenance()` (every 3600 s, `await asyncio.to_thread(purge_expired, now)`, logging errors and never raising, cancelled on shutdown like `telemetry_task`).

- [ ] **Step 1: Write failing tests**: `test_api_error_envelope` (a route raising `ApiError(409, "username_taken", "x", bucket="s")` → `{"detail": "x", "error_code": "username_taken", "bucket": "s"}`); `test_public_url_prefers_public_base_url` (`PUBLIC_BASE_URL=https://a.example/` → `public_url("/verify") == "https://a.example/verify"`; empty → falls back to `APP_BASE_URL`); `test_user_payload_shape` (keys equal the contract `User` set; `display_name` falls back to the username; `avatar_url` is `None` when the file is missing; `password_hash "!"` → `has_password False`); `test_stub_routers_importable` (each of the nine modules exposes an `APIRouter` named `router`, and `GET /api/account` answers 404 or 405 rather than failing at import); `test_limited_includes_quota_dependency`.
- [ ] **Step 2: Run** `cd backend && python3 -m pytest -q tests/test_phase1_seams.py` → FAIL.
- [ ] **Step 3: Implement**, except the lifespan wiring.
- [ ] **Step 4: Rebase on Task 2** and add the lifespan wiring. Run the whole backend suite and `ruff check backend/` → PASS.
- [ ] **Step 5: Commit** `feat(accounts): phase 1 seams — settings, error envelope, URLs, router stubs`

### Task 2: Schema + user-row helpers

**Files:**
- Create: `backend/app/db/accounts_schema.py`, `backend/app/db/reserved_usernames.py`
- Modify: `backend/app/db/users_db.py`
- Test: `backend/tests/test_accounts_schema.py`, `backend/tests/test_users_db_phase1.py`

**Interfaces:**
- Produces:
  - `create_account_tables() -> None`. It is idempotent. It adds `users` columns with `ALTER TABLE … ADD COLUMN` when missing: `email_verified INTEGER NOT NULL DEFAULT 0`, `account_status TEXT NOT NULL DEFAULT 'active'` (`active|pending`), `signup_method TEXT NOT NULL DEFAULT 'admin'`, `verified_at TEXT`, `token_version INTEGER NOT NULL DEFAULT 0`, `display_name TEXT`, `avatar_source TEXT` (`upload|provider`), `avatar_rev INTEGER NOT NULL DEFAULT 0`, `locale TEXT`, `last_login_at TEXT`, `invite_id INTEGER`. It also creates indexes on `lower(username)` and `lower(email)` (non-unique; existing data may predate the rule) and these tables:
    - `account_tokens(id INTEGER PK, user_id TEXT NOT NULL, purpose TEXT NOT NULL CHECK(purpose IN ('verify_email','reset_password')), token_hash TEXT NOT NULL UNIQUE, email TEXT NOT NULL, created_at TEXT NOT NULL, expires_at TEXT NOT NULL, used_at TEXT)`, with an index on `(user_id, purpose)`
    - `refresh_tokens(id TEXT PK, user_id TEXT NOT NULL, family_id TEXT NOT NULL, token_hash TEXT NOT NULL UNIQUE, client TEXT NOT NULL, device_name TEXT, token_version INTEGER NOT NULL, created_at TEXT NOT NULL, last_used_at TEXT, expires_at TEXT NOT NULL, family_expires_at TEXT NOT NULL, rotated_at TEXT, revoked_at TEXT)`, with indexes on `user_id` and `family_id`
    - `user_identities(id INTEGER PK, user_id TEXT NOT NULL, provider TEXT NOT NULL, subject TEXT NOT NULL, email TEXT, email_verified INTEGER NOT NULL DEFAULT 0, display_name TEXT, picture_url TEXT, secret_enc TEXT, created_at TEXT NOT NULL, last_used_at TEXT, UNIQUE(provider, subject))`, with an index on `user_id`
    - `oauth_tickets(hash TEXT PK, kind TEXT NOT NULL CHECK(kind IN ('state','handoff','signup','link')), provider TEXT, user_id TEXT, data TEXT NOT NULL DEFAULT '{}', binding_hash TEXT, client_challenge TEXT, created_at TEXT NOT NULL, expires_at TEXT NOT NULL, used_at TEXT)`
    - `invite_codes(id INTEGER PK, code_hash TEXT NOT NULL UNIQUE, code_prefix TEXT NOT NULL, note TEXT, max_uses INTEGER NOT NULL, uses INTEGER NOT NULL DEFAULT 0, created_by TEXT, created_at TEXT NOT NULL, expires_at TEXT NOT NULL, revoked_at TEXT)`
    - `user_settings(user_id TEXT PK, data TEXT NOT NULL, updated_at TEXT NOT NULL)`
    - `user_onboarding(user_id TEXT PK, step INTEGER NOT NULL DEFAULT 0, done INTEGER NOT NULL DEFAULT 0, skipped INTEGER NOT NULL DEFAULT 0, traveller_type TEXT, completed_at TEXT, updated_at TEXT NOT NULL)`
    - `ai_usage_daily(day TEXT, user_key TEXT, bucket TEXT, used INTEGER NOT NULL DEFAULT 0, PRIMARY KEY(day, user_key, bucket))`
    - `xp_ledger(id INTEGER PK, user_id TEXT NOT NULL, rule TEXT NOT NULL, points INTEGER NOT NULL, idem_key TEXT NOT NULL UNIQUE, meta TEXT, created_at TEXT NOT NULL)`, with indexes on `(user_id, created_at)` and `(user_id, rule, created_at)`
    - `user_badges(user_id TEXT, badge_id TEXT, progress INTEGER NOT NULL, target INTEGER NOT NULL, earned_at TEXT, updated_at TEXT NOT NULL, PRIMARY KEY(user_id, badge_id))`
    - `user_streaks(user_id TEXT, kind TEXT, current INTEGER NOT NULL, longest INTEGER NOT NULL, last_day TEXT, freezes INTEGER NOT NULL, freeze_week TEXT, updated_at TEXT NOT NULL, PRIMARY KEY(user_id, kind))`
  - `purge_expired(now: datetime) -> dict[str, int]`. It deletes `pending` users older than `pending_purge_days` (and their `account_tokens`), `account_tokens` 1 day past expiry, `oauth_tickets` past expiry, refresh tokens 7 days past expiry or revocation, and `ai_usage_daily` older than 8 days. It returns counts per table.
  - In `users_db.py`:
    - `create_user(..., signup_method="admin", account_status="active", email_verified=False, display_name=None, locale=None, password_hash=None)`. It lower-cases the email, and `password_hash="!"` marks an account with no password.
    - `get_user_by_login(identifier: str) -> dict | None` (an exact username, else a case-insensitive username, else a lower-cased email)
    - `get_user_by_email(email) -> dict | None`
    - `username_available(name: str, now: datetime) -> bool`: case-insensitive. A `pending` holder whose newest token has expired doesn't count, and is deleted.
    - `create_pending_user(username, email, password, display_name, locale, invite_id) -> dict`: inside `BEGIN IMMEDIATE`. It replaces a pending row with the same email, and raises `UsernameTakenError` or `EmailInUseError`.
    - `activate_user(user_id, email)`: sets `account_status='active'`, `email_verified=1`, and `verified_at` if null.
    - `mark_email_verified(user_id, email) -> bool`: false if the email changed.
    - `bump_token_version(user_id) -> int`
    - `set_display_name(user_id, name)`
    - `set_avatar(user_id, source: str | None) -> int` (bumps `avatar_rev`)
    - `touch_last_login(user_id)`
    - `count_active_admins() -> int`
    - `delete_user_row(user_id)`
    - The existing `set_email` sets `email_verified=0` whenever the address changes. `deactivate_user` and `admin_reset_password` bump `token_version`.
  - `RESERVED_USERNAMES: frozenset[str]` (admin, administrator, root, support, help, voyager, api, system, null, undefined, me, account, settings, login, signup, verify, auth, share, plans, alerts, moderator, staff, official).

- [ ] **Step 1: Write failing tests**: `test_create_account_tables_idempotent` (run twice; an old-shape `users` table gains every column; existing rows read `signup_method 'admin'`, `token_version 0`); `test_username_taken_is_case_insensitive`; `test_expired_pending_releases_username`; `test_pending_with_same_email_is_replaced`; `test_set_email_resets_verified`; `test_deactivate_bumps_token_version`; `test_purge_expired_counts` (a pending user 8 days old is removed, a 6-day-old one stays); `test_login_by_email`.
- [ ] **Step 2: Run** → FAIL. **Step 3: Implement.** **Step 4: Run** the backend suite → PASS (`test_auth.py` and `test_admin*` unchanged).
- [ ] **Step 5: Commit** `feat(accounts): schema for accounts, sessions, identities, quotas and game`

### Task 3: Password policy

**Files:**
- Create: `backend/app/core/passwords.py` (its module docstring names the list's source and MIT licence), `backend/app/core/data/common_passwords.txt` (the 10,000 most common passwords from SecLists `Passwords/Common-Credentials/10k-most-common.txt`, MIT)
- Test: `backend/tests/test_passwords.py`

**Interfaces:**
- Produces: `MIN_PASSWORD_LENGTH_V2 = 10`, `MAX_PASSWORD_LENGTH = 128`, and `password_problem(password: str, *, username: str | None = None, email: str | None = None) -> str | None`, which returns one of `password_too_short`, `password_too_long`, `password_common` or `password_matches_identity`, or `None`. The list is loaded lazily into a `frozenset` of lower-cased entries. Call sites switch to it in Task 7.

- [ ] **Step 1: Write failing tests**: `"password12"` → `password_common`; `"Jane_Doe12"` with username `jane_doe12` → `password_matches_identity`; 9 characters → too short; 129 → too long; `"correct horse battery"` → `None`; the list file has ≥ 9,900 lines.
- [ ] **Step 2: Run** → FAIL. **Step 3: Implement.** **Step 4: Run** → PASS.
- [ ] **Step 5: Commit** `feat(accounts): password policy with common-password list`

### Task 4: Telemetry events for Phase 1

**Files:**
- Modify: `backend/app/telemetry/registry.py`, `docs/Telemetry.md` (one table row per event)
- Test: `backend/tests/test_telemetry_registry.py` (extend)

**Interfaces:**
- Produces these registry entries:
  - `auth_start{method: enum:<password|apple|google|facebook|github>, mode: enum:<signin|signup|link>}`
  - `auth_result{method: <same>, mode: <same>, result: enum:<ok|error|cancelled|coming_soon|needs_username|pending>, code: id}`
  - `signup_step{step: enum:<form|check_email|username|done>}`
  - `email_verify{result: enum:<ok|expired|invalid|used|resent|email_changed>}`
  - `password_reset{step: enum:<request|confirm>, result: enum:<ok|error|expired|invalid|used>}`
  - `account_action{action: enum:<avatar_upload|avatar_remove|name_change|settings_change|export|delete|link|unlink|signout_all|email_verify_request|change_password>}`
  - `quota_block{bucket: enum:<search|chat|compare|discover|light_ai|import>, reason: enum:<daily_quota|unverified>}`
  - `game_award{rule: id, points: int}`, `badge_earned{badge: id}`, `level_up{level: int}`, `game_view{surface: enum:<account|nav|celebration>}`

- [ ] **Step 1: Write failing tests**: `clean_event({"event":"auth_result","props":{"method":"google","mode":"signin","result":"ok","code":"jane@x.com"}})["props"]` has no `code`; every new event is in `EVENTS`; `test_every_event_documented` passes with the new rows.
- [ ] **Step 2: Run** → FAIL. **Step 3: Implement.** **Step 4: Run** → PASS.
- [ ] **Step 5: Commit** `feat(telemetry): phase 1 account and game events`

### Task 5: Frontend seams (API modules, error text, session, routes, stubs)

**Files:**
- Create: `frontend/src/services/authApi.js`, `frontend/src/services/accountApi.js`, `frontend/src/services/gameApi.js`, `frontend/src/services/apiError.js`, `frontend/src/hooks/useClientConfig.js`, `frontend/src/game/announce.js`, `frontend/src/i18n/locales/<lang>/errors.json` (7 files)
- Create, as stubs that render `null` (one per later task): `pages/SignupPage.jsx` (T15), `pages/VerifyEmailPage.jsx` and `pages/CheckEmailPage.jsx` (T16), `pages/ForgotPasswordPage.jsx` and `pages/ResetPasswordPage.jsx` (T17), `pages/OAuthCallbackPage.jsx` and `pages/ChooseUsernamePage.jsx` (T18), `pages/AccountPage.jsx` (renders the sections in order) and `components/account/{ProfileSection,AccountMenu}.jsx` (T19), `components/account/{SettingsSection,SettingsSync}.jsx` (T20), `components/account/SecuritySection.jsx` (T21), `components/account/DataSection.jsx` (T22), `components/account/{QuotaSection,VerifyBanner}.jsx` (T23), `components/game/{GameSection,GameNavChip,GameCelebration}.jsx` (T24)
- Modify: `frontend/src/App.jsx` (public routes `/signup`, `/check-email`, `/verify`, `/forgot-password`, `/reset-password`, `/auth/callback`, `/auth/username`; `/account` in `KNOWN_PATHS` + Layout; mounts `<SettingsSync/>`, `<VerifyBanner/>` and `<GameCelebration/>` in Layout), `frontend/src/context/AuthContext.jsx`, `frontend/src/components/ui/NavBar.jsx` (renders `<GameNavChip/>` and `<AccountMenu/>`), `frontend/src/telemetry/routes.js` (the new static paths)
- Test: `frontend/src/services/apiError.test.js`, `frontend/src/services/authApi.test.js`, `frontend/src/context/AuthContext.session.test.jsx`, `frontend/src/hooks/useClientConfig.test.js`

**Interfaces:**
- Consumes: the API contract.
- Produces:
  - `toApiError(err) -> {status: number, code: string | null, detail: string, retryAfter: number | null, extra: object}`; `errorText(t, apiErr) -> string`, which uses `t('errors:' + code)` when the key exists, else `detail`, else `errors:generic`.
  - `authApi.js` (each function resolves with `data` and rejects with `toApiError(...)`): `signup(body)`, `resendVerification(email)`, `verifyEmail(token)`, `requestPasswordReset(email)`, `confirmPasswordReset(token, newPassword)`, `exchangeOAuthCode(code)` (sends `credentials: 'same-origin'`), `completeOAuthSignup(body)`, `getLinkStartUrl(token, provider)`, `logoutAll(token)`, `changePasswordV2(token, current, next)`. Every call sends `client: 'web'` and `localeField()`.
  - `accountApi.js`: `getAccount`, `updateProfile`, `uploadAvatar(token, file)`, `removeAvatar`, `getSettings`, `patchSettings`, `putOnboarding`, `unlinkIdentity`, `requestEmailVerification`, `exportAccount(token) -> Promise<Blob>`, `deleteAccount(token, body)`, `getQuota`.
  - `gameApi.js`: `getGameMe(token)`, `getGameCatalog()`.
  - `useClientConfig() -> {config: object, loaded: boolean}`. It fetches once per page load and caches at module level; a 404 or network error gives `{}`. `signupAvailable(config)` and `resetAvailable(config)` helpers are false when `config.auth` is missing.
  - `announce.js`: `announceGame(delta)` and `onGameAnnounce(fn) -> unsubscribe`. These are an in-memory pub-sub, and a `null` or empty delta is ignored.
  - `AuthContext` adds `applySession(session) -> Promise<User>` (stores `tp_token`, sets the user, loads preferences, emits `setUserPresent(true)`), `refreshUser() -> Promise<void>` (re-reads `/api/auth/me`) and `accountVerified: boolean` (true when `user.account_verified !== false`, so the old backend counts as verified). `login()` now goes through `applySession`.
  - The `errors` namespace has one key per `error_code` in the contract, plus `generic`, in all 7 languages.

- [ ] **Step 1: Write failing tests**: `toApiError` on an axios error carrying `{detail, error_code:'ai_daily_quota', bucket:'search'}` and `Retry-After: 30` → `{status:429, code:'ai_daily_quota', retryAfter:30, extra:{bucket:'search'}}`; on a 422 FastAPI list detail → `code null`, with detail text from the first message; `errorText` for an unknown code returns `detail`; `useClientConfig` with a 404 → `signupAvailable(config) === false` (**old backend hides signup and account sections**); `applySession` stores the token and sets `user`; the catalogue parity test covers `errors`; `routeTemplate('/verify') === '/verify'`.
- [ ] **Step 2: Run** `cd frontend && npm test -- src/services src/context src/hooks` → FAIL.
- [ ] **Step 3: Implement**; translate `errors` into all 7 languages.
- [ ] **Step 4: Run** `npm test` + eslint + `npm run build` → PASS (the stubs render nothing, and every existing test is unchanged).
- [ ] **Step 5: Commit** `feat(accounts): frontend seams — API modules, error text, session, routes`

### Task 6: Publish the contract

**Files:**
- Create: `docs/Accounts-API.md` (the "API contract" section of this plan, verbatim, plus a "Mobile flow" walkthrough: native sign-up → universal link `/verify` → `POST /auth/verify-email` with `client`; OAuth with `ASWebAuthenticationSession`/Custom Tabs: generate a verifier, open `start?client=ios&challenge=…&redirect_uri=…`, receive `?code=`, `POST /auth/oauth/exchange` with `verifier`; refresh single-flight)
- Modify: `mkdocs.yml` (nav: Internals → "Accounts API")
- [ ] **Step 1:** Write the page. **Step 2:** `mkdocs build --strict` → PASS.
- [ ] **Step 3: Commit** `docs: frozen Phase 1 accounts API contract for mobile clients`

## Wave 1 — independent modules (backend and all UI)

### Task 7: Sessions (token version, refresh tokens, login/me/change-password)

**Files:**
- Create: `backend/app/db/sessions_db.py`, `backend/app/core/session.py`
- Modify: `backend/app/core/auth.py`, `backend/app/api/routes/auth.py`, `backend/app/api/routes/sessions.py`, `backend/app/api/routes/admin.py` (temporary and reset passwords use `password_problem`)
- Test: `backend/tests/test_sessions.py`, `backend/tests/test_auth.py` (unchanged, must pass)

**Interfaces:**
- Consumes: Task 1 `ApiError`, `user_payload`; Task 2 helpers; Task 3 `password_problem`.
- Produces:
  - `issue_session(user: dict, client: str = "web", device_name: str | None = None) -> dict`, which returns the contract `Session` and calls `touch_last_login`.
  - `create_access_token(data, *, minutes: int | None = None)` (kept compatible); claims `uid`, `tv`, `iat`.
  - `get_current_user` / `get_optional_user`: a stale `tv` → `ApiError(401, "session_revoked", …)` (the optional variant returns `None`); a missing `tv` = 0; a `pending` user → 401.
  - `sessions_db`: `create_refresh(user_id, client, device_name, token_version) -> str` (plaintext, `rt_` + `token_urlsafe(32)`); `rotate_refresh(token, now) -> tuple[str, dict] | RefreshError` (the reason is `stale` or `invalid`; a mismatched `token_version` is invalid); `revoke_family_of(token)`; `revoke_all(user_id)`.
  - Routes: `/auth/refresh`, `/auth/logout`, `/auth/logout-all` (in `sessions.py`, rate bucket `refresh`); the additive `/auth/login`, `/auth/me`, `/auth/change-password` and `/auth/email` per the contract.
- [ ] **Step 1: Write failing tests**: `test_login_response_keeps_legacy_keys`; `test_login_with_email`; `test_mobile_login_gets_refresh_token` (`client ios` → `refresh_token`, `expires_in 3600`); `test_pending_login_403_only_with_right_password` (a wrong password → 401); `test_old_token_without_tv_still_works`; `test_logout_all_revokes_access_and_refresh`; `test_refresh_rotates`; `test_refresh_reuse_within_grace_keeps_family`; `test_refresh_reuse_after_grace_revokes_family` (freeze the clock); `test_change_password_bumps_version_keeps_current_session`; `test_change_password_rejects_common` (`400`, `error_code password_common`); `test_set_password_when_no_password` (`current_password ""` with `password_hash "!"`).
- [ ] **Step 2: Run** → FAIL. **Step 3: Implement.** **Step 4: Run** the backend suite → PASS.
- [ ] **Step 5: Commit** `feat(accounts): revocable sessions and mobile refresh tokens`

### Task 8: Account emails

**Files:**
- Create: `backend/app/services/account_email.py`, `backend/app/i18n/__init__.py`, `backend/app/i18n/emails/{en,es,de,fr,hi,zh,bn}.json`
- Test: `backend/tests/test_account_email.py`, `backend/tests/test_email_catalog.py`

**Interfaces:**
- Consumes: `alert_email.send_message`, `alert_email._sender`, `alert_email._mail_domain`; Task 1 `public_url`.
- Produces:
  - `email_delivery_available() -> bool`: SMTP set, or `dev_links_enabled()`.
  - `dev_links_enabled() -> bool`: SMTP unset and (`email_log_links` or the base host is `localhost`/`127.0.0.1`).
  - `async send_account_email(kind: Literal["verify","reset","already_registered"], to: str, *, link: str | None, locale: str | None, username: str) -> bool`. It sends a multipart text + inline-styled HTML message with no remote images, through `asyncio.to_thread(send_message, msg)`. With dev links on, it logs `account_email.dev_link kind=<kind> url=<link>` at INFO instead of sending. It never logs the address, and failures are logged and return `False`.
  - Catalogue keys per kind: `subject`, `heading`, `body` (`{{minutes}}`, `{{username}}`), `button`, `ignore`, plus a shared `footer`. Unknown or missing locales fall back to `en`.
- [ ] **Step 1: Write failing tests**: the parity test (every language has the `en` key set, with the same `{{placeholders}}` and no empty values); `test_verify_email_contains_link_and_30_minutes`; `test_dev_link_logged_only_when_enabled` (`caplog`: SMTP unset with the base `https://x.sslip.io` → nothing logged and `False`; with `EMAIL_LOG_LINKS=true` → logged); `test_html_has_no_remote_images`; `test_hindi_subject_used_for_hi`.
- [ ] **Step 2: Run** → FAIL. **Step 3: Implement**; translate into all 7 languages. **Step 4: Run** → PASS.
- [ ] **Step 5: Commit** `feat(accounts): localised verify, reset and already-registered emails`

### Task 9: Invite codes

**Files:**
- Create: `backend/app/db/invites_db.py`
- Modify: `backend/app/api/routes/admin_invites.py`
- Test: `backend/tests/test_invites.py`

**Interfaces:**
- Produces:
  - `create_invite(created_by, max_uses, expires_in_days, note) -> dict` (the code is `VOY-` + two groups of 4 characters from `ABCDEFGHJKMNPQRSTUVWXYZ23456789`, and the dict includes the plaintext `code`)
  - `check_invite(code) -> int | None` (an id if usable)
  - `consume_invite(code) -> int | None`: an atomic `UPDATE … SET uses = uses + 1 WHERE code_hash = ? AND uses < max_uses AND revoked_at IS NULL AND expires_at > ?`. It is case-insensitive and ignores spaces and dashes.
  - `list_invites()`, `revoke_invite(id) -> bool`
  - The admin routes per the contract (`require_admin`).
- [ ] **Step 1: Write failing tests**: create → consume → `uses 1`; `test_last_use_cannot_be_redeemed_twice` (two threads on a `max_uses 1` code → exactly one id); an expired or revoked code → `None`; `"voy 7k2m 9qxr"` matches; admin-only (403 for a user); the code is never in the list response.
- [ ] **Step 2: Run** → FAIL. **Step 3: Implement.** **Step 4: Run** → PASS.
- [ ] **Step 5: Commit** `feat(accounts): invite codes for SIGNUP_MODE=invite`

### Task 10: Game engine

**Files:**
- Create: `backend/app/game/rules.json`, `backend/app/game/rules.py`, `backend/app/game/engine.py`, `backend/app/db/game_db.py`
- Modify: `backend/app/game/hooks.py` (fill in the bodies), `backend/app/api/routes/game.py`
- Test: `backend/tests/test_game_engine.py`, `backend/tests/test_game_api.py`

**Interfaces:**
- Consumes: Task 2 tables.
- Produces:
  - `rules.json` v1: `rules` = `email_verified {points 50, daily_cap 1, once true}` and `onboarding_complete {points 100, daily_cap 1, once true}`; `badges` = `verified {rule email_verified, target 1, tier bronze, icon "mail-check"}` and `first_steps {rule onboarding_complete, target 1, tier bronze, icon "footprints"}`; `levels` min_xp = `[0, 100, 250, 500, 1000, 2000, 3500, 5500, 8000, 12000]`; `streaks` = `daily {freeze_per_week 1}`.
  - `load_rules(path: str | None = None) -> Rules` (pydantic-validated). An invalid override file is logged and the built-in file is used.
  - `award(user_id: str, rule: str, idem_key: str, *, meta: dict | None = None, now: datetime | None = None) -> dict`, which returns a `GameDelta`. An unknown rule raises `KeyError`. A duplicate `idem_key` or a reached daily cap → an empty delta. A `once` rule uses `idem_key = f"{rule}:{user_id}"` whatever is passed. Badge progress and `level_up` are computed in the same transaction.
  - `summary(user_id: str, *, hidden: bool) -> dict`, the `/game/me` shape.
  - `touch_streak(user_id: str, kind: str, day: date) -> dict`. Same day → no change; an earlier day → ignored; next day → `current + 1`; `missed = gap - 1` with `missed <= freezes` → consume `missed` freezes and `current + 1`; otherwise `current = 1`. `freezes` refills to `freeze_per_week` when `day`'s ISO week differs from `freeze_week` (refill first), and `longest = max(longest, current)`. No Phase 1 hook calls it.
  - `hooks.on_email_verified` → `award(uid, "email_verified", …)`; `on_onboarding_complete` → `award(uid, "onboarding_complete", …)`. Both return `None` when `game_enabled` is false, and they catch and log every exception (a game failure never breaks auth).
  - Routes `/game/me` (auth; `hidden` read from `user_settings.hide_game`; the settings table is read directly) and `/game/catalog`, both `404` when disabled.
- [ ] **Step 1: Write failing tests**: `test_award_once_is_idempotent` (twice → the second delta is empty and the ledger has 1 row); `test_daily_cap`; `test_level_up_reported` (100 XP from level 1 → `{"from":1,"to":2}`); `test_badge_earned_with_progress`; streaks: `test_streak_next_day`, `test_streak_freeze_covers_one_missed_day`, `test_streak_resets_after_two_missed_days`, `test_freeze_refills_each_iso_week`; `test_invalid_override_falls_back`; `test_hooks_swallow_errors`; the API: `/game/me` shape, `/game/catalog` cache header, `404` when disabled.
- [ ] **Step 2: Run** → FAIL. **Step 3: Implement.** **Step 4: Run** → PASS.
- [ ] **Step 5: Commit** `feat(game): XP ledger, badges, levels and streaks engine`

### Task 11: OAuth core (provider protocol, PKCE, JWKS, test IdP)

**Files:**
- Create: `backend/app/services/oauth/__init__.py`, `backend/app/services/oauth/base.py`, `backend/app/services/oauth/jwks.py`, `backend/app/services/oauth/registry.py`, `backend/app/services/oauth/secrets_box.py`, `backend/tests/oauth_fakes.py`
- Modify: `backend/requirements.txt` (`cryptography>=44,<47`, pinned to a release ≥ 2 weeks old)
- Test: `backend/tests/test_oauth_core.py`

**Interfaces:**
- Produces:
  - `@dataclass(frozen=True) ProviderProfile(subject: str, email: str | None, email_verified: bool, email_trusted: bool, display_name: str | None, picture_url: str | None)`.
  - `class OAuthError(Exception)` with a `.code` (a contract callback error code).
  - `class OAuthProvider(Protocol)`: `id: str`, `uses_pkce: bool`, `callback_methods: tuple[str, ...]`, `configured() -> bool`, `native_configured() -> bool`, `authorize_url(*, redirect_uri, state, nonce, code_challenge) -> str`, `async exchange(*, code, redirect_uri, code_verifier, nonce, form: dict) -> tuple[ProviderProfile, str | None]` (the second item is a secret to store, Apple's refresh token), `async verify_id_token(id_token, *, nonce: str | None) -> ProviderProfile` (native; the default raises `OAuthError("bad_request")`), `async revoke(secret: str) -> None` (the default does nothing).
  - `registry.PROVIDER_ORDER = ("apple", "google", "facebook", "github")`; `get_provider(id) -> OAuthProvider | None` (it imports `services.oauth.<id>` lazily and reads `PROVIDER`; an `ImportError` → `None`, so providers merge independently); `override(id, provider)` for tests.
  - `pkce_verifier() -> str` (43–128 characters), `pkce_challenge(verifier) -> str` (b64url SHA-256, no padding).
  - `http_client() -> httpx.AsyncClient` (timeout 10 s, `User-Agent: Voyager/1`); `set_transport(transport | None)` for tests.
  - `jwks.verify_jwt(token, *, jwks_url, issuers: set[str], audiences: set[str], nonce: str | None = None, nonce_is_hash: bool = False) -> dict`. Keys are cached for 1 h, an unknown `kid` refetches once, and the algorithms are RS256/ES256 only. Leeway is 60 s.
  - `secrets_box.seal(text) -> str`, `open_(token) -> str | None`.
  - `oauth_fakes.FakeIdP(issuer, audience)`: an RSA key, `.jwks()`, `.id_token(**claims)`, `.transport(routes: dict[str, Callable])` → an `httpx.MockTransport`.
- [ ] **Step 1: Write failing tests**: the RFC 7636 appendix B vector (`dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk` → `E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM`); `verify_jwt` accepts the FakeIdP token and rejects a wrong aud, iss, nonce or an expired token; an unknown `kid` refetches once; `get_provider("google") is None` before Task 28 exists (use a monkeypatched import); seal/open round trip; open with another JWT secret → `None`.
- [ ] **Step 2: Run** → FAIL. **Step 3: Implement.** **Step 4: Run** → PASS.
- [ ] **Step 5: Commit** `feat(oauth): provider protocol, PKCE, JWKS verification, test IdP`

### Task 12: Account API (profile, settings, onboarding, identities)

**Files:**
- Create: `backend/app/db/user_settings_db.py`
- Modify: `backend/app/api/routes/account.py`
- Test: `backend/tests/test_account_api.py`

**Interfaces:**
- Consumes: Task 1 `user_payload`, `game.hooks.on_onboarding_complete`; Task 2 helpers.
- Produces:
  - `get_settings(user_id) -> dict` (the defaults merged with the stored values); `patch_settings(user_id, changes: dict) -> dict`, validated by a pydantic `SettingsPatch` with `extra="forbid"`.
  - `get_onboarding(user_id) -> dict`, `put_onboarding(user_id, step, done, skipped, traveller_type) -> tuple[dict, bool]` (`bool` = newly completed and not skipped).
  - Routes `GET/PATCH /account`, `GET/PATCH /account/settings`, `PUT /account/onboarding`, `DELETE /account/identities/{provider}` per the contract (rate bucket `account` on the writes).
- [ ] **Step 1: Write failing tests**: the `GET /account` shape; PATCH `display_name` with a control character → `422 display_name_invalid`; a settings patch with an unknown key → 422 and with `timezone "Mars/Base"` → 422; `test_onboarding_done_awards_once` (patch `hooks.on_onboarding_complete` to count calls: done twice → called once; `skipped` → not called; `done` stays true); unlinking the only identity of a user without a password → `409 last_sign_in_method`.
- [ ] **Step 2: Run** → FAIL. **Step 3: Implement.** **Step 4: Run** → PASS.
- [ ] **Step 5: Commit** `feat(accounts): account profile, settings and onboarding API`

### Task 13: Avatars

**Files:**
- Create: `backend/app/services/avatar.py`
- Modify: `backend/app/api/routes/avatars.py`
- Test: `backend/tests/test_avatar.py`

**Interfaces:**
- Consumes: Task 2 `set_avatar`; Task 1 `public_url`.
- Produces:
  - `avatar_path(user_id) -> Path` (`$DATA_DIR/avatars/<id>.webp`).
  - `process_upload(data: bytes, content_type: str) -> bytes`. It raises `ApiError` 413/415/422. Accepted types are `image/jpeg|png|webp|gif`, sniffed with Pillow (the declared type alone isn't trusted). `Image.MAX_IMAGE_PIXELS = 40_000_000` and the bomb warning becomes an error. It applies `ImageOps.exif_transpose`, uses the first frame, converts to RGB(A), centre-crops square, resizes to 256 with LANCZOS, and saves WebP at quality 82 with no metadata.
  - `save_avatar(user_id, webp: bytes, source: str) -> str` (an atomic write via a temp file and `os.replace`; returns `avatar_url`); `remove_avatar(user_id)`.
  - `async import_provider_photo(user_id: str, url: str) -> bool`, a best effort. The host must be one of `lh3.googleusercontent.com`, `avatars.githubusercontent.com`, `platform-lookaside.fbsbx.com` or `graph.facebook.com` over https; the response is capped at 2 MB with a 5 s timeout and no redirects off-list. On success it stores the photo with `source "provider"`; on any failure it returns `False`.
  - Routes `PUT/DELETE /account/avatar` (bucket `account`) and `GET /avatars/{user_id}.webp` (`FileResponse` with the immutable cache header; a non-UUID id → 404).
- [ ] **Step 1: Write failing tests**: a 1000×600 JPEG → a 256×256 WebP with no EXIF; a PNG with an alpha channel keeps transparency; `text/plain` bytes labelled `image/png` → 415; 2.1 MB → 413; a decompression bomb (a 10k×10k PNG header) → 422; the `GET` serves the bytes with the cache header; `import_provider_photo` refuses `https://evil.example/x.png` and an `http://` URL.
- [ ] **Step 2: Run** → FAIL. **Step 3: Implement.** **Step 4: Run** → PASS.
- [ ] **Step 5: Commit** `feat(accounts): avatar upload, resize to 256 px WebP, provider photo import`

### Task 14: AI gate + daily quotas

**Files:**
- Modify: `backend/app/core/ai_quota.py` (fill it in), `backend/app/core/rate_limit.py` (`require_ai_access`), `backend/app/agents/chat_agent.py` (`_full_plan_refusal`), `backend/app/api/routes/quota.py`, `backend/tests/conftest.py` (`AI_DAILY_QUOTA_ENABLED=false`, set the same way `RATE_LIMIT_ENABLED` is)
- Test: `backend/tests/test_ai_quota.py`

**Interfaces:**
- Consumes: Task 1 `ApiError`, settings; Task 2 `ai_usage_daily`.
- Produces:
  - `consume(bucket: str, user: dict | None, request: Request, now: datetime | None = None) -> None`. It raises the contract `429 ai_daily_quota`. The user key is `user:<id>`, or `ip:<host>` when anonymous. Admins, `limit == 0` and quotas disabled all skip the check. The increment is a single atomic upsert (`INSERT … ON CONFLICT DO UPDATE SET used = used + 1 WHERE used < ?`, then `changes()`).
  - `usage(user) -> dict` (the `/account/quota` shape).
  - `daily_quota(bucket)` calls `consume` through `asyncio.to_thread`.
  - `require_ai_access` adds: a signed-in user with `account_verified` false → `ApiError(403, "email_unverified", …)`.
  - `_full_plan_refusal` also consumes `search` from the daily quota (after the window check) and returns the quota text in-stream.
  - The bucket labels in `detail` are search → "searches", chat → "chat", compare → "comparisons", discover → "Surprise me", light_ai → "quick AI tools", import → "link imports".
- [ ] **Step 1: Write failing tests** (with quotas enabled in the test via monkeypatch): the 21st `search` of the day → 429 with `error_code`, `bucket` and a `Retry-After` equal to the seconds until UTC midnight under a frozen clock; the next UTC day → allowed; admin → never limited; an OAuth user with an unverified email → `403 email_unverified` on `/api/search`; an admin-created user (`signup_method admin`, unverified email) → allowed; `/account/quota` shape; a chat full plan over the quota → the in-stream message and no 429.
- [ ] **Step 2: Run** → FAIL. **Step 3: Implement.** **Step 4: Run** the backend suite → PASS.
- [ ] **Step 5: Commit** `feat(accounts): verified-only AI and per-user daily quotas`

### Task 15: Sign-up page + login page links (namespace `signup`)

**Files:**
- Create: `frontend/src/utils/passwordStrength.js` (+ `.test.js`), `frontend/src/components/auth/PasswordStrengthMeter.jsx`, `frontend/src/i18n/locales/<lang>/signup.json`
- Modify: `frontend/src/pages/SignupPage.jsx`, `frontend/src/pages/LoginPage.jsx`
- Test: `frontend/src/pages/SignupPage.test.jsx`, `frontend/src/pages/LoginPage.test.jsx` (extend)

**Interfaces:**
- Consumes: Task 5 `signup`, `useClientConfig`, `errorText`, `SocialSignInButtons mode="signup"`.
- Produces:
  - `passwordStrength(pw, {username, email}) -> {score: 0..4, hints: string[]}` (hint keys under `signup:strength.*`). The heuristic covers length, character classes, repeats/sequences and an embedded username. It adds no dependency.
  - `SignupPage`: the social buttons, then "or", then username (lower-cased as typed, with an inline rule hint), email, password + meter + show toggle, optional display name, and an invite code field only when `config.auth.signup_mode === 'invite'`. Field-level errors come from `error_code`. Success navigates to `/check-email?email=<email>`. It emits `auth_start` / `auth_result` (`method password, mode signup`) and `signup_step`.
  - `LoginPage`: "Create account" (only when `signupAvailable`) and "Forgot password?" (only when `resetAvailable`) links; the label becomes "Username or email" (`signup:login.identifier`); `403 account_pending` shows the `email_hint` and a "Resend confirmation email" button.
- [ ] **Step 1: Write failing tests**: the score for `"aaaaaaaaaa"` < 2 and for `"correct horse battery"` ≥ 3; submit → `signup` called with `client 'web'`; `409 username_taken` shows under the username field; the invite field is hidden in open mode; LoginPage hides "Create account" when config has no `auth`; `account_pending` shows resend; the existing LoginPage tests pass.
- [ ] **Step 2: Run** → FAIL. **Step 3: Implement**, in both themes; translate `signup` into all 7 languages. **Step 4: Run** `npm test` + eslint → PASS.
- [ ] **Step 5: Commit** `feat(accounts): sign-up page and login links`

### Task 16: Check-email + verify pages (namespace `verify`)

**Files:**
- Create: `frontend/src/i18n/locales/<lang>/verify.json`
- Modify: `frontend/src/pages/CheckEmailPage.jsx`, `frontend/src/pages/VerifyEmailPage.jsx`
- Test: `frontend/src/pages/VerifyEmailPage.test.jsx`, `frontend/src/pages/CheckEmailPage.test.jsx`

**Interfaces:**
- Consumes: Task 5 `verifyEmail`, `resendVerification`, `applySession`, `announceGame`.
- Produces:
  - `CheckEmailPage`: "We sent a link to {{email}}. It works for 30 minutes." It has a resend button with a 60 s client cooldown and an "open your mail app" hint.
  - `VerifyEmailPage`: reads `token`, calls `history.replaceState` to drop it **before** the POST, and posts once (guarded against StrictMode's double effect). With a `session` → `applySession`, `announceGame(game)`, then navigate to `/`. With no session → "Email confirmed" and a link to `/account`. `token_used` → "already confirmed — sign in"; `token_expired` → an email field + resend; `token_invalid` → a link to sign-up. It emits `email_verify`.
- [ ] **Step 1: Write failing tests**: the token is removed from the URL before `verifyEmail` resolves; StrictMode → one call; **renders already-confirmed on token_used**; expired shows resend; a session result calls `applySession` and `announceGame`.
- [ ] **Step 2: Run** → FAIL. **Step 3: Implement**; translate into all 7 languages. **Step 4: Run** → PASS.
- [ ] **Step 5: Commit** `feat(accounts): check-email and verify-email pages`

### Task 17: Forgot + reset password pages (namespace `recovery`)

**Files:**
- Create: `frontend/src/i18n/locales/<lang>/recovery.json`
- Modify: `frontend/src/pages/ForgotPasswordPage.jsx`, `frontend/src/pages/ResetPasswordPage.jsx`
- Test: `frontend/src/pages/ResetPasswordPage.test.jsx`, `frontend/src/pages/ForgotPasswordPage.test.jsx`

**Interfaces:**
- Consumes: Task 5 `requestPasswordReset`, `confirmPasswordReset`, `applySession`; Task 15 `PasswordStrengthMeter`.
- Produces: Forgot shows the same "If an account uses that email, a link is on its way" text whatever the result (except 429/503). Reset strips the token with `replaceState`, has new password + confirm + meter, and on success calls `applySession` → `/` with a toast "Password changed — other devices were signed out". It emits `password_reset`.
- [ ] **Step 1: Write failing tests**: the success text is identical for 202 whether or not the account exists; mismatched confirm blocks submit; `password_common` shows under the field; the token is stripped.
- [ ] **Step 2: Run** → FAIL. **Step 3: Implement**; translate. **Step 4: Run** → PASS.
- [ ] **Step 5: Commit** `feat(accounts): forgot and reset password pages`

### Task 18: OAuth callback + choose-username pages (namespace `oauth`)

**Files:**
- Create: `frontend/src/i18n/locales/<lang>/oauth.json`
- Modify: `frontend/src/pages/OAuthCallbackPage.jsx`, `frontend/src/pages/ChooseUsernamePage.jsx`, `frontend/src/components/auth/SocialSignInButtons.jsx` (append `?client=web&return_to=<returnPathFrom(location)>` to `start_url` before `safeStart`; emit `auth_start`; emit `auth_result{result:'coming_soon'}` when the note shows)
- Test: `frontend/src/pages/OAuthCallbackPage.test.jsx`, `frontend/src/pages/ChooseUsernamePage.test.jsx`, `SocialSignInButtons.test.jsx` (extend)

**Interfaces:**
- Consumes: Task 5 `exchangeOAuthCode`, `completeOAuthSignup`, `applySession`, `announceGame`.
- Produces:
  - `OAuthCallbackPage`: `?error=` → navigate to `/login` with a translated note for each callback error code. `?code=` → `replaceState`, then exchange. `signed_in` → `applySession` → `return_to` (re-validated with `returnPathFrom`). `needs_username` → navigate to `/auth/username` with the result in router `state` (never in the URL). `linked` → `/account` with a toast.
  - `ChooseUsernamePage`: the prefilled `suggested_username`, the display name, and an invite field when `invite_required`. Submit → `completeOAuthSignup` → `applySession`. A missing router state (a reload) → back to `/login` with "Please start again".
- [ ] **Step 1: Write failing tests**: `?error=email_in_use_unverified` shows the "sign in with your password, then connect" note; the code is stripped before exchange; `needs_username` never puts `signup_token` in `location.search`; `return_to=//evil.com` → `/`; the SocialSignInButtons start URL has `client=web`, and `safeStart` still refuses a foreign origin.
- [ ] **Step 2: Run** → FAIL. **Step 3: Implement**; translate. **Step 4: Run** → PASS.
- [ ] **Step 5: Commit** `feat(accounts): OAuth callback and username pages`

### Task 19: Account page profile + avatar menu (namespace `profile`)

**Files:**
- Create: `frontend/src/components/account/Avatar.jsx` (+ `.test.jsx`), `frontend/src/utils/initials.js` (+ `.test.js`), `frontend/src/i18n/locales/<lang>/profile.json`
- Modify: `frontend/src/pages/AccountPage.jsx`, `frontend/src/components/account/ProfileSection.jsx`, `frontend/src/components/account/AccountMenu.jsx`

**Interfaces:**
- Consumes: Task 5 `getAccount`, `updateProfile`, `uploadAvatar`, `removeAvatar`, `refreshUser`.
- Produces:
  - `initials(displayName, username) -> string` (up to 2 graphemes; works for Devanagari, Bengali and CJK through `Intl.Segmenter` with a fallback); `avatarHue(username) -> 0..359` (a stable hash).
  - `<Avatar user size />`: the image with `onError` → initials.
  - `AccountPage`: the heading and the sections in the order Profile, Settings, Security, Quota, Game, Data, each wrapped in an error boundary. It loads `getAccount` once and passes `{account, reload}` to the sections. A 404 shows only Profile from `/auth/me`.
  - `ProfileSection`: the avatar with Change/Remove (client-side check ≤ 2 MB and the image type before upload), inline display-name editing, read-only `@username` and the email with a verified/unverified pill.
  - `AccountMenu` (NavBar): the avatar button → a menu with Account, Preferences and Sign out.
  - It emits `account_action`.
- [ ] **Step 1: Write failing tests**: `initials('জন দো','x') === 'জদ'`, `initials(null,'jane_doe') === 'J'`; a broken image falls back to initials; a 3 MB file is rejected without a request; saving a name calls `updateProfile` then `refreshUser`; the menu shows Account.
- [ ] **Step 2: Run** → FAIL. **Step 3: Implement**; translate. **Step 4: Run** → PASS.
- [ ] **Step 5: Commit** `feat(accounts): account page, profile and avatar`

### Task 20: Settings section + server sync (namespace `accountSettings`)

**Files:**
- Create: `frontend/src/i18n/locales/<lang>/accountSettings.json`
- Modify: `frontend/src/components/account/SettingsSection.jsx`, `frontend/src/components/account/SettingsSync.jsx`
- Test: `frontend/src/components/account/SettingsSync.test.jsx`, `SettingsSection.test.jsx`

**Interfaces:**
- Consumes: Task 5 `getSettings`, `patchSettings`; the existing `useTheme`, `setLanguage`, `PrivacySwitch`, `ThemeToggle`, `LanguagePicker`.
- Produces:
  - `SettingsSync` (renders nothing): on sign-in it GETs the settings and applies the non-null `language` and `theme` (the server wins at sign-in). Afterwards, theme and `languageChanged` changes from anywhere PATCH the server (debounced 1 s; failures are ignored). A 404 → inactive.
  - `SettingsSection`: language, theme, currency (ISO list from `Intl.supportedValuesOf('currency')` with a fallback list), units, timezone (default `Intl…timeZone`, with a "use this device's" button), "Hide Play & points" (`hide_game`), "Hide community" (`hide_community`), profile visibility, and the telemetry switch (the existing `PrivacySwitch`, mirrored into `telemetry_opt_out`).
  - `useAccountSettings() -> {settings, update}`, exported from `SettingsSync.jsx`. It reads a module-level store through `useSyncExternalStore`, so it needs no provider, and Task 24 can read `hide_game`.
- [ ] **Step 1: Write failing tests**: signing in with server `theme 'dark'` sets dark; changing the language via the NavBar picker PATCHes once after the debounce; a 404 → no further calls; toggling hide_game updates the context.
- [ ] **Step 2: Run** → FAIL. **Step 3: Implement**; translate. **Step 4: Run** → PASS.
- [ ] **Step 5: Commit** `feat(accounts): account settings synced to the server`

### Task 21: Security section (namespace `security`)

**Files:**
- Create: `frontend/src/i18n/locales/<lang>/security.json`
- Modify: `frontend/src/components/account/SecuritySection.jsx`
- Test: `frontend/src/components/account/SecuritySection.test.jsx`

**Interfaces:**
- Consumes: Task 5 `getLinkStartUrl`, `unlinkIdentity`, `logoutAll`, `requestEmailVerification`, `changePasswordV2`; `getAuthProviders`; `navigateTo` from `components/auth/navigate.js`.
- Produces: connected sign-in methods (the four providers in contract order: "Connected as {{email}}" / Connect / Disconnect; unconfigured providers show "coming soon"); "Verify email" when unverified; change or set password (reusing `PasswordStrengthMeter`); "Sign out everywhere" (confirm → `logoutAll` → local logout → `/login`). `last_sign_in_method` shows a hint to set a password first.
- [ ] **Step 1: Write failing tests**: Connect calls `getLinkStartUrl` and navigates only to a same-origin `/api/auth/` path; Disconnect with `409 last_sign_in_method` shows the hint; "Sign out everywhere" logs out locally.
- [ ] **Step 2: Run** → FAIL. **Step 3: Implement**; translate. **Step 4: Run** → PASS.
- [ ] **Step 5: Commit** `feat(accounts): connected sign-in methods and security settings`

### Task 22: Data section — export + delete (namespace `accountData`)

**Files:**
- Create: `frontend/src/i18n/locales/<lang>/accountData.json`
- Modify: `frontend/src/components/account/DataSection.jsx`
- Test: `frontend/src/components/account/DataSection.test.jsx`

**Interfaces:**
- Consumes: Task 5 `exportAccount`, `deleteAccount`, `logout`.
- Produces: "Download my data" (Blob → object URL → `<a download>`, revoked afterwards). "Delete account" opens a dialog that names what is deleted and asks for the password (`has_password`) or for typing the username. On success: local logout → `/login` with "Your account was deleted". It emits `account_action`.
- [ ] **Step 1: Write failing tests**: the export creates and revokes an object URL; delete stays disabled until the confirmation matches; `403 password_incorrect` shows inline; success logs out.
- [ ] **Step 2: Run** → FAIL. **Step 3: Implement**; translate. **Step 4: Run** → PASS.
- [ ] **Step 5: Commit** `feat(accounts): export my data and delete account`

### Task 23: Quota + verify UX (namespace `quota`)

**Files:**
- Create: `frontend/src/i18n/locales/<lang>/quota.json`
- Modify: `frontend/src/components/account/QuotaSection.jsx`, `frontend/src/components/account/VerifyBanner.jsx`
- Test: `QuotaSection.test.jsx`, `VerifyBanner.test.jsx`

**Interfaces:**
- Consumes: Task 5 `getQuota`, `requestEmailVerification`, `accountVerified`.
- Produces: `QuotaSection` shows a "used / limit" bar per bucket and "Resets at {{time}}" (local time through `fmtDate`); unlimited shows "No daily limit"; a 404 hides it. `VerifyBanner` is a slim dismissible-for-the-session banner shown when `accountVerified === false`: "Confirm your email to use the AI planner", with a "Send link" button. It emits `quota_block{reason:'unverified'}` once per session when shown. The existing `responseErrorMessage` already shows the server `detail` for AI 403/429, so search and chat need no change.
- [ ] **Step 1: Write failing tests**: the bars render from a mocked quota; the banner is hidden for verified users and with the old backend (no `account_verified` field); Send link calls the API once.
- [ ] **Step 2: Run** → FAIL. **Step 3: Implement**; translate. **Step 4: Run** → PASS.
- [ ] **Step 5: Commit** `feat(accounts): quota meter and verify-email banner`

### Task 24: Game UI (namespace `game`)

**Files:**
- Create: `frontend/src/i18n/locales/<lang>/game.json` (`levels.<n>`, `badges.<id>.name|desc`, `rules.<id>`, UI copy)
- Modify: `frontend/src/components/game/GameSection.jsx`, `GameNavChip.jsx`, `GameCelebration.jsx`
- Test: `frontend/src/components/game/game.test.jsx`

**Interfaces:**
- Consumes: Task 5 `getGameMe`, `getGameCatalog`, `onGameAnnounce`; Task 20 `useAccountSettings().settings.hide_game`.
- Produces:
  - `GameNavChip`: "Lv {{level}}" and a progress ring to the next level; hidden when `hide_game`, signed out or on a 404.
  - `GameSection`: XP, level, a progress bar, a badge grid (earned in colour; unearned greyed with `progress/target`) and the recent awards.
  - `GameCelebration`: subscribes to `onGameAnnounce`. For each award it shows a toast "+{{points}} XP — {{rule}}". For a badge it shows a card with a short confetti burst (CSS only; none under `prefers-reduced-motion`). For a level-up it shows "Level {{to}}!". It auto-dismisses after 4 s, is announced through `aria-live`, never blocks input, and is suppressed when `hide_game` is on. It emits `game_award`, `badge_earned` and `level_up`.
- [ ] **Step 1: Write failing tests**: announcing a delta with a badge shows the badge name from the catalogue; reduced motion → no element with the confetti class; `hide_game` → nothing rendered; the chip hides on a 404.
- [ ] **Step 2: Run** → FAIL. **Step 3: Implement**, in both themes; translate. **Step 4: Run** → PASS.
- [ ] **Step 5: Commit** `feat(game): level chip, badges and celebration toasts`

### Task 25: Onboarding-complete hook (web)

**Files:**
- Modify: `frontend/src/components/OnboardingTour.jsx` (the last step's Next calls `onClose({ done: true })`; Skip/Escape call `onClose({ done: false })`), `frontend/src/hooks/useFirstRunTour.js` (`close(result)`; on `done` → `putOnboarding(token, {step: stepsCount, done: true})` → `announceGame(game)`, fire-and-forget; a 404 is ignored)
- Test: `frontend/src/hooks/useFirstRunTour.test.jsx`, `OnboardingTour.test.jsx` (extend)

**Interfaces:**
- Consumes: Task 5 `putOnboarding`, `announceGame`.
- Produces: `useFirstRunTour({username, visible, eligible, delayMs, token, stepsCount})`. The new args are optional, so existing callers keep working. Phase 2's shared onboarding replaces this call site.
- [ ] **Step 1: Write failing tests**: finishing the tour calls `putOnboarding` once with `done: true`; skipping doesn't call it; a rejected call is swallowed.
- [ ] **Step 2: Run** → FAIL. **Step 3: Implement.** **Step 4: Run** → PASS.
- [ ] **Step 5: Commit** `feat(game): award starter XP when onboarding completes`

### Task 26: Admin invites tab (namespace `adminInvites`)

**Files:**
- Create: `frontend/src/components/admin/InvitesPanel.jsx` (+ `.test.jsx`), `frontend/src/services/adminInvitesApi.js`, `frontend/src/i18n/locales/<lang>/adminInvites.json`
- Modify: `frontend/src/pages/AdminPage.jsx` (an "Invites" tab, shown only when `GET /admin/invites` doesn't 404)

**Interfaces:**
- Consumes: the contract admin invite endpoints.
- Produces: a create form (max uses, expiry days, note) → the code shown once with Copy; a list with uses, expiry and Revoke.
- [ ] **Step 1: Write failing tests**: a created code is shown once and absent after a reload; the tab is hidden on a 404.
- [ ] **Step 2: Run** → FAIL. **Step 3: Implement**; translate. **Step 4: Run** → PASS.
- [ ] **Step 5: Commit** `feat(admin): invite codes tab`

## Wave 2 — flows that join the modules

### Task 27: Sign-up, verify and reset API (+ client config auth block)

**Files:**
- Create: `backend/app/db/account_tokens_db.py`
- Modify: `backend/app/api/routes/signup.py`, `backend/app/api/routes/client_config.py`
- Test: `backend/tests/test_signup_flow.py`, `backend/tests/test_client_config.py` (extend)

**Interfaces:**
- Consumes: Task 2 helpers; Task 3 `password_problem`; Task 7 `issue_session`, `revoke_all`, `bump_token_version`; Task 8 `send_account_email`, `email_delivery_available`; Task 9 `check_invite`, `consume_invite`; Task 1 hooks.
- Produces:
  - `issue_token(user_id, purpose, email) -> str` (invalidates earlier unused tokens of that purpose for that user); `redeem_token(token, purpose, now) -> dict | TokenError` (`invalid|expired|used`).
  - The contract routes `/auth/signup`, `/auth/verify-email`, `/auth/verify-email/resend`, `/auth/password-reset/request`, `/auth/password-reset/confirm` and `/account/email/verify`. Buckets: `signup` on signup; `auth_email` on resend and reset-request; and the per-address limit `email_address`, keyed `sha256(email)`, on every send. The address limit is silent: it still answers 202 without sending, so it reveals nothing.
  - Verify: a pending account → `activate_user`, `issue_session`, `hooks.on_email_verified`. An active account → `mark_email_verified` (or `409 email_changed`) and `hooks.on_email_verified`. The invite is consumed at signup, before the insert. When the insert loses a race, the use stays consumed (accepted; logged).
  - `/config` gains the `auth` block and `features.accounts`/`features.game`; `public_base_url` comes from `core.urls.public_base_url()`.
- [ ] **Step 1: Write failing tests** (capture sends by monkeypatching `send_account_email`): the happy path signup → 202 → captured link → verify → session + `game.awards[0].rule == "email_verified"` (with the real Task 10 engine); `test_verify_twice_is_token_used`; expired (clock + 31 min) → 410; resend invalidates the first token; `test_signup_existing_email_is_enumeration_safe` (an identical 202, an `already_registered` send, no new row); `test_signup_race_one_wins` (two threads, same username → one 202 and one 409); invite mode without a code → 403 `invite_required`; SMTP unset and no dev links → 503 `email_unavailable` and `/config.auth.signup_available false`; a reset revokes the other sessions (an old access token → 401 `session_revoked`); a reset on a pending account activates it; the reset request for an unknown email → 202 and no send.
- [ ] **Step 2: Run** → FAIL. **Step 3: Implement.** **Step 4: Run** the backend suite → PASS.
- [ ] **Step 5: Commit** `feat(accounts): native sign-up, email verification and password reset`

### Tasks 28–31: Provider adapters (one file each, parallel)

Each task creates `backend/app/services/oauth/<id>.py` exposing `PROVIDER: OAuthProvider`, and `backend/tests/test_oauth_<id>.py`. Every test runs against `FakeIdP` / `MockTransport` only. Each test file covers: `configured()` false when any credential is empty; `authorize_url` has exactly the listed parameters; `exchange` builds the right token request (asserted from the transport) and maps the profile; provider error responses → `OAuthError("provider_error")`. Commit `feat(oauth): <Name> provider`.

| Task | Provider | Configured when | Authorize | Token / profile | Profile mapping |
|---|---|---|---|---|---|
| 28 | `google` | `google_client_id` + `google_client_secret` | `https://accounts.google.com/o/oauth2/v2/auth`; `response_type=code`, `scope=openid email profile`, `state`, `nonce`, `code_challenge`, `code_challenge_method=S256`, `prompt=select_account` | POST `https://oauth2.googleapis.com/token` (form, with `code_verifier`); verify the `id_token` with JWKS `https://www.googleapis.com/oauth2/v3/certs`, iss `{https://accounts.google.com, accounts.google.com}`, aud `google_client_id`, `nonce` | `sub`; `email`; `email_verified` (bool or `"true"`); trusted = verified; `name`; `picture`. Native: `verify_id_token` with aud ∈ `google_native_client_ids`; `native_configured()` when the list is non-empty |
| 29 | `github` | `github_client_id` + `github_client_secret` | `https://github.com/login/oauth/authorize`; `scope=read:user user:email`, `state`, `code_challenge`, `code_challenge_method=S256`, `allow_signup=true` | POST `https://github.com/login/oauth/access_token` with `Accept: application/json` and `code_verifier`; GET `https://api.github.com/user` and `/user/emails` with `Accept: application/vnd.github+json`, `X-GitHub-Api-Version: 2022-11-28` | subject `str(id)`; email = the primary && verified one, else the first verified one, else `None`; verified/trusted accordingly; `name or login`; `avatar_url`. A test covers "only an unverified email → `email None`" |
| 30 | `facebook` | `facebook_app_id` + `facebook_app_secret` | `https://www.facebook.com/{facebook_graph_version}/dialog/oauth`; `scope=public_profile,email`, `state`, `code_challenge`, `code_challenge_method=S256`, `response_type=code` | GET `https://graph.facebook.com/{ver}/oauth/access_token` (`client_id`, `client_secret`, `redirect_uri`, `code`, `code_verifier`); GET `/{ver}/me?fields=id,name,email,picture.width(256).height(256)` with `appsecret_proof = hex(HMAC-SHA256(app_secret, access_token))` | `id`; `email`; `email_verified = email is not None`; `email_trusted = settings.facebook_email_trusted`; `name`; `picture.data.url` (only when `is_silhouette` is false). A test covers "trusted false by default" |
| 31 | `apple` | `apple_services_id` + `apple_team_id` + `apple_key_id` + `apple_private_key` | `https://appleid.apple.com/auth/authorize`; `response_type=code`, `response_mode=form_post`, `scope=name email`, `state`, `nonce` (no PKCE: `uses_pkce False`); `callback_methods ("POST",)` | POST `https://appleid.apple.com/auth/token`; `client_secret` = an ES256 JWT `{iss: team_id, iat, exp: iat+300, aud: "https://appleid.apple.com", sub: client_id}` with header `kid`. The private key accepts a PEM with real or `\n`-escaped newlines. Verify the `id_token` with JWKS `https://appleid.apple.com/auth/keys`, iss `https://appleid.apple.com`, aud = client_id, `nonce` | `sub`; `email`; `email_verified` (`"true"`/true); trusted = verified; the name comes from the first-time `user` form field JSON (`name.firstName` + `lastName`), else `None`; no picture. Return the `refresh_token` as the secret. `revoke(secret)` POSTs `https://appleid.apple.com/auth/revoke` (`token`, `token_type_hint=refresh_token`). Native: aud ∈ `apple_native_client_ids`; `nonce_is_hash=True` (claim = hex SHA-256 of the raw nonce); an `authorization_code` is exchanged with `client_id` = the token's aud for a refresh token. Tests: the client-secret JWT verifies with the public key; the escaped-newline PEM works |

### Task 32: OAuth flow routes

**Files:**
- Create: `backend/app/db/oauth_db.py`, `backend/app/services/oauth/flow.py`
- Modify: `backend/app/api/routes/oauth.py` (it also serves `GET /auth/providers`, which no backend route serves today; `auth.py` stays Task 7's)
- Test: `backend/tests/test_oauth_flow.py`

**Interfaces:**
- Consumes: Task 11 registry, `pkce_*`, `secrets_box`, `OAuthError`; Task 7 `issue_session`; Task 9 `check_invite`/`consume_invite`; Task 13 `import_provider_photo`; Task 8 `send_account_email` (verify mail for untrusted-email accounts); Task 2 helpers; Task 1 hooks.
- Produces:
  - `oauth_db.put_ticket(kind, *, ttl_s, provider=None, user_id=None, data=None, binding=None, client_challenge=None) -> str` (plaintext); `take_ticket(kind, token, now) -> dict | None` (atomic `UPDATE … SET used_at` where unused and unexpired; `None` otherwise).
  - `flow.resolve_identity(profile: ProviderProfile, provider: str, *, link_user_id: str | None, secret: str | None) -> Result`, where `Result` is one of `SignedIn(user)`, `NeedsUsername(pending_data)`, `Linked(user)` or `Refused(code)`. Rules, in order:
    1. A known `(provider, subject)` → its user. An inactive user → `account_inactive`. Update `last_used_at`, the identity email and the secret.
    2. `link_user_id` set → attach (a subject owned by another user → `identity_in_use`).
    3. `email_verified and email_trusted` and an active user with that email and `email_verified=1` → attach and sign in.
    4. A `pending` user with that email → delete it (and its tokens), then continue.
    5. An active user with that email and `email_verified=0` → `email_in_use_unverified`.
    6. Otherwise → `NeedsUsername`.
  - On `complete`: create the user with `signup_method 'oauth'` and `password_hash '!'`. When the email is verified and trusted → `email_verified=1`, `verified_at=now` and `hooks.on_email_verified`. When the email is untrusted → `email_verified=0` and a verify email is sent. The identity row is inserted, `import_provider_photo` runs as a background task, and invite mode needs a valid `invite_code` (consumed).
  - The suggested username is the email local part or name, folded to `[a-z0-9_]`, trimmed to 20 and padded to ≥ 3, with `_2`, `_3`, … until available.
  - The routes per the contract. Buckets: `oauth` on all of them, except `/auth/providers`, which has none. The first `/auth/providers` call logs `oauth.configured providers=[…] redirect_uris=[…]` once (the `<base>/api/auth/oauth/<p>/callback` URIs the owner registers in each console).
- [ ] **Step 1: Write failing tests** with a fake provider through `registry.override`: `test_web_round_trip` (start → 302 with a state → callback → 302 `/auth/callback?code=` → exchange with the cookie → `signed_in` or `needs_username` → complete → session); `test_exchange_without_cookie_fails` (`400 code_invalid`); `test_mobile_requires_challenge_and_verifier` (no challenge → redirect `error=bad_request`; a wrong verifier → 400); `test_mobile_redirect_allowlist`; `test_state_single_use_and_10_min_expiry`; `test_pending_native_account_is_replaced_not_linked`; `test_untrusted_email_never_links`; `test_unverified_existing_email_is_refused`; `test_link_ticket_attaches_identity`; `test_identity_in_use`; `test_unconfigured_provider_redirects_with_provider_unavailable` (never a 5xx); `test_apple_form_post_callback` (POST callback with a `user` JSON name); `test_return_to_rejects_offsite` (`//evil.com` and `https://evil.com` → `/`); `test_providers_listing_order_and_flags`; invite mode → `needs_username.invite_required true`, and complete without a code → 403.
- [ ] **Step 2: Run** → FAIL. **Step 3: Implement.** **Step 4: Run** the backend suite → PASS.
- [ ] **Step 5: Commit** `feat(oauth): authorization-code flow with PKCE, linking and handoff codes`

### Task 33: Export + delete

**Files:**
- Create: `backend/app/services/account_data.py`
- Modify: `backend/app/api/routes/account_data.py`, `backend/app/db/telemetry_db.py` (add `delete_user_events(user_id: str) -> int`)
- Test: `backend/tests/test_account_data.py`

**Interfaces:**
- Consumes: every table (schema from Task 2 plus the existing ones); Task 11 `get_provider(...).revoke`, `secrets_box.open_`; Task 13 `remove_avatar`; its own `telemetry_db.delete_user_events`.
- Produces:
  - `USER_TABLES: dict[str, tuple[str, Literal["id","username"]]]`, mapping every main-DB table that holds a user's rows to (column, key), and `CHILD_TABLES: dict[str, str]`, mapping child tables to a `WHERE` clause over the parent (e.g. `fare_watch_history`: `"watch_id IN (SELECT id FROM fare_watches WHERE <col> = ?)"`).
  - `export_user(user) -> dict` (the contract keys; never `password_hash`, `token_hash`, `secret_enc`, device tokens (masked as in `/devices`) or refresh tokens).
  - `async delete_user(user) -> None`: revokes Apple (best effort, logged), deletes the child tables, `USER_TABLES` and the telemetry rows, removes the avatar, nulls `invite_codes.created_by`, then `delete_user_row`, all inside one transaction except the network and file steps.
  - Routes `GET /account/export` and `DELETE /account` (bucket `account`; `409 last_admin` when `count_active_admins() == 1` and the user is an admin).
- [ ] **Step 1: Write failing tests**: `test_every_user_table_is_covered` (introspect `sqlite_master`: every table with a `username`, `user_id` or `created_by` column is in `USER_TABLES` or the explicit `KEEP_NULLED` set, and every table with a `watch_id` column is in `CHILD_TABLES`); after delete, a full-DB scan finds no row with the user's id or username; the export round trip contains a saved plan and has no secret keys; a wrong password → 403; the last admin → 409; an Apple identity → `revoke` called with the decrypted secret.
- [ ] **Step 2: Run** → FAIL. **Step 3: Implement.** **Step 4: Run** → PASS.
- [ ] **Step 5: Commit** `feat(accounts): export my data and in-app account deletion`

### Task 34: Deploy configuration

**Files:**
- Modify: `deploy/gcp/app.env.example` (append `GOOGLE_CLIENT_SECRET,GITHUB_CLIENT_SECRET,FACEBOOK_APP_SECRET,APPLE_PRIVATE_KEY` to `SECRET_MANAGER_SECRETS`; add commented placeholders for the non-secret IDs, `SIGNUP_MODE=open`, `PUBLIC_BASE_URL=` and the quota settings), `infrastructure/gcp/bootstrap.sh` (`SECRETS+=(google-client-secret github-client-secret facebook-app-secret apple-private-key)`), `infrastructure/gcp/tests/test_bootstrap.py` (extend)
- [ ] **Step 1: Write the failing test**: the bootstrap dry-run output creates the four new empty secrets; `app.env.example` names only secrets that bootstrap creates.
- [ ] **Step 2: Run** `python3 -m pytest -q infrastructure/gcp/tests` → FAIL. **Step 3: Implement.** **Step 4: Run** → PASS, and run shellcheck (v0.9 docker) on `bootstrap.sh`.
- [ ] **Step 5: Commit** `chore(deploy): OAuth secrets and account settings in the VM kit`

## Wave 3 — integration, docs, review

### Task 35: Per-provider end-to-end test

**Files:**
- Create: `backend/tests/test_oauth_e2e.py`
- [ ] **Step 1:** For each of the four real adapters (not overrides), set fake credentials, route `http_client()` through a `FakeIdP` transport that mimics that provider's token, profile and JWKS endpoints, and drive `GET start → provider redirect (assert the URL and params) → callback (GET, or POST for Apple) → exchange → complete → /api/auth/me`. This shows that "set the env vars and it works" holds without real credentials. Also cover Apple and Google `id-token` native sign-in.
- [ ] **Step 2: Run** → PASS (fix the adapters if not). **Step 3: Commit** `test(oauth): end-to-end flows for every provider against fake IdPs`

### Task 36: Docs + CLAUDE.md sync

**Files:**
- Modify: `CLAUDE.md` (tables list and count, new routers, auth paragraph: self-registration, OAuth, sessions, quotas, game; new settings), `docs/Configuration.md` (every Task 1 setting), `docs/API-Reference.md` (link to `Accounts-API.md`), `docs/Deployment-GCP.md` (new section "Sign-in providers and email": the redirect URI `<PUBLIC_BASE_URL>/api/auth/oauth/<p>/callback` per provider console, Apple Services ID + key steps, SMTP, `SIGNUP_MODE`; and "Moving to a custom domain": DNS, `SITE_HOST`, `PUBLIC_BASE_URL`/`APP_BASE_URL`, provider consoles, AASA/assetlinks (Phase 7/8), old sslip.io redirects; the known Google + sslip.io limitation), `docs/Privacy.md` (account data, retention, export, deletion, avatars on disk and not in the GCS backup), `docs/Feature-Parity.md` (account rows: Web ✅, Android ⏳ 8, iOS ⏳ 7), `docs/Accounts-API.md` (any contract notes from waves 1–2), `docs/superpowers/specs/2026-11-10-voyager-reimagined-design.md` (§4: the AI gate counts admin-created accounts as verified; Facebook email untrusted by default)
- [ ] **Step 1:** Write. **Step 2:** `mkdocs build --strict` → PASS. **Step 3: Commit** `docs: accounts, OAuth, quotas and game engine`

### Task 37: Translation review

**Files:** `frontend/src/i18n/locales/{es,de,fr,hi,zh,bn}/{errors,signup,verify,recovery,oauth,profile,accountSettings,security,accountData,quota,game,adminInvites}.json`, `backend/app/i18n/emails/*.json`
- [ ] **Step 1:** One fresh reviewer per language reads `en` alongside, fixes meaning, register (informal es/de, `vous` fr) and length (shorten German or Bengali buttons longer than 1.6× `en`), and checks that the emails read naturally.
- [ ] **Step 2:** `npm test` and the backend email parity test → PASS. **Step 3: Commit** `fix(i18n): phase 1 translation review`

### Task 38: Browser end-to-end + review passes

- [ ] **Step 1:** With the `verify` skill, run locally with SMTP unset and `EMAIL_LOG_LINKS=true`: sign up → read the link from the log → verify (signed in, +50 XP toast, `verified` badge) → finish the tour (+100 XP, level 2) → account page: avatar upload, rename, settings sync (theme dark persists after sign-out and sign-in), export, then delete → login refuses. Forgot → reset → the old tab gets `session_revoked`. OAuth is covered by Task 35, since no real credentials exist yet; in the browser, check that every provider shows "coming soon". Take screenshots in light, dark and `de`/`bn` at 375 px and 1280 px.
- [ ] **Step 2:** Mixed versions: build the SPA from `origin/main` against the new backend (login, search, alerts work), and the new SPA against the `origin/main` backend (no Create account, no Account sections, no console errors).
- [ ] **Step 3:** Three review passes on the combined diff: spec compliance (this plan + spec §4/§5a), correctness/security (`/code-review high`, focused on the Review Focus list and the token handling), and UX/visual (screenshots). Fix, then re-run the suites.
- [ ] **Step 4:** Add to `docs/superpowers/plans/2026-11-11-phase0-followups.md` (or a Phase 1 follow-ups file) any deferred minors.

## Execution waves

Each wave starts when the previous one is merged to main. Inside a wave, every task runs in its own worktree in parallel, because the tasks own disjoint files.

| Wave | Tasks (parallel) | Count | Gate |
|---|---|---|---|
| **0 — seams** | 1 backend seams · 2 schema + users_db · 3 password policy · 4 telemetry events · 5 frontend seams · 6 contract doc | 6 | Task 1's last step rebases on Task 2. When wave 0 merges, the contract is frozen and the iOS/Android teams start |
| **1 — modules** | backend: 7 sessions · 8 emails · 9 invites · 10 game engine · 11 OAuth core · 12 account API · 13 avatars · 14 AI gate + quotas; frontend: 15 sign-up · 16 verify · 17 recovery · 18 OAuth pages · 19 profile · 20 settings · 21 security · 22 data · 23 quota UX · 24 game UI · 25 onboarding hook · 26 admin invites | 20 | Frontend tasks need only Task 5 and the contract (API mocked); backend tasks need only Tasks 1–3 |
| **2 — flows** | 27 sign-up/verify/reset API · 28 Google · 29 GitHub · 30 Facebook · 31 Apple · 32 OAuth flow · 33 export + delete · 34 deploy config | 8 | 27 needs 7, 8, 9, 10; 28–31 need 11; 32 needs 7, 9, 11, 13; 33 needs 11, 13 |
| **3 — integrate** | 35 provider E2E · 36 docs · 37 translation review (one agent per language) · 38 browser E2E + three review passes | 4 (+6 reviewers) | 35 needs 28–32 |

Merge cadence: one PR per wave (as in Phase 0), or a PR per task when CI time allows. Each PR is green and deployable on its own: every wave leaves the features hidden or harmless until the next lands. Wave 1 UI against the wave-0 backend sees 404s and hides itself, and wave-1 backend routes exist with no UI pointing at them.

## Deferred (later phases)

Seasonal challenges, leaderboards and more badges come in Phase 5. Streak hooks (daily quiz, trip check-ins) come in Phases 2 and 5. Notification categories and quiet hours in Settings come in Phase 6. The traveller-type badge comes with Phase 2's shared onboarding. AASA/assetlinks for universal links come in Phases 7 and 8. A refresh-token device list ("signed-in devices") can come later.
