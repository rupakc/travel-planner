# Accounts API

> Frozen 2026-11-11. Changes are additive only; each change is listed in a Changelog section at the bottom.

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
 "hide_game": false, "hide_community": false, "profile_visibility": "public", "telemetry_opt_out": false,
 "bucket_list_goal": null}
```
`language` is one of the 7 codes or `null`. `theme` is `system|light|dark`. `currency` matches `^[A-Z]{3}$`. `units` is `metric|imperial`. `timezone` is an IANA name that `zoneinfo` accepts, or `null`. `profile_visibility` is `public|followers|private`.

**Additive (Phase 2).** `Settings` gains `bucket_list_goal: int 1..250 | null` (default `null`; see `Trips-API.md`). The Phase 2 journey rules, badges and the `trip_checkin` streak appear in `GET /game/catalog`; `PUT /account/onboarding` with `traveller_type` awards `traveller_type` once and merges that into `game`.

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
| `GET /auth/sessions` (additive, 2026-11-12) | yes | optional header `X-Refresh-Token: rt_…` (never logged) | `200 {"sessions": [{"id", "client", "device_name", "created_at", "last_used_at", "current"}]}`: the caller's live refresh-token families (one per mobile sign-in; web logins have none), most recently used first. `id` is the family id and stays the same across refreshes. `current` is true for the family the `X-Refresh-Token` belongs to. Revoked and expired families are not listed. Bucket `account` | `401`, `429` |
| `DELETE /auth/sessions/{id}` (additive, 2026-11-12) | yes | — | `204`, revokes that whole family (its next refresh answers `401 refresh_invalid`) | `404 session_not_found` (unknown, already revoked, or another user's), `429` |
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
| `GET /account/export` | yes | — | `200 application/json` with `Content-Disposition: attachment; filename="voyager-export-<username>-<YYYY-MM-DD>.json"`: `{"format": "voyager-export", "version": 1, "exported_at", "account", "identities", "settings", "onboarding", "preferences", "plans", "recent_searches", "taste", "feedback", "fare_watches", "price_watches", "notifications", "devices", "notification_settings", "notify_log", "game"}` (`notify_log`, additive: the user's notification delivery log) | `429` |
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

## Mobile flow

All examples use `client: "ios"`; Android is identical with `"android"`. Mobile sessions carry a `refresh_token` and a 3600 s access token. Store the refresh token in the Keychain / Android Keystore-backed storage, never in plain preferences.

### 1. Native sign-up and email verification

```http
POST /api/auth/signup
{"username": "jane_doe", "email": "jane@example.com", "password": "correct horse battery", "locale": "en", "client": "ios"}

202 {"status": "verification_sent", "email": "jane@example.com", "expires_in": 1800}
```

The account stays pending until the email is confirmed. The email links to the universal link / app link `<base>/verify?token=…`. Register `/verify` (and `/reset-password`) as associated domains so the app opens instead of the browser. The app reads `token` from the URL and calls:

```http
POST /api/auth/verify-email
{"token": "<token from the link>", "client": "ios", "device_name": "Jane's iPhone"}

200 {"status": "verified", "session": {"access_token": "<jwt>", "token_type": "bearer", "expires_in": 3600,
     "refresh_token": "rt_…", "user": {…}}, "game": {"xp": 50, "awards": […], "badges": […], "level_up": null}}
```

`session` is `null` when the token only confirmed an email on an already active account; show a confirmation and keep the current session. On `410 token_expired` offer `POST /auth/verify-email/resend`. Until verified, login answers `403 account_pending` (with `email_hint`) and the AI routes answer `403 email_unverified`.

### 2. Login

```http
POST /api/auth/login
{"username": "jane_doe", "password": "correct horse battery", "client": "ios", "device_name": "Jane's iPhone"}

200 {"access_token": "<jwt>", "token_type": "bearer", "expires_in": 3600, "refresh_token": "rt_…", "user": {…}}
```

### 3. OAuth with the system browser

Use `ASWebAuthenticationSession` on iOS and Custom Tabs on Android.

1. Generate a random `verifier` (43 to 128 URL-safe characters, per RFC 7636) and keep it in memory. Compute `challenge = base64url(sha256(verifier))` without padding.
2. Open the system browser at:
   `<base>/api/auth/oauth/github/start?client=ios&challenge=<challenge>&redirect_uri=voyager%3A%2F%2Fauth%2Fcallback`
   `redirect_uri` must exactly match an allow-listed entry (default `voyager://auth/callback` or `<base>/auth/callback`).
3. The provider flow ends with a redirect to `voyager://auth/callback?code=<handoff>` (or `?error=<code>`, for example `cancelled`). The handoff code lasts 120 s and is single use.
4. Exchange it:

```http
POST /api/auth/oauth/exchange
{"code": "<handoff>", "verifier": "<verifier>", "device_name": "Jane's iPhone"}
```

