# Configuration

The backend is configured through environment variables, read by pydantic-settings in `backend/app/core/config.py`. Variable names are the upper-case field names. Every setting has a default, so the app always starts; the ones marked *needed* below must be set for it to be useful.

Settings are read from the process environment and from a `.env` file in the **working directory** (`env_file=".env"`, unknown keys ignored). For `start.sh` and a manual `uvicorn` run that is `backend/.env`. For Docker Compose, put the values in your shell or a root `.env`, which Compose uses for variable substitution (see [Setup and Installation](Setup-and-Installation.md)).

---

## Core

| Variable | Default | Meaning |
|---|---|---|
| `ANTHROPIC_API_KEY` | `""` | **Needed.** Used by every agent. Without it, every AI call fails. |
| `JWT_SECRET_KEY` | `""` | **Needed.** HS256 signing key for login tokens (24 h lifetime). Changing it logs everyone out. Generate one with `python3 -c "import secrets; print(secrets.token_hex(32))"`. |
| `CORS_ORIGINS` | `["http://localhost:5174","http://localhost:5173"]` | Allowed browser origins, as a JSON list. |
| `AGENTS_DIR` | `<repo>/.agents` | Directory of the agent definition files. A relative path that does not exist falls back to `<repo>/.agents`. |
| `AGENT_MAX_CONCURRENCY` | `6` | Global cap on concurrent Anthropic calls across all agents. |
| `CACHE_TTL_SECONDS` | `1800` | TTL of the in-memory result cache. |
| `CACHE_MAXSIZE` | `500` | Maximum entries in that cache. |

## Storage and backup

| Variable | Default | Meaning |
|---|---|---|
| `DATA_DIR` | `backend/data` | Directory of the single SQLite file `airports.db`, which holds every table (users, plans, preferences, place data and so on). Created automatically. |
| `BACKUP_BUCKET` | `""` | Google Cloud Storage bucket for SQLite backups. Empty disables backup and restore. When set, the database is restored at startup, uploaded every 60 s and uploaded once more on shutdown. Uses Application Default Credentials. |

## Live data (optional)

| Variable | Default | Meaning |
|---|---|---|
| `SERPAPI_KEY` | `""` | SerpAPI key for live Google Flights fares, the fare calendar and Google's price insights. Empty means flights are LLM estimates and `POST /api/flights/fare-calendar` returns 503. `GET /health` reports `serpapi_configured`. |
| `SERPER_KEY` | `""` | Serper.dev key for Places-to-See data (Google Places) and the second tier of activity and place link resolution. Empty means Places to See is LLM-only. |

Other web lookups (link enrichment for hotels and activities, the forex agent's rate searches, walking-tour city-page discovery, and identifying an unknown airport code) go through DuckDuckGo via the `ddgs` package and need no key.

## Accounts

| Variable | Default | Meaning |
|---|---|---|
| `ADMIN_USERNAME` | `admin` | Username of the seeded admin. |
| `ADMIN_PASSWORD` | `""` | Password for the seeded admin. Empty means no admin is created. Used only when that user does not exist yet; the seeded admin is not forced to change it. |
| `ADMIN_EMAIL` | `""` | Optional email for the seeded admin. |

There is no self-registration: the admin creates every other user from the Admin page.

## Rate limits

AI-calling endpoints are rate-limited per signed-in user, or per client IP for anonymous callers, in an in-process sliding window (`backend/app/core/rate_limit.py`). See [API Reference](API-Reference.md#rate-limits) for the endpoints in each bucket.

| Variable | Default | Applies to |
|---|---|---|
| `RATE_LIMIT_ENABLED` | `true` | Master switch. The test suite sets it to `false`. |
| `RATE_LIMIT_WINDOW_SECONDS` | `600` | Window length. |
| `RATE_LIMIT_SEARCH` | `10` | `/api/search`, `/api/search/sync` |
| `RATE_LIMIT_CHAT` | `30` | `/api/chat` |
| `RATE_LIMIT_COMPARE` | `30` | `/api/compare/destination` |
| `RATE_LIMIT_DISCOVER` | `10` | `/api/discover` |
| `RATE_LIMIT_LIGHT_AI` | `60` | Single-agent routes, `/*/filtered`, `/api/flights/fare-calendar`, `/api/stress-test`, `/api/layover`, `/api/events`, `/api/walking-tours` |

Counters live in process memory: they reset on restart and are not shared between processes or instances, so a multi-instance deployment would need a shared store. Anonymous callers are keyed by the connecting address; behind a reverse proxy all anonymous traffic shares one key unless the proxy address is replaced (for example with uvicorn `--proxy-headers`).

## Logging

`LOG_FORMAT` is read directly with `os.getenv` in `backend/app/main.py`, not through Settings. The default, `json`, gives one JSON object per line (stdlib `logging` with a custom formatter in `backend/app/core/logging_config.py`). Any other value gives plain-text logs.

---

## Frontend

The frontend reads no environment variables at build or run time.

- **Dev:** Vite proxies `/api` and `/health` to `http://localhost:8001` (`frontend/vite.config.js`).
- **Container:** nginx renders `frontend/nginx.conf.template` with `BACKEND_URL` (envsubst) and proxies `/api/` and `/health` to it. Proxy buffering is off so SSE streams, with a 120 s read timeout.

Browser storage used by the app: `tp_token` (login token), `tp_recent_searches_open`, `tp_tour_done:<username>`, `chat_history_<username>`, and the packing-list checkbox state.

---

## Examples

`backend/.env` for local development:

```env
ANTHROPIC_API_KEY=sk-ant-...
JWT_SECRET_KEY=3f0c...   # 64 hex characters
ADMIN_PASSWORD=LocalDevPassword123
# Optional
SERPAPI_KEY=
SERPER_KEY=
RATE_LIMIT_ENABLED=false
LOG_FORMAT=text
```

Values set by `docker-compose.yml`: `ANTHROPIC_API_KEY`, `JWT_SECRET_KEY` (default `change-me-in-compose`), `ADMIN_PASSWORD` (default `admin-dev-password`), `DATA_DIR=/data`, `BACKUP_BUCKET=` (empty) and `CORS_ORIGINS=http://localhost:8080` for the backend, and `BACKEND_URL=http://backend:8001` for the frontend.

The retained Terraform (see [Deployment](Deployment.md)) sets `DATA_DIR=/tmp/data`, `AGENTS_DIR=/app/.agents`, `LOG_FORMAT=json`, `CORS_ORIGINS`, `BACKUP_BUCKET`, and injects `ANTHROPIC_API_KEY`, `JWT_SECRET_KEY`, `ADMIN_PASSWORD`, `SERPAPI_KEY` and `SERPER_KEY` from Secret Manager.
