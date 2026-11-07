# PYTHON_BASE: the deploy workflow passes this tag pinned to the digest it
# resolved; the same string goes into the image's inputs id
# (deploy/ci/image-inputs-id.sh), so a new base digest rebuilds the image.
ARG PYTHON_BASE=python:3.12-slim
FROM ${PYTHON_BASE}

WORKDIR /app

# Install deps first for layer caching
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY backend/ ./

# Copy agent definitions (project root .agents/ → /app/.agents/)
COPY .agents/ .agents/

# Non-root (uid 10001). /data is the DB mount point: a fresh named volume
# inherits this ownership; on the VM first-boot.sh chowns the host directory.
RUN useradd --system --uid 10001 --no-create-home --shell /usr/sbin/nologin voyager \
    && mkdir -p /data && chown voyager:voyager /data
USER 10001

EXPOSE 8001

# Entrypoint: optional Secret Manager secrets into the process env, refuses an
# empty JWT_SECRET_KEY, then execs uvicorn (1 worker, graceful shutdown 5 s,
# proxy headers only from FORWARDED_ALLOW_IPS) — see app/entrypoint.py
CMD ["python", "-m", "app.entrypoint"]
