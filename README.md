# Travel Planner

AI-powered travel planning. Give it your destination, dates, and interests — it returns flights, hotels, activities, visa requirements, SIM recommendations, transport options, and a day-by-day itinerary in one go. Results stream section by section in real time.

## Live App

| | URL |
|---|---|
| **Frontend** | https://travel-planner-frontend-2hrxgxqboa-ew.a.run.app |
| **Backend API** | https://travel-planner-backend-2hrxgxqboa-ew.a.run.app |
| **API docs** | https://travel-planner-backend-2hrxgxqboa-ew.a.run.app/docs |
| **Project docs** | https://rupakc.github.io/travel-planner/ |

The frontend proxies all `/api/*` calls to the backend, so most users only need the frontend URL. Use the backend URL directly for API exploration or health checks (`/health`).

## Features

- **Multi-agent AI** — 9 specialist Claude agents run in parallel (flights, hotels, activities, places to see, visa, SIM, tips, transport, itinerary)
- **Places to See** — dedicated agent combining live Serper/Google Maps data with Claude synthesis to surface must-visit landmarks, temples, museums, and viewpoints with ratings, visit durations, and direct links
- **Real-time streaming** — results appear section by section via SSE, no waiting for all agents
- **My Plan** — select flights, hotels, activities, places, and more into a named plan; save and reload anytime
- **Chat interface** — conversational trip planning with session memory, smart routing, suggestion chips, and real-time budget tracker; auto-triggers the full agent pipeline
- **User feedback** — floating feedback widget on every page; admin can view and export
- **Multi-user auth** — admin-created accounts with forced first-login password change
- **Admin panel** — create/deactivate users, view feedback, manage the app
- **Mobile responsive** — works on all screen sizes
- **Production-ready** — Cloud Run, Terraform IaC, GitHub Actions CI/CD, structured logging, Cloud Monitoring

## Architecture

### GCP Production Deployment