Handle the three results:

- `{"status": "signed_in", "session": {…}, "game": {…}, "return_to": "/"}`: store the session.
- `{"status": "needs_username", "signup_token": "…", "suggested_username": "jane", …}`: ask for a username, then `POST /auth/oauth/complete` with `{"signup_token", "username", "client": "ios", "device_name"}` which returns `201 {"status": "signed_in", "session": {…}, "game": {…}}`.
- `{"status": "linked", …}`: returned only for linking, which is started from a signed-in session with a link ticket (the contract example uses `client=web`).

`400 code_invalid` means the code expired, was used, or the verifier does not match; restart from step 1.

For Apple and Google, native ID-token sign-in skips the browser when `GET /auth/providers` reports `"id_token": true`:

```http
POST /api/auth/oauth/apple/id-token
{"id_token": "<jwt>", "nonce": "<raw nonce>", "authorization_code": "<apple code>", "client": "ios", "device_name": "Jane's iPhone"}
```

The result is one of the same three shapes as the exchange.

### 4. Calling the API and refreshing (single flight)

Send `Authorization: Bearer <access_token>`. When a call answers `401` (expired access token) or `401 session_revoked`, refresh. Run at most one refresh at a time: the first request that needs a refresh starts it, and every other request that gets a 401 meanwhile waits for that same refresh to finish, then retries with the new access token.

```http
POST /api/auth/refresh
{"refresh_token": "rt_old"}

200 {"access_token": "<jwt>", "token_type": "bearer", "expires_in": 3600, "refresh_token": "rt_new"}
```

Refresh tokens rotate: persist `rt_new` immediately and discard `rt_old`. Failure handling:

- `401 refresh_stale`: the old token was already rotated at most 30 s ago (for example a second process, or a response lost in transit). The family is still valid. Re-read the newest stored refresh token and retry the refresh once with it. If that also fails, treat it as `refresh_invalid`.
- `401 refresh_invalid`: the token is unknown, expired, revoked, the user is inactive, or it was reused after the grace window (which revokes the family). Clear stored tokens and sign the user out.
- `429`: wait `Retry-After` seconds, then retry. Do not sign out.

On `401 session_revoked`, try one refresh; if the refresh fails, sign out.

### 5. Sign out

```http
POST /api/auth/logout
{"refresh_token": "rt_new"}

204
```

This revokes that refresh token's family. Clear local tokens regardless of the response. `POST /auth/logout-all` (authenticated) revokes every device.

## Contract notes

Clarifications of behaviour the frozen contract left implicit. None changes a request or response shape.

- **Off-site `return_to`.** On `GET /auth/oauth/<p>/start`, a `return_to` that is not a same-origin path (an absolute URL, a `//host` form, or anything not starting with a single `/`) is refused like any other bad start parameter: `302` to `<final>?error=bad_request`. It is never followed.
- **Apple native secret.** For Apple the server stores the refresh token it needs to revoke on account deletion as `"<client_id>|<refresh_token>"`, Fernet-encrypted (see Global constraints). This is internal storage: no request or response field changes.
- **Unverified or untrusted provider email.** A provider email that is unverified, or verified but not trusted (Facebook, unless `FACEBOOK_EMAIL_TRUSTED=true`), never deletes and never links to an existing account. If it matches an existing account that has no verified email (for example an admin-created one), the callback answers `email_in_use_unverified`. Only a pending native account is replaced, and only by a trusted, verified provider email.
- **Password reset goes only to a proven address.** `POST /auth/password-reset/request` sends a link only when the address is the account's verified email, or the account is pending (a reset then activates and verifies it, as above). For an active account's unverified email it sends nothing and answers the same `202`, so `POST /auth/password-reset/confirm` never marks an active account's unverified email verified.
- **Sign-up needs the operator's opt-in.** `signup_available` is true only when email delivery is available *and* the server sets `SIGNUP_ENABLED=true`; otherwise `POST /auth/signup` answers `503 email_unavailable`. OAuth sign-up is not gated by it.
- **An untrusted provider email is not the account's email until confirmed.** After an OAuth sign-up whose provider email is unverified or untrusted, `User.email` is `null` and `email_verified` false; the verify link goes to the provider address, and redeeming it sets `email` (and `email_verified: true`) unless another account holds that address by then (`409 email_changed`). `needs_username.email` still shows the provider address. While `email` is `null`, `POST /account/email/verify` re-sends the link to that pending address (`email` in the `202` is that address); it answers `422 no_email` only when there is no pending address.

## Changelog

- 2026-11-11 — v1 published
- 2026-11-11 — added the "Contract notes" section (clarifications only)
- 2026-11-12 — added `GET /auth/sessions` and `DELETE /auth/sessions/{id}` (additive; no existing endpoint changed)
