FROM python:3.12-slim

WORKDIR /app

# Install deps first for layer caching
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY backend/ ./

# Copy agent definitions (project root .agents/ → /app/.agents/)
COPY .agents/ .agents/

EXPOSE 8001

# Entrypoint: optional Secret Manager secrets into the process env, refuses an
# empty JWT_SECRET_KEY, then execs uvicorn (1 worker, graceful shutdown 5 s,
# proxy headers only from FORWARDED_ALLOW_IPS) — see app/entrypoint.py
CMD ["python", "-m", "app.entrypoint"]
