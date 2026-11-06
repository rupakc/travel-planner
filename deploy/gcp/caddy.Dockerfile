# Caddy with the built SPA baked in. Build from the repo root:
#   docker build -f deploy/gcp/caddy.Dockerfile -t voyager-caddy .
FROM node:20-alpine AS spa
WORKDIR /app
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM caddy:2.10-alpine
COPY deploy/gcp/Caddyfile /etc/caddy/Caddyfile
COPY --from=spa /app/dist /srv
# Fail the build on a Caddyfile error (placeholder values for the check only)
RUN SITE_HOST=voyager.example.test ACME_EMAIL=ops@example.test \
    caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile
