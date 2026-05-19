# Setup and Installation

This page covers everything needed to run Travel Planner locally, from scratch, in under 10 minutes.

---

## Prerequisites

- **Python 3.11 or later** — the backend uses `asyncio.TaskGroup` patterns and modern type hints
- **Node.js 18 or later** — for the React frontend
- **Docker and Docker Compose** — if you prefer the containerised setup
- **An Anthropic API key** — the agents call Claude; without this, searches will not work
- **Git**

Optional (needed for GCS backup and GCP deployment only):
- Google Cloud SDK (`gcloud`)
- A GCP project with a Cloud Storage bucket

---

## Option A: Direct (no Docker)

This runs the backend and frontend as separate processes on your machine. Best for active development.

### 1. Clone the repository

```bash
git clone https://github.com/rupakc/travel-planner.git
cd travel-planner
```

### 2. Set up the backend

```bash
cd backend
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

Create a `.env` file in the `backend/` directory:

```env
ANTHROPIC_API_KEY=sk-ant-...
JWT_SECRET_KEY=change-this-to-a-random-64-char-string
ADMIN_PASSWORD=your-admin-password
DATA_DIR=./data
AGENTS_DIR=../.agents
CORS_ORIGINS=http://localhost:5173
LOG_FORMAT=console
```

Start the backend:

```bash
uvicorn app.main:app --reload --port 8001
```

The API will be available at `http://localhost:8001`. The interactive docs are at `http://localhost:8001/docs`.

### 3. Set up the frontend

Open a new terminal tab:

```bash
cd frontend
npm install
```

Create a `.env` file in the `frontend/` directory (or the Vite dev proxy will handle this automatically):

```env
VITE_API_URL=http://localhost:8001
```

Start the frontend:

```bash
npm run dev
```

The app will be at `http://localhost:5173`.

### 4. First login

The application has no self-registration — accounts are created by an admin. On first startup, an admin account is created automatically using the `ADMIN_PASSWORD` you set in the backend `.env`.

1. Go to `http://localhost:5173`
2. Click **Login**
3. Username: `admin`, password: whatever you set as `ADMIN_PASSWORD`
4. You will be prompted to change the password on first login
5. To create additional users, use the admin interface or the `/api/admin/users` endpoint

---

## Option B: Docker Compose

This is the quickest way to get a running instance without configuring Python or Node environments.

### 1. Clone and configure

```bash
git clone https://github.com/rupakc/travel-planner.git
cd travel-planner
cp .env.example .env   # if .env.example exists, otherwise create .env
```

Edit `.env` at the project root:

```env
ANTHROPIC_API_KEY=sk-ant-...
JWT_SECRET_KEY=change-this-to-a-random-64-char-string
ADMIN_PASSWORD=your-admin-password
```

### 2. Start everything

```bash
docker compose up --build
```

This builds both the backend and frontend images and starts them. First build takes 3–5 minutes; subsequent starts are fast.

- Frontend: `http://localhost:8080`
- Backend API: `http://localhost:8001`
- Backend docs: `http://localhost:8001/docs`

### 3. Stopping

```bash
docker compose down
```

Use `docker compose down -v` to also remove the data volume (wipes the SQLite databases).

---

## Running tests

### Backend tests

```bash
cd backend
source .venv/bin/activate
pytest
```

For coverage:

```bash
pytest --cov=app --cov-report=term-missing
```

The test suite includes unit tests for individual agents, integration tests for the orchestration flow, and end-to-end tests for the API routes. Most tests mock the Anthropic API to avoid API costs during testing.

### Frontend tests

```bash
cd frontend
npm test
```

---

## Troubleshooting

**Backend won't start: `ModuleNotFoundError`**
Make sure you activated the virtual environment (`source .venv/bin/activate`) before running uvicorn.

**`ANTHROPIC_API_KEY` not found**
The key must be in the `.env` file in the `backend/` directory (not the project root, unless you are using Docker Compose where the root `.env` is used).

**Frontend shows "Network Error" on search**
The Vite dev server proxies `/api/*` to `http://localhost:8001`. If the backend is not running on port 8001, searches will fail with a network error. Check that the backend process is up.

**Agents returning empty results**
Check backend logs for `RetryError` — this usually means the Anthropic API key is invalid or has hit a rate limit. Confirm the key is correct and has available quota.

**Docker Compose port conflict**
If port 8001 or 8080 is already in use, edit `docker-compose.yml` and change the host port mappings. For example, change `"8001:8001"` to `"8002:8001"`.

**`sentence-transformers` download on first run**
The first time ActivitiesAgent runs, it downloads the embedding model (~90 MB). This is normal and happens once. Subsequent runs use the cached model. In Docker, this download happens at image build time.

**GCS backup errors in logs**
If `BACKUP_BUCKET` is not set, GCS backup is silently disabled. This is fine for local development. You will see `GCS backup disabled: BACKUP_BUCKET not configured` in the logs, which is expected.
