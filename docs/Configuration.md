# Configuration

All configuration is driven by environment variables, managed via Pydantic Settings (`backend/app/core/config.py`). The backend reads these on startup; missing required variables raise a `ValidationError` that prevents the application from starting.

For local development, put these in `backend/.env`. For Docker Compose, put them in `.env` at the project root. For Cloud Run, they are stored in GCP Secret Manager and injected at deploy time by Terraform.

---

## Required variables

These must be set for the application to start and function.

### `ANTHROPIC_API_KEY`

| | |
|---|---|
| **Required** | Yes |
| **Example** | `sk-ant-api03-...` |
| **What breaks** | All agent calls fail; search returns errors for every section |

Your Anthropic API key. Every AI agent call goes through this key. Without it, the application starts but every search attempt will fail when the agents try to call the API.

Get one at [console.anthropic.com](https://console.anthropic.com).

---

### `JWT_SECRET_KEY`

| | |
|---|---|
| **Required** | Yes |
| **Example** | `a-random-64-character-hex-string` |
| **What breaks** | Authentication fails; tokens cannot be verified |

The secret used to sign and verify JWT access tokens. Must be kept secret and consistent — if you change this, all existing sessions are invalidated (users get logged out).

Generate a suitable value with:
```bash
python -c "import secrets; print(secrets.token_hex(32))"
```

---

### `ADMIN_PASSWORD`

| | |
|---|---|
| **Required** | Yes (on first startup) |
| **Example** | `MySecureAdminPassword123!` |
| **What breaks** | Admin account is created with a default password if missing (security risk) |

The initial password for the `admin` account. The admin user is created on first startup if it does not already exist. The admin is forced to change this password on first login. After the admin password has been changed, this variable is no longer read at runtime (the new password is stored as a bcrypt hash in `users.db`).

---

## Storage variables

### `DATA_DIR`

| | |
|---|---|
| **Required** | No |
| **Default** | `./data` |
| **Example** | `/app/data` |
| **What breaks** | SQLite database files are created relative to the working directory |

The directory where the four SQLite database files (`users.db`, `plans.db`, `preferences.db`, `feedback.db`) are stored. In Docker and Cloud Run deployments this should point to a writable path. The directory is created automatically if it does not exist.

---

### `BACKUP_BUCKET`

| | |
|---|---|
| **Required** | No |
| **Default** | None (GCS backup disabled) |
| **Example** | `my-travel-planner-backups` |
| **What breaks** | SQLite data is not backed up; lost on Cloud Run instance restart |

The name of the GCS bucket to use for SQLite backups. If not set, backup is silently disabled and a log message confirms this. Required for any production or Cloud Run deployment where the local filesystem is ephemeral.

GCS authentication uses Application Default Credentials. In Cloud Run, the service account attached to the Cloud Run service must have `storage.objects.create` and `storage.objects.get` permissions on this bucket.

---

### `AGENTS_DIR`

| | |
|---|---|
| **Required** | No |
| **Default** | `./.agents` |
| **Example** | `/app/.agents` |
| **What breaks** | Agents cannot load their system prompts; all agent calls fail with `FileNotFoundError` |

Path to the directory containing `.agents/*.md` definition files. In Docker images this should be the absolute path where the `.agents/` directory is copied. In local development, the default relative path resolves correctly when the backend is started from the `backend/` directory.

---

## Network variables

### `CORS_ORIGINS`

| | |
|---|---|
| **Required** | No |
| **Default** | `http://localhost:5174` |
| **Example** | `https://travel-planner.example.com,http://localhost:5174` |
| **What breaks** | Browser blocks API requests from your frontend origin |

Comma-separated list of allowed CORS origins. In production, set this to your frontend's public URL. In local development, the default covers the Vite dev server (port 5174). In Cloud Run, Terraform sets this to the frontend Cloud Run service URL.

---

## Logging variables

### `LOG_FORMAT`

| | |
|---|---|
| **Required** | No |
| **Default** | `json` |
| **Values** | `json`, `console` |
| **What breaks** | Nothing breaks; logs are just harder to read |

Controls whether `structlog` outputs JSON (for log aggregation in Cloud Run / Cloud Logging) or human-readable coloured output (for local development). Set to `console` when running locally.

---

## Search API variables (optional)

These are used if you want the agents to perform live web searches to supplement their training data. If not set, agents rely solely on the model's knowledge.

### `SERPER_KEY`

| | |
|---|---|
| **Required** | No |
| **Default** | None |
| **Example** | `abc123...` |

API key for Serper.dev (Google Search API). Used by the PlacesAgent to fetch real-time place data that Claude then synthesises into the `places_to_see` section. Get one at [serper.dev](https://serper.dev).

If not provided, the application falls back to DuckDuckGo search (no key required) for any web search operations.

---

## Example `.env` for local development

```env
# Required
ANTHROPIC_API_KEY=sk-ant-api03-...
JWT_SECRET_KEY=a64charrandombhexstringhere
ADMIN_PASSWORD=LocalDevPassword123

# Storage
DATA_DIR=./data
AGENTS_DIR=../.agents

# Network
CORS_ORIGINS=http://localhost:5174

# Logging
LOG_FORMAT=console
```

## Example `.env` for Docker Compose

```env
# Required
ANTHROPIC_API_KEY=sk-ant-api03-...
JWT_SECRET_KEY=a64charrandombhexstringhere
ADMIN_PASSWORD=LocalDevPassword123

# Storage (Docker paths)
DATA_DIR=/app/data
AGENTS_DIR=/app/.agents

# Network (Docker frontend)
CORS_ORIGINS=http://localhost:8080

# Logging
LOG_FORMAT=console
```
