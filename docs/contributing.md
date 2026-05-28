# Contributing

## Local Setup

```bash
# Backend
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt
cp .env.example .env  # set ANTHROPIC_API_KEY

# Frontend
cd frontend
npm install
```

## Running Servers

```bash
./start.sh   # starts backend (8001) + frontend (5174)
./stop.sh    # stops both
```

## Code Style

- **Backend**: `ruff` for linting and formatting (`ruff check`, `ruff format`)
- **Frontend**: ESLint with project config (`npx eslint src/`)
- **No comments** unless the WHY is non-obvious
- **No error handling** for scenarios that can't happen
- **No abstractions** beyond what the task requires

## Tests

```bash
# Backend
cd backend
pytest --cov=app --cov-fail-under=70 -q

# Frontend unit
cd frontend
npx vitest run

# E2E (requires docker compose up)
docker compose up -d
cd frontend && npx playwright test
docker compose down
```

Coverage gate: 70% minimum on backend (`--cov-fail-under=70`). There is no enforced gate for frontend unit tests.

## Adding Agents

See [Agent System](agents.md) for instructions on adding new specialist agents.

## CI Pipeline

Each push runs the following stages in order:

1. **Lint** — `ruff check` (backend) and `eslint` (frontend)
2. **Security scan** — `bandit` on the backend source tree
3. **Test** — `pytest --cov` with the 70% gate (backend) + `vitest run` (frontend)
4. **Build** — Docker image build for backend and Vite production build for frontend
5. **Deploy** — automatic deploy to Cloud Run on merge to `main`

All five stages must pass before a PR can be merged.

## Pull Request Flow

1. Branch off `main`
2. CI runs automatically on push
3. All CI checks must pass before merge
4. Merge to `main` triggers automatic deploy
