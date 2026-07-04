---
name: verify
description: How to launch and drive this app locally to verify backend/chat changes end-to-end.
---

# Verifying travel-planner changes

## Backend (FastAPI, port of your choice)

```bash
cd backend
DATA_DIR=$(mktemp -d) ADMIN_PASSWORD='verify-pw-123!' \
JWT_SECRET_KEY='verify-secret-key-32chars-long!' \
python3 -m uvicorn app.main:app --port 8011
```

- `backend/.env` holds a real `ANTHROPIC_API_KEY`, so AI paths work locally.
- `DATA_DIR` override gives an isolated SQLite DB; the admin account is
  seeded from `ADMIN_PASSWORD` on startup.
- Health check: `curl localhost:8011/health`.

## Getting a token

```bash
TOKEN=$(curl -s -X POST localhost:8011/api/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"username":"admin","password":"verify-pw-123!"}' | jq -r .access_token)
```

## Driving chat (SSE)

```bash
curl -sN -X POST localhost:8011/api/chat \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"messages":[{"role":"user","content":"..."}]}'
```

- Conversational replies stream as `delta` events and must end with `done`.
- Specialist queries (e.g. "Do I need a visa for Tokyo? I'm British") take
  30–90s and emit `planning_start` / `section_result` /
  `session_context_update` / `planning_done`.
- To exercise the error path, start a second instance with
  `ANTHROPIC_API_KEY='sk-ant-invalid'` — the stream must still deliver a
  friendly `delta`, then `error`, then `done`.

## Frontend

`cd frontend && npm run dev` (port 5174, proxies /api → 8001). Unit tests:
`npm test`; CI lint gate is `npx eslint src/ --max-warnings 0`.