```
╔══════════════════════════════════════════════════════════════════════════════════════╗
║  DEVELOPER MACHINE / PR                                                              ║
║                                                                                      ║
║   git push → main                                                                    ║
╚══════════════╦═══════════════════════════════════════════════════════════════════════╝
               │
               ▼
╔══════════════════════════════════════════════════════════════════════════════════════╗
║  GITHUB                                                                              ║
║                                                                                      ║
║  ┌─────────────────────────────────────────────────────────────────────────────┐    ║
║  │  .github/workflows/deploy.yml  (triggered on push to main)                  │    ║
║  │                                                                              │    ║
║  │  ┌─────────────────┐    ┌───────────────────┐    ┌────────────────────────┐ │    ║
║  │  │  1. bootstrap   │───►│  2. push-images   │───►│  3. terraform          │ │    ║
║  │  │                 │    │                   │    │                        │ │    ║
║  │  │ • Enable APIs   │    │ • docker build    │    │ • terraform init       │ │    ║
║  │  │ • Create TF     │    │   backend:$SHA    │    │   (GCS remote state)   │ │    ║
║  │  │   state bucket  │    │ • docker build    │    │ • terraform validate   │ │    ║
║  │  │ • Create        │    │   frontend:$SHA   │    │ • terraform plan       │ │    ║
║  │  │   Artifact      │    │ • Push both to    │    │ • terraform apply      │ │    ║
║  │  │   Registry repo │    │   Artifact        │    │ • Output URLs          │ │    ║
║  │  │ • Upsert        │    │   Registry        │    │                        │ │    ║
║  │  │   secrets into  │    │                   │    │                        │ │    ║
║  │  │   Secret Mgr    │    │                   │    │                        │ │    ║
║  │  └─────────────────┘    └───────────────────┘    └────────────────────────┘ │    ║
║  └─────────────────────────────────────────────────────────────────────────────┘    ║
║                                                                                      ║
║  Secrets used by Actions:                                                            ║
║  GCP_PROJECT_ID · GCP_SA_KEY · ANTHROPIC_API_KEY · JWT_SECRET_KEY · ADMIN_PASSWORD  ║
╚══════════════╦═══════════════════════════════════════════════════════════════════════╝
               │  Terraform apply
               ▼
╔══════════════════════════════════════════════════════════════════════════════════════╗
║  GCP PROJECT  (region: europe-west1)                                                 ║
║                                                                                      ║
║  ┌──────────────────────────────────────────────────────────────────────────────┐   ║
║  │  Artifact Registry                                                           │   ║
║  │  europe-west1-docker.pkg.dev/{project}/travel-planner                        │   ║
║  │                                                                              │   ║
║  │    backend:{git-sha}   frontend:{git-sha}                                    │   ║
║  └──────────┬──────────────────────┬───────────────────────────────────────────┘   ║
║             │ image ref            │ image ref                                       ║
║             ▼                      ▼                                                 ║
║  ┌─────────────────────┐   ┌──────────────────────────────────────────────────┐    ║
║  │  Cloud Run          │   │  Cloud Run                                        │    ║
║  │  travel-planner-    │◄──│  travel-planner-frontend                          │    ║
║  │  backend            │   │                                                   │    ║
║  │                     │   │  nginx:alpine (2-stage build)                     │    ║
║  │  python:3.12-slim   │   │  port 8080  •  Gen2                               │    ║
║  │  port 8001  •  Gen2 │   │  min=0, max=3  •  512Mi / 1 CPU                  │    ║
║  │  min=0, max=5       │   │                                                   │    ║
║  │  1Gi / 1 CPU        │   │  ┌──────────────────────────────────────────┐    │    ║
║  │                     │   │  │  nginx.conf.template                     │    │    ║
║  │  FastAPI + uvicorn  │   │  │                                          │    │    ║
║  │  1 worker           │   │  │  /assets/*  → immutable cache (1 year)  │    │    ║
║  │                     │   │  │  /api/*     → proxy_pass $BACKEND_URL   │    │    ║
║  │  ┌─────────────┐    │   │  │               proxy_buffering off       │    │    ║
║  │  │ SQLite DBs  │    │   │  │               proxy_read_timeout 120s   │    │    ║
║  │  │  /tmp/data  │    │   │  │               (SSE-safe)                │    │    ║
║  │  │             │    │   │  │  /health    → proxy to backend          │    │    ║
║  │  │ users.db    │    │   │  │  /*         → /index.html (SPA)         │    │    ║
║  │  │ plans.db    │    │   │  └──────────────────────────────────────────┘    │    ║
║  │  │ prefs.db    │    │   │                                                   │    ║
║  │  │ feedback.db │    │   │  React 18 + Vite SPA                             │    ║
║  │  └──────┬──────┘    │   │  Web Workers: sseWorker.js, chatWorker.js        │    ║
║  │         │           │   └──────────────────────────────────────────────────┘    ║
║  │  ┌──────▼──────┐    │                        ▲                                   ║
║  │  │  Backup     │    │                        │ HTTPS (port 443)                  ║
║  │  │  every 5min │    │                ┌───────┴──────────────────────────┐        ║
║  │  │  + SIGTERM  │    │                │  USER BROWSER                    │        ║
║  │  └──────┬──────┘    │                │                                  │        ║
║  │         │           │                │  https://travel-planner-         │        ║
║  └─────────┼───────────┘                │  frontend-xxx.a.run.app          │        ║
║            │ GCS write                  │                                  │        ║
║            ▼                            │  REST / SSE requests             │        ║
║  ┌───────────────────────────────┐      │  via nginx proxy                 │        ║
║  │  Cloud Storage                │      └──────────────────────────────────┘        ║
║  │                               │                                                   ║
║  │  {project}-sqlite-backup      │                                                   ║
║  │  • Versioning enabled         │                                                   ║
║  │  • Keep 10 most recent        │                                                   ║
║  │  • Restore on cold start      │                                                   ║
║  │                               │                                                   ║
║  │  {project}-tf-state           │                                                   ║
║  │  • Terraform remote state     │                                                   ║
║  │  • Versioning enabled         │                                                   ║
║  └───────────────────────────────┘                                                   ║
║                                                                                      ║
║  ┌───────────────────────────────────────────────────────────────────────────────┐  ║
║  │  Secret Manager                                                               │  ║
║  │                                                                               │  ║
║  │  anthropic-api-key  ──►  backend (env var, injected at container start)       │  ║
║  │  jwt-secret-key     ──►  backend (env var, injected at container start)       │  ║
║  │  admin-password     ──►  backend (env var, injected at container start)       │  ║
║  │                                                                               │  ║
║  │  Accessed by: Default Compute SA (roles/secretmanager.secretAccessor)         │  ║
║  └───────────────────────────────────────────────────────────────────────────────┘  ║
║                                                                                      ║
║  ┌───────────────────────────────────────────────────────────────────────────────┐  ║
║  │  Cloud Monitoring + Cloud Logging                                             │  ║
║  │                                                                               │  ║
║  │  Uptime Check: GET /health every 60s from europe-west1                        │  ║
║  │                                                                               │  ║
║  │  Alert Policies (→ email: admin@dataguard.com):                               │  ║
║  │    • Uptime check fails for > 2 min                                           │  ║
║  │    • 5xx error rate > 5% over 5 min                                           │  ║
║  │    • p99 latency > 10 000 ms over 5 min                                       │  ║
║  │                                                                               │  ║
║  │  Log-based Metrics:                                                           │  ║
║  │    • api_request_count   (jsonPayload.event = "api_request")                  │  ║
║  │      labels: path, status_code                                                │  ║
║  │    • feature_usage_count (jsonPayload.event = "feature_used")                 │  ║
║  │      labels: feature, page                                                    │  ║
║  │                                                                               │  ║
║  │  Dashboard: Request count • Error rate • p50/p99 latency • Feature usage      │  ║
║  │                                                                               │  ║
║  │  Cloud Logging: structured JSON stdout (LOG_FORMAT=json)                      │  ║
║  │    Backend emits: api_request, feature_used, request_id per request           │  ║
║  └───────────────────────────────────────────────────────────────────────────────┘  ║
╚══════════════════════════════════════════════════════════════════════════════════════╝
```

