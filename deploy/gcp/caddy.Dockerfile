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
# Non-root (uid 10002); compose lowers the unprivileged-port floor so it can
# bind 80/443. Fresh named volumes on /data and /config inherit this owner.
# The stock binary carries a file capability (cap_net_bind_service); with
# no-new-privileges and every capability dropped its exec would be refused.
# Copying it drops the xattr; the port sysctl makes the capability unneeded.
RUN addgroup -S -g 10002 caddy && adduser -S -D -H -u 10002 -G caddy caddy \
    && chown -R caddy:caddy /data /config \
    && cp /usr/bin/caddy /tmp/caddy && mv -f /tmp/caddy /usr/bin/caddy \
    && chmod 0755 /usr/bin/caddy
USER 10002
# Fail the build on a Caddyfile error (placeholder values for the check only)
RUN SITE_HOST=voyager.example.test ACME_EMAIL=ops@example.test \
    caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile
