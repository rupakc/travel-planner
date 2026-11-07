#!/usr/bin/env bash
# Prints the Caddy runtime id: a SHA-256 over the pinned base image and the
# runtime part of caddy.Dockerfile's final stage. The deploy workflow stores
# it in the image label io.voyager.caddy-runtime; the VM's deploy.sh recreates
# the Caddy container only when it changes (an SPA or Caddyfile change keeps
# the id and is swapped in without a restart).
#
# Runtime part = every line from the last FROM to the end, minus comments,
# blank lines and the two content lines (COPY of the Caddyfile and of the
# built SPA). A new base digest or any other change there (binary, user,
# Caddyfile check) gives a new id.
#
# Usage: caddy-runtime-id.sh BASE_REF [DOCKERFILE]
#   BASE_REF  e.g. caddy:2.10-alpine@sha256:… (exactly the CADDY_BASE build arg)
set -euo pipefail

base="${1:?usage: caddy-runtime-id.sh BASE_REF [DOCKERFILE]}"
dockerfile="${2:-$(dirname "$0")/caddy.Dockerfile}"
[[ "$base" == *@sha256:* ]] || { echo "caddy-runtime-id: BASE_REF must be pinned by digest: $base" >&2; exit 2; }

stage="$(awk '
  /^[[:space:]]*FROM[[:space:]]/ { buf = "" }
  { buf = buf $0 "\n" }
  END { printf "%s", buf }
' "$dockerfile" |
  grep -Ev '^[[:space:]]*(#|$)' |
  grep -Ev '^[[:space:]]*COPY[[:space:]]+(deploy/gcp/Caddyfile[[:space:]]|--from=spa[[:space:]])' || true)"
[[ "$stage" == FROM* ]] || { echo "caddy-runtime-id: no final stage in $dockerfile" >&2; exit 2; }

printf 'base=%s\n%s\n' "$base" "$stage" | sha256sum | cut -c1-64