### Runtime Request Flow

```
Browser
  │
  │  GET / (or /chat, /preferences, /admin)
  ▼
Cloud Run: travel-planner-frontend  (nginx, port 8080)
  │  SPA: serves /index.html → React app boots in browser
  │
  │  POST /api/search  (or /api/chat, /api/auth/*, etc.)
  │  nginx proxies to: $BACKEND_URL/api/  (HTTPS, SNI, no buffering)
  ▼
Cloud Run: travel-planner-backend  (FastAPI, port 8001)
  │
  ├── Auth middleware: validates JWT, attaches user to request state
  ├── Request-ID middleware: generates X-Request-ID, stamps all logs
  ├── Analytics middleware: logs api_request event on every response
  │
  ├── POST /api/search ──► TravelOrchestrator.stream_run()
  │       │                        │
  │       │   text/event-stream    │  Phase 0 — Static lookups (< 1s)
  │       │   (Server-Sent Events) │    visa, sim, tips, getting_around
  │       │◄──────────────────────┤
  │       │                        │  Phase 1 — Parallel AI agents
  │       │                        │    9 agents via asyncio.gather():
  │       │                        │    flights, hotels, activities,
  │       │                        │    places, visa*, sim*, tips*,
  │       │                        │    forex, getting_around*
  │       │                        │    (* AI enhances static fallback)
  │       │◄──────────────────────┤
  │       │                        │  Phase 2 — Sequential synthesis
  │       │                        │    itinerary (waits for activities
  │       │                        │    + hotels, 60s timeout)
  │       │◄──────────────────────┤
  │       │
  ├── POST /api/chat  ──► ChatAgent → same pipeline if trip request
  │
  ├── SQLite I/O  →  /tmp/data/{users,plans,preferences,feedback}.db
  │
  ├── Anthropic API  →  https://api.anthropic.com  (claude-* models)
  │     Each agent: claude_agent_sdk.query() with agent .md definition
  │
  └── Cloud Storage  →  gs://{project}-sqlite-backup/
        backup_to_gcs() every 5 min + on SIGTERM
        restore_from_gcs() on cold start (container /tmp is ephemeral)
```

### Multi-Agent System (inside backend)

```
TravelOrchestrator
│
├── Phase 0 — instant static results (no AI call)
│     VisaAgent.static()           → lookup table by nationality + destination
│     SimAgent.static()            → lookup table by destination
│     TipsAgent.static()           → lookup table by destination
│     GettingAroundAgent.static()  → lookup table by destination
│     (all 4 stream immediately; UI shows "Enhancing…" badge)
│
├── Phase 1 — parallel AI agents  (asyncio.gather, each agent independent)
│     FlightsAgent         → flight search + pricing
│     HotelsAgent          → hotels across 4 budget tiers
│     ActivitiesAgent      → activities scored by interest relevance
│                            (sentence-transformers + sklearn cosine sim)
│     PlacesAgent          → must-see landmarks, temples, museums, viewpoints
│                            Serper /places + /search → Claude synthesis
│                            SerperPlacesResolver enriches top-5 with
│                            TripAdvisor/Timeout/Lonely Planet URLs
│     VisaAgent            → AI-enhanced visa + vaccinations + customs
│     SimAgent             → AI-enhanced eSIM / local SIM plans
│     TipsAgent            → AI-enhanced safety + culture tips
│     ForexAgent           → exchange rates + card advice
│     GettingAroundAgent   → AI-enhanced city + intercity transport
│
│     Each agent:
│       loader.py reads .agents/{name}.md  (YAML frontmatter + system prompt)
│       BaseAgent.execute() → claude_agent_sdk.query()
│       BaseAgent._parse_json() — 3-strategy extraction:
│         1. direct json.loads
│         2. ```json ... ``` code block
│         3. regex first {...} / [...]
│
│     Error handling: AI error for visa/sim/tips/getting_around
│     is SUPPRESSED — static data is retained instead
│
└── Phase 2 — sequential synthesis (starts when activities+hotels done)
      ItineraryAgent → day-by-day plan from activities + hotels
      60s timeout → client-side fallback template if agent too slow
```

### IAM & Security

