# Caddy with the built SPA and the Caddyfile inside. Build from the repo root:
#   docker build -f deploy/gcp/caddy.Dockerfile -t voyager-caddy .
#
# Two kinds of content, deployed differently on the VM (deploy/gcp/host/deploy.sh):
#   - the runtime: everything in the final stage except the two content COPY
#     lines (base image, binary, user). The deploy workflow hashes it into the
#     label io.voyager.caddy-runtime (deploy/gcp/caddy-runtime-id.sh); only a
#     change there recreates the Caddy container (after draining SSE streams).
#   - the content: /srv (the SPA) and /etc/caddy/Caddyfile. The VM copies them
#     out of each new image and swaps them in without a restart.
# Keep the runtime layers ABOVE the content COPYs: they then stay cached and
# identical across releases, so the VM pulls only the small SPA layer.
# The runtime id hashes these Dockerfile LINES (plus the base digest), not
# file contents: a runtime COPY of a host file (a plugin, a config) changes
# nothing in the id when only that file changes. Add such a file's contents
# to caddy-runtime-id.sh's inputs, or the VM won't recreate Caddy for it.
#
# Separately, the workflow skips the whole build when nothing this file can
# read changed: io.voyager.caddy-inputs (deploy/ci/image-inputs-id.sh) hashes
# this file, .dockerignore, every COPY source from the context and both
# pinned bases. Use COPY (not ADD) for context files, or the id can't be
# computed and every merge rebuilds.
#
# CADDY_BASE / NODE_BASE: the workflow passes each tag pinned to the digest it
# resolved (CADDY_BASE also goes into the runtime hash; both into the inputs
# id). The defaults are for local builds.
ARG CADDY_BASE=caddy:2.11-alpine
ARG NODE_BASE=node:20-alpine

FROM ${NODE_BASE} AS spa
WORKDIR /app
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM ${CADDY_BASE}
# Non-root (uid 10002); compose lowers the unprivileged-port floor so it can
# bind 80/443. Fresh named volumes on /data and /config inherit this owner.
# The stock binary carries a file capability (cap_net_bind_service); with
# no-new-privileges and every capability dropped its exec would be refused.
# Copying it drops the xattr; the port sysctl makes the capability unneeded.
# /edge/current → the image's own SPA + Caddyfile: the Caddyfile serves from
# /edge/current/srv, and without the VM's edge mount (which hides this
# directory) the image still serves its own content, e.g. under an older
# compose.yaml.
RUN addgroup -S -g 10002 caddy && adduser -S -D -H -u 10002 -G caddy caddy \
    && chown -R caddy:caddy /data /config \
    && cp /usr/bin/caddy /tmp/caddy && mv -f /tmp/caddy /usr/bin/caddy \
    && chmod 0755 /usr/bin/caddy \
    && mkdir -p /edge/baked \
    && ln -s /srv /edge/baked/srv && ln -s /etc/caddy/Caddyfile /edge/baked/Caddyfile \
    && ln -s baked /edge/current
USER 10002
# Content (not part of the runtime hash): root-owned, world-readable
COPY deploy/gcp/Caddyfile /etc/caddy/Caddyfile
COPY --from=spa /app/dist /srv
# Fail the build on a Caddyfile error (placeholder values for the check only)
RUN SITE_HOST=voyager.example.test ACME_EMAIL=ops@example.test \
    caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile
