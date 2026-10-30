# Setup and Installation

How to run Travel Planner on your own machine. There is no hosted instance any more (see [Deployment](Deployment.md)), so this is also how to try the app.

---

## Prerequisites

- **Python 3.12** (the Dockerfile and CI use 3.12; `pyproject.toml` allows 3.11 or later).
- **Node.js 20** (the Dockerfile and CI use 20; vitest 4 needs `^20 || ^22 || >=24` and jsdom 27 needs 20 or later).
- **An Anthropic API key.** Every agent calls Claude. Without a key the app starts, but every AI section fails.
- **Docker with Compose**, only for the container setup.
- Optional: a **SerpAPI key** (`SERPAPI_KEY`) for live Google Flights fares, the fare calendar and price insights, and a **Serper key** (`SERPER_KEY`) for Places-to-See data and link resolution. Without them, flights come from the LLM and the fare calendar is hidden.

---

## Option A: `start.sh` (recommended for development)

```bash
git clone https://github.com/rupakc/travel-planner.git
cd travel-planner

# Backend dependencies (a virtualenv is recommended)
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt          # add -r requirements-dev.txt for tests and linters
cd ..
```

Create `backend/.env`. The backend reads `.env` from its working directory, which is `backend/` when started by `start.sh`:

```env
ANTHROPIC_API_KEY=sk-ant-...
JWT_SECRET_KEY=<output of: python3 -c "import secrets; print(secrets.token_hex(32))">
ADMIN_PASSWORD=<a password for the seeded admin account>
# Optional
SERPAPI_KEY=
SERPER_KEY=
```

Then, from the repo root:

```bash
./start.sh              # backend on :8001, frontend on :5174
./start.sh --backend    # just one side
./start.sh --frontend
./stop.sh               # stop both (--backend, --frontend, --force)
```

`start.sh` runs `uvicorn app.main:app --reload --port 8001` from `backend/` and `npm run dev` (Vite on port 5174) from `frontend/`. It runs `npm install` when `node_modules` is missing, warns when `ANTHROPIC_API_KEY` or `backend/.env` is missing, waits up to 30 s for each port, writes PIDs to `.pids/` and logs to `.logs/backend.log` and `.logs/frontend.log`. `stop.sh` gives each process a 10 s grace period; `--force` sends SIGKILL.

Open http://localhost:5174. The API's Swagger UI is at http://localhost:8001/docs.

## Option B: by hand

```bash
# Terminal 1
cd backend && pip install -r requirements.txt && uvicorn app.main:app --port 8001 --reload

# Terminal 2
cd frontend && npm install && npm run dev
```

The Vite dev server proxies `/api` and `/health` to `http://localhost:8001` (`frontend/vite.config.js`). The frontend has no `.env` and reads no `VITE_*` variables.

## Option C: Docker Compose

```bash
git clone https://github.com/rupakc/travel-planner.git
cd travel-planner
export ANTHROPIC_API_KEY=sk-ant-...   # or put it in a .env file at the repo root
docker compose up --build
```

- Frontend (nginx): http://localhost:8080
- Backend: http://localhost:8001 (Swagger UI at `/docs`)

`docker-compose.yml` builds the backend from the repo root (`context: .`, `dockerfile: backend/Dockerfile`), because the image copies both `backend/` and `.agents/`. Compose reads `ANTHROPIC_API_KEY`, `JWT_SECRET_KEY` and `ADMIN_PASSWORD` from your shell or a root `.env`. If unset, `JWT_SECRET_KEY` falls back to `change-me-in-compose` and `ADMIN_PASSWORD` to `admin-dev-password`; change both for anything other than a local trial. The backend stores its database in the `backend_data` volume (`DATA_DIR=/data`), GCS backup is off, and the frontend waits for the backend's `/health` check. `docker compose down -v` also deletes the volume and therefore all users and plans.

---

## What happens on first start

The backend's startup (`backend/app/main.py`, lifespan) runs in this order:

1. Restore from GCS (only when `BACKUP_BUCKET` is set).
2. Seed the place and airport data into `$DATA_DIR/airports.db`. This takes about 2 s on the first start and about 5 ms afterwards, because the seed is versioned (see [Place and Airport Data](Place-and-Airport-Data.md)).
3. Build the in-memory airport-name index (about 0.06 s).
4. Seed the nationalities and create the remaining tables.
5. Seed the admin account, if `ADMIN_PASSWORD` is set.
6. Start the 60 s backup loop (a no-op without `BACKUP_BUCKET`).

All data lives in one SQLite file, `$DATA_DIR/airports.db`. `DATA_DIR` defaults to `backend/data`, which is gitignored.

## First login

There is **no self-registration**. Accounts are created by an admin.

1. Open the app and sign in as `admin` (or your `ADMIN_USERNAME`) with the `ADMIN_PASSWORD` you set. The seeded admin is not asked to change the password.
2. Open the **Admin** tab and create users with a temporary password (at least 8 characters). Those users must change it on first login.

`ADMIN_PASSWORD` is only used to create the admin account when it does not exist yet. Changing it later does not change an existing admin's password.

---

## Running the tests

```bash
cd backend && python3 -m pytest -q
cd frontend && npm test
```

See [Testing and CI](Testing-and-CI.md) for coverage, lint and the Node 20.18 workaround.

---

## Troubleshooting

**Every AI section shows an error.** The Anthropic key is missing or invalid, or the account is out of quota. Check `.logs/backend.log`. `GET /health/agents` makes one tiny Haiku call and reports whether the LLM is reachable.

**"Network Error" in the browser.** The backend is not running on port 8001, which the Vite proxy expects.

**No fare calendar and only estimated fares.** `SERPAPI_KEY` is not set. `GET /health` reports `serpapi_configured`.

**429 "Too many requests".** You hit a rate limit (for example 10 searches per 10 minutes). Raise the `RATE_LIMIT_*` values or set `RATE_LIMIT_ENABLED=false` for local work (see [Configuration](Configuration.md)).

**Port already in use.** Run `./stop.sh --force`, or change the host port mappings in `docker-compose.yml`.

**Log lines are JSON.** That is the default. Set `LOG_FORMAT` to any value other than `json` for plain-text logs.