```
Service Accounts
│
├── GitHub Actions SA  (GCP_SA_KEY secret in GitHub)
│     roles/run.admin
│     roles/storage.admin
│     roles/artifactregistry.admin
│     roles/secretmanager.admin
│     roles/iam.serviceAccountUser       ← self-granted by Terraform
│     roles/resourcemanager.projectIamAdmin
│
├── Default Compute SA  (used by Cloud Run at runtime)
│     roles/secretmanager.secretAccessor  ← reads 3 secrets at startup
│     roles/storage.objectAdmin           ← backup / restore SQLite to GCS
│
└── Cloud Run services  (public access)
      roles/run.invoker → allUsers  (no Cloud Run auth layer; app handles JWT)

JWT Auth (app-level)
  Login  →  POST /api/auth/login  →  returns signed JWT (HS256, jwt-secret-key)
  Every request  →  Authorization: Bearer <token>  →  FastAPI dependency
  Admin routes   →  require_admin dependency checks is_admin flag in users.db
  First login    →  requires_password_change flag  →  redirected to /change-password
```

### Data Stores

```
SQLite (ephemeral — /tmp/data, backed up to GCS)
│
├── users.db       — id, username, password_hash, is_admin, is_first_login, is_active
├── plans.db       — id, user_id, name, search_data (JSON), selections (JSON)
├── preferences.db — user_id, nationality, interests, budget, residence_permits, etc.
└── feedback.db    — id, username, page, rating, category, message, metadata, created_at

GCS Backup  gs://{project}-sqlite-backup/
  • Full backup of /tmp/data/*.db   every 5 minutes (background asyncio.Task)
  • Final backup on SIGTERM          (Cloud Run sends SIGTERM before shutdown)
  • Full restore from GCS on startup (before accepting traffic)
  • Versioned bucket, keep 10 versions per object
  ⚠ Cold start latency: +1–3s for GCS restore (acceptable for beta)
```

See [docs/architecture.md](docs/architecture.md) for further detail on agent design.

## Quick Start

```bash
# Clone
git clone https://github.com/your-org/travel-planner && cd travel-planner

# Set up environment
cp backend/.env.example backend/.env
# Edit backend/.env — set ANTHROPIC_API_KEY and ADMIN_PASSWORD at minimum

# Start both servers
./start.sh

# Open
open http://localhost:5174
```

## Running with Docker

```bash
cp backend/.env.example .env  # set ANTHROPIC_API_KEY, ADMIN_PASSWORD
docker compose up
open http://localhost:8080
```

## API

| Endpoint | Description |
|---|---|
| `POST /api/auth/login` | JWT login |
| `GET  /api/auth/me` | Current user |
| `POST /api/auth/change-password` | Update password |
| `GET  /api/admin/users` | List users (admin) |
| `POST /api/admin/users` | Create user (admin) |
| `POST /api/search` | SSE streaming trip search |
| `POST /api/chat` | SSE streaming chat |
| `GET/PUT /api/preferences` | User preferences |
| `GET/POST /api/plans` | Saved plans |
| `POST /api/feedback` | Submit feedback |
| `GET  /api/admin/feedback` | View feedback (admin) |
| `POST /api/analytics/events` | Track frontend events |
| `GET  /health` | Health check |

Full OpenAPI docs available at `/docs` when the backend is running.

## Configuration

| Variable | Default | Description |
|---|---|---|
| `ANTHROPIC_API_KEY` | — | Required. Your Anthropic API key |
| `ADMIN_PASSWORD` | — | Seeds the initial `admin` account on startup |
| `JWT_SECRET_KEY` | `change-me` | JWT signing secret — change in production |
| `DATA_DIR` | `backend/data` | Where SQLite databases are stored |
| `BACKUP_BUCKET` | (empty) | GCS bucket for SQLite backup; empty = disabled |
| `CORS_ORIGINS` | `http://localhost:5174` | Allowed CORS origins (comma-separated list) |
| `LOG_FORMAT` | `json` | `json` for Cloud Logging, `text` for local dev |
| `SERPER_KEY` | (empty) | Serper.dev API key for Places to See Google data; agent falls back to Claude-only if unset |

## Running Tests

```bash
# Backend (from backend/)
pip install -r requirements-dev.txt
pytest --cov=app --cov-fail-under=70

# Frontend unit tests (from frontend/)
npx vitest run --coverage

# E2E tests (requires docker compose up)
docker compose up -d
npx playwright test
docker compose down
```

## Deployment

See [DEPLOYMENT.md](DEPLOYMENT.md) for step-by-step GCP deployment.

## Developer Docs

Auto-generated from code, published to GitHub Pages on every push to `main`:
`https://<your-org>.github.io/travel-planner`

## Contributing

See [docs/contributing.md](docs/contributing.md).

## License

MIT
