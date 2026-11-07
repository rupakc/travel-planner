#!/usr/bin/env bash
# Voyager pull deployer (runs on the VM every minute via voyager-deploy.timer).
#
#   1. Resolve the `prod` tag of both images to digests (GHCR, anonymous: one
#      token, cached for 4 min, and two HEAD requests). Nothing new → done
#      (no pull, no cosign). A 429 from GHCR backs off (Retry-After, else
#      exponentially, up to 30 min).
#   2. Verify each new digest's cosign keyless signature: it must come from
#      this repo's deploy workflow on refs/heads/main. Anything else is refused.
#   3. App: pull by digest, pin it in images.env (previous one kept),
#      `compose up -d app`, wait for healthy (240 s); unhealthy → previous
#      digest back, the bad one held.
#   4. Caddy image (SPA + Caddyfile + Caddy runtime), never restarting Caddy
#      for content:
#      - copy /srv and the Caddyfile out of the image (docker create + cp,
#        never run) into $EDGE_DIR/releases/<id>, check them (regular files
#        and directories only, index.html and its assets present), and switch
#        the symlinks current → new, prev1 → old current, prev2 → old prev1.
#        Caddy serves the SPA from /edge/current/srv and /assets/* from
#        current, prev1 and prev2 (browsers holding an older index.html).
#      - Caddyfile changed → adapt + validate it (throwaway container, real
#        SITE_HOST/ACME_EMAIL), then load it through the admin API: graceful,
#        open connections (SSE) keep running. Failure → old config stays,
#        symlinks switched back, digest held, email.
#      - Caddy *runtime* changed (label io.voyager.caddy-runtime: base image,
#        binary, user; see caddy-runtime-id.sh) → wait up to 90 s for open
#        SSE streams to finish (the app's /internal/streams), recreate the
#        container, check it (admin API, index.html and an asset through
#        Caddy) and roll back to the previous runtime + release on failure.
#   5. Converge: `compose up -d` brings back anything that was stopped (e.g.
#      by a Docker upgrade) and applies a changed compose.yaml. When that
#      would recreate Caddy (its compose config hash changed), drain first.
#
# images.env: APP_IMAGE / PREV_APP_IMAGE, CADDY_IMAGE / PREV_CADDY_IMAGE (the
# runtime compose runs; changes only on runtime changes), CADDY_CONTENT_IMAGE
# / PREV_CADDY_CONTENT_IMAGE (where the live SPA + Caddyfile came from).
#
# An image built by an OLDER deploy run than the running one (label
# io.voyager.build = the workflow's run number) is refused: moving `prod`
# back, or re-running an old workflow run, can't downgrade production. Use a
# rollback option or --allow-downgrade on purpose.
#
# Usage: deploy.sh [--rollback | --rollback-edge | --rollback-caddy] [--allow-downgrade]
#   --rollback        app → previous digest (held)
#   --rollback-edge   SPA + Caddyfile → previous release (held), no restart
#   --rollback-caddy  Caddy runtime → previous image (held), drain + recreate
#   --window          accepted and ignored (Caddy no longer waits for a window)
# Config: /etc/voyager/deploy.env (optional overrides of the defaults below).
set -euo pipefail

CONFIG="${VOYAGER_DEPLOY_CONFIG:-/etc/voyager/deploy.env}"
# shellcheck source=/dev/null
[[ -f "$CONFIG" ]] && . "$CONFIG"

REPO="${REPO:-rupakc/travel-planner}"
REGISTRY="${REGISTRY:-ghcr.io}"
APP_REPO="${APP_REPO:-$REGISTRY/rupakc/travel-planner-app}"
CADDY_REPO="${CADDY_REPO:-$REGISTRY/rupakc/travel-planner-caddy}"
TAG="${TAG:-prod}"
COMPOSE_DIR="${COMPOSE_DIR:-/opt/voyager}"
# Pinned by digest (v2.4.1): the verifier itself must not float
COSIGN_IMAGE="${COSIGN_IMAGE:-ghcr.io/sigstore/cosign/cosign:v2.4.1@sha256:b03690aa52bfe94054187142fba24dc54137650682810633901767d8a3e15b31}"
CERT_IDENTITY="${CERT_IDENTITY:-https://github.com/$REPO/.github/workflows/deploy.yml@refs/heads/main}"
CERT_ISSUER="${CERT_ISSUER:-https://token.actions.githubusercontent.com}"
# ≥ the app's health start_period (180 s) + margin: a place-data reseed on
# pd-standard must not be mistaken for a failed deploy
HEALTH_TIMEOUT="${HEALTH_TIMEOUT:-240}"
# Edge: releases on the host, mounted read-only into Caddy at /edge
EDGE_DIR="${EDGE_DIR:-/var/lib/voyager/edge}"
EDGE_MOUNT=/edge
EDGE_MAX_MB="${EDGE_MAX_MB:-200}"
# Before a Caddy recreate: wait this long for open SSE streams to end
DRAIN_TIMEOUT="${DRAIN_TIMEOUT:-90}"
CADDY_HEALTH_TIMEOUT="${CADDY_HEALTH_TIMEOUT:-60}"
# Fixed addresses on the compose network (compose.yaml)
APP_STREAMS_URL="${APP_STREAMS_URL:-http://172.30.0.10:8001/internal/streams}"
CADDY_IP="${CADDY_IP:-172.30.0.20}"
# Seconds between polls (tests: 0)
POLL="${POLL:-3}"
# Token cache, GHCR back-off, signature retry and log-once notes (tmpfs)
STATE_DIR="${STATE_DIR:-/run/voyager-deploy}"

IMAGES_ENV="$COMPOSE_DIR/images.env"
SITE_ENV="$COMPOSE_DIR/site.env"
# Held digests, never deployed automatically: ones that failed their health
# check (or Caddy's checks), and ones an operator rolled back from. A newer
# digest isn't on the list, so publishing one ends the hold. To release a
# digest by hand, delete its line.
FAILED="$COMPOSE_DIR/failed-digests"
# Digests refused as downgrades (built by an older run than the live one):
# remembered so they aren't verified and pulled again every minute.
# --allow-downgrade ignores the list.
REFUSED="$COMPOSE_DIR/refused-digests"
LOCK="${LOCK:-/run/voyager-deploy.lock}"

log() { echo "voyager-deploy: $*" >&2; logger -t voyager-deploy -- "$*" 2>/dev/null || true; }
die() { log "ERROR: $*"; exit 1; }

# log_once KEY MSG — log MSG only when it differs from the last one for KEY
# (the timer runs every minute: a held digest must not log 1,440 times a day)
log_once() {
  local f="$STATE_DIR/note-$1"
  [[ "$(cat "$f" 2>/dev/null)" == "$2" ]] && return 0
  printf '%s' "$2" >"$f" 2>/dev/null || true
  log "$2"
}

compose() {
  docker compose --project-directory "$COMPOSE_DIR" \
    --env-file "$SITE_ENV" --env-file "$IMAGES_ENV" \
    -f "$COMPOSE_DIR/compose.yaml" "$@"
}

# get_var FILE KEY → value of KEY=... (empty if absent)
get_var() {
  [[ -f "$1" ]] || return 0
  sed -n "s/^$2=//p" "$1" | tail -n1
}

listed() { [[ -n "$2" ]] && grep -qxF "$2" "$1" 2>/dev/null; }
hold() { listed "$FAILED" "$1" || echo "$1" >>"$FAILED"; }

# ── images.env ────────────────────────────────────────────────────────────
APP="" PREV_APP="" CADDY="" PREV_CADDY="" CONTENT="" PREV_CONTENT=""
load_images() {
  APP="$(get_var "$IMAGES_ENV" APP_IMAGE)"
  PREV_APP="$(get_var "$IMAGES_ENV" PREV_APP_IMAGE)"
  CADDY="$(get_var "$IMAGES_ENV" CADDY_IMAGE)"
  PREV_CADDY="$(get_var "$IMAGES_ENV" PREV_CADDY_IMAGE)"
  CONTENT="$(get_var "$IMAGES_ENV" CADDY_CONTENT_IMAGE)"
  PREV_CONTENT="$(get_var "$IMAGES_ENV" PREV_CADDY_CONTENT_IMAGE)"
}
save_images() { # atomic
  local tmp
  tmp="$(mktemp "$COMPOSE_DIR/.images.XXXXXX")"
  {
    echo "# Written by deploy.sh — digests verified with cosign"
    echo "APP_IMAGE=$APP"
    echo "CADDY_IMAGE=$CADDY"
    echo "PREV_APP_IMAGE=$PREV_APP"
    echo "PREV_CADDY_IMAGE=$PREV_CADDY"
    echo "CADDY_CONTENT_IMAGE=$CONTENT"
    echo "PREV_CADDY_CONTENT_IMAGE=$PREV_CONTENT"
    echo "UPDATED=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  } >"$tmp"
  chmod 0644 "$tmp"
  mv -f "$tmp" "$IMAGES_ENV"
  sync -f "$IMAGES_ENV" 2>/dev/null || sync
}

# ── Registry (anonymous) ──────────────────────────────────────────────────
BACKOFF="$STATE_DIR/backoff" # "<until epoch> <level>"

# backing_off → true while a GHCR 429 back-off is running
backing_off() {
  local until
  until="$(cut -d' ' -f1 "$BACKOFF" 2>/dev/null || true)"
  [[ "$until" =~ ^[0-9]+$ ]] && (($(date +%s) < until))
}

# back_off RETRY_AFTER — start/extend the back-off after a 429
back_off() {
  local level wait
  level="$(cut -d' ' -f2 "$BACKOFF" 2>/dev/null || true)"
  [[ "$level" =~ ^[0-9]+$ ]] || level=0
  wait=$((60 << level))
  ((wait <= 1800)) || wait=1800
  [[ "$1" =~ ^[0-9]+$ ]] && (($1 > wait)) && wait=$1
  echo "$(($(date +%s) + wait)) $((level < 5 ? level + 1 : 5))" >"$BACKOFF"
  log "GHCR rate limit (429): backing off for ${wait}s"
}

# http FILE_PREFIX CURL_ARGS… → status code; headers in FILE_PREFIX.h, body in .b
http() {
  local p="$1"
  shift
  curl -sS --max-time 20 -D "$p.h" -o "$p.b" -w '%{http_code}' "$@" 2>/dev/null || true
}

retry_after() { tr -d '\r' <"$1.h" | sed -n 's/^[Rr]etry-[Aa]fter: *\([0-9]*\).*/\1/p' | tail -n1; }

# registry_token [fresh] → anonymous pull token for both repos (cached 4 min)
registry_token() {
  local f="$STATE_DIR/token" code
  if [[ "${1:-}" != fresh && -s "$f" ]] && (($(date +%s) - $(stat -c %Y "$f") < 240)); then
    cat "$f"
    return 0
  fi
  code="$(http "$STATE_DIR/tok" \
    "https://$REGISTRY/token?scope=repository:${APP_REPO#"$REGISTRY"/}:pull&scope=repository:${CADDY_REPO#"$REGISTRY"/}:pull")"
  if [[ "$code" == 429 ]]; then
    back_off "$(retry_after "$STATE_DIR/tok")"
    return 1
  fi
  [[ "$code" == 200 ]] || { log "registry token: HTTP $code"; return 1; }
  jq -r '.token // empty' <"$STATE_DIR/tok.b" >"$f.new" && [[ -s "$f.new" ]] ||
    { log "registry token: no token in the answer"; return 1; }
  mv -f "$f.new" "$f"
  cat "$f"
}

# resolve_digest REPO → sha256:… of the `prod` tag's manifest (index)
resolve_digest() {
  local repo="$1" path token code digest try
  path="${repo#"$REGISTRY"/}"
  for try in cached fresh; do
    token="$(registry_token "$try")" || return 1
    code="$(http "$STATE_DIR/head" -I \
      -H "Authorization: Bearer $token" \
      -H "Accept: application/vnd.oci.image.index.v1+json" \
      -H "Accept: application/vnd.docker.distribution.manifest.list.v2+json" \
      -H "Accept: application/vnd.oci.image.manifest.v1+json" \
      -H "Accept: application/vnd.docker.distribution.manifest.v2+json" \
      "https://$REGISTRY/v2/$path/manifests/$TAG")"
    [[ "$code" == 401 && "$try" == cached ]] && continue
    break
  done
  if [[ "$code" == 429 ]]; then
    back_off "$(retry_after "$STATE_DIR/head")"
    return 1
  fi
  [[ "$code" == 200 ]] || { log "manifest $path:$TAG: HTTP $code"; return 1; }
  digest="$(tr -d '\r' <"$STATE_DIR/head.h" | sed -n 's/^[Dd]ocker-[Cc]ontent-[Dd]igest: *//p' | tail -n1)"
  [[ "$digest" =~ ^sha256:[0-9a-f]{64}$ ]] || { log "bad digest for $path:$TAG: '$digest'"; return 1; }
  echo "$digest"
}

# ── Images ────────────────────────────────────────────────────────────────
# verified REF → cosign keyless check. A failure (bad signature, or Sigstore
# unreachable) is retried after 10 min, not every minute.
verified() {
  local ref="$1" f
  f="$STATE_DIR/verify-failed-$(digest_hex "$ref")"
  if [[ -f "$f" ]] && (($(date +%s) - $(stat -c %Y "$f") < 600)); then
    log_once "verify-$(digest_hex "$ref")" "signature check of $ref failed recently: retrying after 10 min"
    return 1
  fi
  log "verifying $ref"
  if docker run --rm --network host "$COSIGN_IMAGE" verify \
    --certificate-identity "$CERT_IDENTITY" \
    --certificate-oidc-issuer "$CERT_ISSUER" \
    "$ref" >/dev/null 2>&1; then
    rm -f "$f"
    return 0
  fi
  touch "$f"
  log "signature check FAILED for $ref: refusing it"
  return 1
}

digest_hex() {
  local h="${1##*@sha256:}"
  [[ "$h" =~ ^[0-9a-f]{64}$ ]] || { log "not a digest reference: $1"; return 1; }
  echo "$h"
}

# label IMAGE KEY → the image's label value, or ""
label() {
  [[ -n "$1" ]] || return 0
  docker image inspect -f "{{ index .Config.Labels \"$2\" }}" "$1" 2>/dev/null |
    sed 's/<no value>//'
}
build_of() { label "$1" io.voyager.build; }
runtime_of() { label "$1" io.voyager.caddy-runtime; }

# older NEW_BUILD CURRENT_BUILD → true if NEW was built by an earlier run
older() { [[ "$1" =~ ^[0-9]+$ && "$2" =~ ^[0-9]+$ ]] && (($1 < $2)); }

# drop_image REF — remove a content-only Caddy image once its files are out
drop_image() {
  [[ -n "$1" && "$1" != "$CADDY" && "$1" != "$PREV_CADDY" ]] || return 0
  docker image rm "$1" >/dev/null 2>&1 || true
}

# ── App ───────────────────────────────────────────────────────────────────
app_health() {
  local cid status
  cid="$(compose ps -q app 2>/dev/null || true)"
  [[ -n "$cid" ]] || { echo missing; return; }
  status="$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' "$cid" 2>/dev/null || echo missing)"
  echo "$status"
}

wait_healthy() {
  local deadline=$((SECONDS + HEALTH_TIMEOUT)) status
  while :; do # check first, then wait: one check even with a 0 s timeout
    status="$(app_health)"
    [[ "$status" == healthy ]] && return 0
    ((SECONDS < deadline)) || break
    sleep 5
  done
  log "app health after ${HEALTH_TIMEOUT}s: $(app_health)"
  return 1
}

# deploy_app NEW → 0 nothing to do or deployed; 1 refused/failed
deploy_app() {
  local new="$1" old="$APP" old_prev="$PREV_APP" b
  [[ "$new" != "$APP" ]] || return 0
  if listed "$FAILED" "$new"; then
    log_once app-held "skipping $new: held (failed its health check, or rolled back from)"
    return 0
  fi
  if ((!ALLOW_DOWNGRADE)) && listed "$REFUSED" "$new"; then
    log_once app-refused "skipping $new: refused as a downgrade (use --allow-downgrade)"
    return 0
  fi
  verified "$new" || return 1
  log "pulling $new"
  docker pull -q "$new" >/dev/null
  b="$(build_of "$new")"
  if ((!ALLOW_DOWNGRADE)) && older "$b" "$(build_of "$APP")"; then
    log "refusing $new: built before the running app (use --allow-downgrade)"
    echo "$new" >>"$REFUSED"
    return 0
  fi
  PREV_APP="$APP" APP="$new"
  save_images
  log "deploying app=$APP"
  compose up -d --no-deps app
  if wait_healthy; then
    log "app healthy"
    return 0
  fi
  hold "$new"
  log "app UNHEALTHY: rolling back to $old"
  APP="$old" PREV_APP="$old_prev"
  save_images
  compose up -d --no-deps app
  if wait_healthy; then
    notify "[voyager] deploy rolled back" "New app $new failed its health check; $old is running again."
  else
    notify "[voyager] deploy FAILED, rollback unhealthy" "Both $new and $old are unhealthy. Check: docker compose logs app"
  fi
  return 1
}

# ── Edge: releases ────────────────────────────────────────────────────────
# release_id REF → the release directory name: the image's full digest (hex
# only, checked), so it can't collide and can't name anything but a release
release_id() { digest_hex "$1"; }

# link NAME → the release path NAME points at (releases/<id>), or ""
link() { readlink "$EDGE_DIR/$1" 2>/dev/null || true; }

# relink NAME TARGET — atomic symlink switch (relative target, rename over)
relink() {
  local tmp="$EDGE_DIR/.$1.$$"
  if [[ -z "$2" ]]; then
    rm -f "$EDGE_DIR/$1"
    return 0
  fi
  ln -sfn "$2" "$tmp"
  mv -T -f "$tmp" "$EDGE_DIR/$1"
}

SAVED_LINKS=()
save_links() { SAVED_LINKS=("$(link current)" "$(link prev1)" "$(link prev2)"); }
restore_links() {
  relink prev2 "${SAVED_LINKS[2]}"
  relink prev1 "${SAVED_LINKS[1]}"
  relink current "${SAVED_LINKS[0]}"
}

# switch_to ID — current → ID; the old current becomes prev1, prev1 prev2
switch_to() {
  local cur prev1
  cur="$(link current)" prev1="$(link prev1)"
  if [[ "$cur" != "releases/$1" ]]; then
    [[ -z "$prev1" ]] || relink prev2 "$prev1"
    [[ -z "$cur" ]] || relink prev1 "$cur"
  fi
  relink current "releases/$1"
}

# edge_ok → current points at a complete release
edge_ok() {
  local c="$EDGE_DIR/current"
  [[ -L "$c" && -f "$c/srv/index.html" && -f "$c/Caddyfile" && -f "$c/.complete" ]]
}

# prune — keep the releases current/prev1/prev2 point at, delete the rest
prune() {
  local keep d
  keep=" $(link current) $(link prev1) $(link prev2) "
  for d in "$EDGE_DIR"/releases/*/; do
    [[ -d "$d" ]] || continue
    d="${d%/}"
    [[ "$keep" == *" releases/${d##*/} "* ]] || rm -rf -- "$d"
  done
  rm -rf -- "$EDGE_DIR"/.staging/* 2>/dev/null || true
}

# check_release DIR — what an image put in /srv and the Caddyfile is served
# by Caddy (as uid 10002) and never executed. Refuse anything that could
# point outside the release: only regular files and directories.
check_release() {
  local dir="$1" bad ref mb
  [[ -d "$dir/srv" && ! -L "$dir/srv" ]] || { log "release: no /srv directory"; return 1; }
  [[ -f "$dir/Caddyfile" && ! -L "$dir/Caddyfile" ]] || { log "release: no regular Caddyfile"; return 1; }
  bad="$(find "$dir/srv" ! -type f ! -type d -print -quit)"
  [[ -z "$bad" ]] || { log "release: refusing non-regular file ${bad#"$dir"/} (symlink/device/fifo)"; return 1; }
  [[ -f "$dir/srv/index.html" ]] || { log "release: no srv/index.html"; return 1; }
  mb="$(du -sm "$dir/srv" | cut -f1)"
  ((mb <= EDGE_MAX_MB)) || { log "release: srv is ${mb} MB (> ${EDGE_MAX_MB} MB)"; return 1; }
  # Every asset index.html loads must be there (a broken build, not a 404 later)
  while IFS= read -r ref; do
    [[ -n "$ref" ]] || continue
    [[ "$ref" != *..* ]] || { log "release: bad asset path $ref"; return 1; }
    [[ -f "$dir/srv$ref" ]] || { log "release: index.html loads missing $ref"; return 1; }
  done < <(grep -oE '(src|href)="/assets/[^"?#]+' "$dir/srv/index.html" | sed 's/^[a-z]*="//' || true)
}

# extract_release REF ID — copy /srv and the Caddyfile out of a verified,
# pulled image into releases/ID (never starting a container), check, normalise
extract_release() {
  local ref="$1" id="$2" rel="$EDGE_DIR/releases/$2" tmp cid ok=1
  [[ -f "$rel/.complete" ]] && return 0 # already there (e.g. a rollback)
  install -d -m 0755 "$EDGE_DIR" "$EDGE_DIR/releases" "$EDGE_DIR/.staging"
  rm -rf -- "$EDGE_DIR"/.staging/*
  tmp="$(mktemp -d "$EDGE_DIR/.staging/$id.XXXXXX")"
  cid="$(docker create --pull never --network none "$ref")" || { rm -rf -- "$tmp"; log "docker create $ref failed"; return 1; }
  { docker cp "$cid:/srv" "$tmp/srv" && docker cp "$cid:/etc/caddy/Caddyfile" "$tmp/Caddyfile"; } >/dev/null 2>&1 || ok=0
  docker rm -f "$cid" >/dev/null 2>&1 || true
  if ((!ok)) || ! check_release "$tmp"; then
    rm -rf -- "$tmp"
    log "release from $ref refused"
    return 1
  fi
  # Root-owned, world-readable, nothing executable or setuid
  ((EUID != 0)) || chown -R 0:0 "$tmp"
  find "$tmp/srv" -type d -exec chmod 0755 {} +
  find "$tmp/srv" -type f -exec chmod 0644 {} +
  echo "$ref" >"$tmp/SOURCE"
  build_of "$ref" >"$tmp/BUILD"
  chmod 0644 "$tmp/Caddyfile" "$tmp/SOURCE" "$tmp/BUILD"
  touch "$tmp/.complete"
  chmod 0755 "$tmp"
  rm -rf -- "$rel"
  mv -T "$tmp" "$rel"
}

# ── Edge: Caddy ───────────────────────────────────────────────────────────
caddy_cid() { compose ps -q caddy 2>/dev/null || true; }

# adapt IMAGE ID — adapt + validate releases/ID/Caddyfile with IMAGE's Caddy
# in a throwaway container (no network, read-only, own memory limit: never a
# second Caddy inside the 96 MB Caddy container), with the real site values.
# Writes releases/ID/caddy.json, which reload posts to the admin API.
adapt() {
  local image="$1" rel="$EDGE_DIR/releases/$2" out
  out="$(mktemp "$EDGE_DIR/.staging/adapt.XXXXXX")"
  if ! docker run --rm --pull never --network none --read-only \
    --tmpfs /data:mode=1777 --tmpfs /config:mode=1777 --tmpfs /tmp:mode=1777 \
    --user 10002:10002 --cap-drop ALL --security-opt no-new-privileges:true --memory 128m \
    -e "SITE_HOST=$(get_var "$SITE_ENV" SITE_HOST)" -e "ACME_EMAIL=$(get_var "$SITE_ENV" ACME_EMAIL)" \
    -v "$EDGE_DIR:$EDGE_MOUNT:ro" --entrypoint caddy "$image" \
    adapt --config "$EDGE_MOUNT/releases/$2/Caddyfile" --adapter caddyfile --validate \
    >"$out" 2>"$out.err"; then
    log "Caddyfile of release $2 does not validate with $image: $(tail -n3 "$out.err" | tr '\n' ' ')"
    rm -f "$out" "$out.err"
    return 1
  fi
  rm -f "$out.err"
  chmod 0644 "$out"
  mv -f "$out" "$rel/caddy.json"
}

# reload ID — load releases/ID/caddy.json through the admin API inside the
# Caddy container (127.0.0.1:2019, busybox wget). Graceful: listeners are
# reused, open connections finish on the old config. On error Caddy keeps
# the old config.
reload() {
  local cid
  cid="$(caddy_cid)"
  [[ -n "$cid" ]] || { log "reload: no Caddy container"; return 1; }
  docker exec "$cid" wget -q -O /dev/null -T 30 \
    --header 'Content-Type: application/json' \
    --post-file "$EDGE_MOUNT/releases/$1/caddy.json" http://127.0.0.1:2019/load
}

# fetch PATH OUT → HTTP code of https://SITE_HOST/PATH straight from the Caddy
# container (compose IP: no DNAT, not subject to the governor's rules; -k: a
# local check of what is served, not of the certificate); 000 = no answer
fetch() {
  local host
  host="$(get_var "$SITE_ENV" SITE_HOST)"
  curl -sk --max-time 10 --resolve "$host:443:$CADDY_IP" -o "$2" -w '%{http_code}' \
    "https://$host$1" 2>/dev/null || true
}

# served ID → 0 Caddy serves ID's index.html and one of its assets; 1 it
# answers wrongly; 2 Caddy doesn't answer at all
served() {
  local srv="$EDGE_DIR/releases/$1/srv" out code asset
  out="$(mktemp)"
  code="$(fetch / "$out")"
  if [[ "$code" == 000 ]]; then rm -f "$out"; return 2; fi
  if [[ "$code" != 200 ]] || ! cmp -s "$out" "$srv/index.html"; then
    log "Caddy check: / answered $code$([[ "$code" != 200 ]] || echo ', not the new index.html')"
    rm -f "$out"
    return 1
  fi
  asset="$(grep -oE 'src="/assets/[^"?#]+' "$srv/index.html" | head -n1 | sed 's/^src="//' || true)"
  if [[ -n "$asset" ]]; then
    code="$(fetch "$asset" "$out")"
    if [[ "$code" != 200 ]]; then
      log "Caddy check: $asset answered $code"
      rm -f "$out"
      return 1
    fi
  fi
  rm -f "$out"
}

# caddy_healthy ID [admin-only] — after a (re)create: admin API up and, unless
# admin-only (first boot: no certificate yet), ID's index + an asset served
caddy_healthy() {
  local deadline=$((SECONDS + CADDY_HEALTH_TIMEOUT)) cid rc
  while :; do
    cid="$(caddy_cid)"
    if [[ -n "$cid" ]] && docker exec "$cid" wget -q -O /dev/null -T 5 http://127.0.0.1:2019/config/ >/dev/null 2>&1; then
      [[ "${2:-}" == admin-only ]] && return 0
      rc=0
      served "$1" || rc=$?
      ((rc == 0)) && return 0
    fi
    ((SECONDS < deadline)) || break
    sleep "$POLL"
  done
  log "Caddy not healthy after ${CADDY_HEALTH_TIMEOUT}s"
  return 1
}

# drain — before a Caddy recreate (which cuts every open connection): wait up
# to DRAIN_TIMEOUT for the app's open SSE streams to end
drain() {
  local deadline=$((SECONDS + DRAIN_TIMEOUT)) n
  while :; do
    n="$(curl -fsS --max-time 3 "$APP_STREAMS_URL" 2>/dev/null | jq -r '.active_streams // empty' 2>/dev/null || true)"
    if [[ ! "$n" =~ ^[0-9]+$ ]]; then
      log "drain: open-stream count unavailable; recreating Caddy now"
      return 0
    fi
    if ((n == 0)); then
      log "drain: no open streams"
      return 0
    fi
    if ((SECONDS >= deadline)); then
      log "drain: $n stream(s) still open after ${DRAIN_TIMEOUT}s; recreating Caddy anyway"
      return 0
    fi
    sleep "$POLL"
  done
}

# caddy_stale → Caddy is running but compose would recreate it (its config
# hash, image included, differs from the running container's)
caddy_stale() {
  local cid want have
  cid="$(caddy_cid)"
  [[ -n "$cid" ]] || return 1
  [[ "$(docker inspect -f '{{.State.Running}}' "$cid" 2>/dev/null)" == true ]] || return 1
  want="$(compose config --hash caddy 2>/dev/null | awk '$1 == "caddy" {print $2}')"
  have="$(docker inspect -f '{{ index .Config.Labels "com.docker.compose.config-hash" }}' "$cid" 2>/dev/null || true)"
  [[ -n "$want" && -n "$have" && "$want" != "$have" ]]
}

# recreate_caddy — drain, then let compose apply the current images.env and
# compose.yaml to Caddy
recreate_caddy() {
  drain
  compose up -d --no-deps caddy
}

# ensure_edge — every run, before anything else: the live Caddy image must
# have its release on disk (migration from the image-baked SPA, or a lost
# /var/lib/voyager/edge). Local only: the image is already pinned + verified.
ensure_edge() {
  [[ -n "$CADDY" ]] || return 0 # first deploy builds the edge
  edge_ok && return 0
  local src="${CONTENT:-$CADDY}" id
  log "edge: no current release; extracting it from $src"
  docker image inspect "$src" >/dev/null 2>&1 || docker pull -q "$src" >/dev/null
  id="$(release_id "$src")"
  extract_release "$src" "$id" || return 1
  switch_to "$id"
  CONTENT="$src"
  save_images
}

# refuse_edge NEW WHY — hold a Caddy digest whose content or runtime failed
refuse_edge() {
  hold "$1"
  notify "[voyager] Caddy deploy refused" "$1: $2. The previous release keeps running; the digest is held in $FAILED."
}

# deploy_edge NEW → 0 nothing to do or deployed; 1 refused/failed
deploy_edge() {
  local new="$1" id b cur_b new_rt cur_rt
  [[ "$new" != "$CONTENT" ]] || return 0
  if listed "$FAILED" "$new"; then
    log_once caddy-held "skipping Caddy $new: held (failed its checks, or rolled back from)"
    return 0
  fi
  if ((!ALLOW_DOWNGRADE)) && listed "$REFUSED" "$new"; then
    log_once caddy-refused "skipping Caddy $new: refused as a downgrade (use --allow-downgrade)"
    return 0
  fi
  verified "$new" || return 1
  log "pulling $new"
  docker pull -q "$new" >/dev/null
  b="$(build_of "$new")"
  cur_b="$(cat "$EDGE_DIR/current/BUILD" 2>/dev/null || true)"
  [[ -n "$cur_b" ]] || cur_b="$(build_of "$CONTENT")"
  if ((!ALLOW_DOWNGRADE)) && older "$b" "$cur_b"; then
    log "refusing Caddy $new: built before the live release (use --allow-downgrade)"
    echo "$new" >>"$REFUSED"
    drop_image "$new"
    return 0
  fi
  id="$(release_id "$new")"
  if ! extract_release "$new" "$id"; then
    refuse_edge "$new" "its SPA/Caddyfile failed the checks (see journalctl -u voyager-deploy)"
    drop_image "$new"
    return 1
  fi
  new_rt="$(runtime_of "$new")"
  cur_rt="$(runtime_of "$CADDY")"
  if [[ -n "$new_rt" && "$new_rt" == "$cur_rt" ]]; then
    deploy_content "$new" "$id"
  else
    deploy_runtime "$new" "$id"
  fi
}

# deploy_content NEW ID — same Caddy runtime: switch the SPA, reload the
# Caddyfile only if it changed. No restart, no dropped connection.
deploy_content() {
  local new="$1" id="$2" changed=0 old_id rc=0
  old_id="$(link current)"
  old_id="${old_id#releases/}"
  cmp -s "$EDGE_DIR/current/Caddyfile" "$EDGE_DIR/releases/$id/Caddyfile" || changed=1
  # Validated with the running runtime: the label says it's the same Caddy
  if ((changed)) && ! adapt "$CADDY" "$id"; then
    refuse_edge "$new" "its Caddyfile does not validate"
    prune
    drop_image "$new"
    return 1
  fi
  save_links
  switch_to "$id"
  if ((changed)); then
    if ! reload "$id"; then
      restore_links
      log "Caddyfile reload FAILED: Caddy keeps the old config; release switched back"
      refuse_edge "$new" "the admin API refused its Caddyfile (Caddy kept the old config)"
      prune
      drop_image "$new"
      return 1
    fi
    log "Caddyfile reloaded (graceful)"
  fi
  served "$id" || rc=$?
  if ((rc == 1)); then
    restore_links
    if ((changed)) && [[ -n "$old_id" ]]; then
      if ! { adapt "$CADDY" "$old_id" && reload "$old_id"; }; then
        log "could not reload the previous Caddyfile"
      fi
    fi
    refuse_edge "$new" "Caddy did not serve the new index.html and its assets"
    prune
    drop_image "$new"
    return 1
  fi
  ((rc == 0)) || log "Caddy did not answer the post-switch check (not running?); the converge step starts it"
  PREV_CONTENT="$CONTENT" CONTENT="$new"
  save_images
  log "SPA live: release $id from $new$( ((changed)) && echo ' (Caddyfile reloaded)')"
  prune
  drop_image "$PREV_CONTENT"
  drop_image "$new"
}

# deploy_runtime NEW ID — new Caddy runtime (or none known yet: migration):
# validate with the NEW image, drain, recreate, check, roll back on failure
deploy_runtime() {
  local new="$1" id="$2" o_caddy="$CADDY" o_prev="$PREV_CADDY" o_content="$CONTENT" o_prev_content="$PREV_CONTENT"
  if ! adapt "$new" "$id"; then
    refuse_edge "$new" "its Caddyfile does not validate with its own Caddy"
    prune
    drop_image "$new"
    return 1
  fi
  log "Caddy runtime changed ($(runtime_of "$CADDY" | cut -c1-12) → $(runtime_of "$new" | cut -c1-12)): recreating Caddy"
  save_links
  drain
  switch_to "$id"
  PREV_CADDY="$CADDY" CADDY="$new" PREV_CONTENT="$CONTENT" CONTENT="$new"
  save_images
  compose up -d --no-deps caddy
  if caddy_healthy "$id"; then
    log "Caddy healthy on the new runtime: release $id from $new"
    prune
    [[ -z "$o_prev" || "$o_prev" == "$o_caddy" ]] || docker image rm "$o_prev" >/dev/null 2>&1 || true
    drop_image "$o_content"
    return 0
  fi
  hold "$new"
  log "Caddy UNHEALTHY on $new: rolling back to $o_caddy"
  restore_links
  CADDY="$o_caddy" PREV_CADDY="$o_prev" CONTENT="$o_content" PREV_CONTENT="$o_prev_content"
  save_images
  compose up -d --no-deps caddy
  if caddy_healthy "${SAVED_LINKS[0]#releases/}"; then
    notify "[voyager] Caddy deploy rolled back" "New Caddy $new failed its checks; $o_caddy is running again."
  else
    notify "[voyager] Caddy deploy FAILED, rollback unhealthy" "Both $new and $o_caddy fail Caddy's checks. Check: docker compose logs caddy"
  fi
  prune
  return 1
}

# ── First deploy (fresh VM) ───────────────────────────────────────────────
first_deploy() {
  local new_app="$1" new_caddy="$2" id
  verified "$new_app" || return 1
  verified "$new_caddy" || return 1
  log "first deploy: pulling $new_app and $new_caddy"
  docker pull -q "$new_app" >/dev/null
  docker pull -q "$new_caddy" >/dev/null
  id="$(release_id "$new_caddy")"
  extract_release "$new_caddy" "$id" || die "first deploy: the Caddy image's SPA/Caddyfile failed the checks"
  switch_to "$id"
  APP="$new_app" CADDY="$new_caddy" CONTENT="$new_caddy"
  save_images
  log "deploying app=$APP caddy=$CADDY"
  compose up -d --remove-orphans
  if ! wait_healthy; then
    hold "$new_app"
    notify "[voyager] first deploy unhealthy" "$new_app is not healthy and there is nothing to roll back to."
    return 1
  fi
  # No certificate yet on a fresh VM: only the admin API is checked
  caddy_healthy "$id" admin-only ||
    notify "[voyager] first deploy: Caddy not answering" "Check: docker compose logs caddy"
  log "first deploy healthy"
}

# ── Rollbacks (operator) ──────────────────────────────────────────────────
rollback_app() {
  [[ -n "$PREV_APP" ]] || die "no previous app digest to roll back to"
  log "manual rollback: $APP → $PREV_APP (holding $APP)"
  # Hold the digest we left, or the timer would redeploy it within a minute
  # while `prod` still points at it
  hold "$APP"
  local cur="$APP"
  APP="$PREV_APP" PREV_APP="$cur"
  save_images
  compose up -d --no-deps app
  wait_healthy || die "rolled-back app is not healthy either"
}

rollback_edge() {
  local cur prev changed=0
  cur="$(link current)" prev="$(link prev1)"
  [[ -n "$prev" && -f "$EDGE_DIR/$prev/.complete" ]] || die "no previous SPA release to roll back to"
  cmp -s "$EDGE_DIR/$cur/Caddyfile" "$EDGE_DIR/$prev/Caddyfile" || changed=1
  if ((changed)); then
    adapt "$CADDY" "${prev#releases/}" || die "the previous release's Caddyfile does not validate with the running Caddy"
  fi
  log "manual SPA rollback: ${cur#releases/} → ${prev#releases/} (holding $CONTENT)"
  hold "$CONTENT"
  # Swap current and prev1: the release we leave stays as an asset fallback
  # for browsers that already loaded its index.html
  save_links
  relink prev1 "$cur"
  relink current "$prev"
  if ((changed)) && ! reload "${prev#releases/}"; then
    restore_links
    die "Caddy refused the previous Caddyfile; nothing changed"
  fi
  local left="$CONTENT"
  CONTENT="$(cat "$EDGE_DIR/$prev/SOURCE" 2>/dev/null || echo "$PREV_CONTENT")"
  PREV_CONTENT="$left"
  save_images
  log "SPA rolled back to release ${prev#releases/}$( ((changed)) && echo ' (Caddyfile reloaded)')"
}

rollback_caddy() {
  [[ -n "$PREV_CADDY" ]] || die "no previous Caddy runtime to roll back to"
  docker image inspect "$PREV_CADDY" >/dev/null 2>&1 || docker pull -q "$PREV_CADDY" >/dev/null
  local id
  id="$(link current)"
  id="${id#releases/}"
  adapt "$PREV_CADDY" "$id" ||
    die "the live Caddyfile does not validate with $PREV_CADDY: run --rollback-edge first"
  log "manual Caddy rollback: $CADDY → $PREV_CADDY (holding $CADDY)"
  hold "$CADDY"
  local cur="$CADDY"
  CADDY="$PREV_CADDY" PREV_CADDY="$cur"
  save_images
  recreate_caddy
  caddy_healthy "$id" || die "rolled-back Caddy is not healthy either"
}

# ── Converge ──────────────────────────────────────────────────────────────
# Bring back anything stopped (no-op when all is up) and apply a changed
# compose.yaml/app.env. Caddy first, drained, when compose would recreate it.
converge() {
  [[ -n "$APP" && -n "$CADDY" ]] || return 0
  if caddy_stale; then
    log "compose config of Caddy changed: draining, then recreating it"
    recreate_caddy || log "compose up caddy failed"
    caddy_healthy "$(link current | sed 's|^releases/||')" ||
      notify "[voyager] Caddy unhealthy after a config change" "Check: docker compose logs caddy"
  fi
  compose up -d --remove-orphans >/dev/null 2>&1 || log "compose up (converge) failed"
}

# ensure_unit — queue a start of voyager.service when it isn't active (the
# first deploy runs compose itself, and the unit's start is skipped while
# images.env is missing). Only an active unit gets its ExecStop (graceful
# stop + backup flush) at shutdown. --no-block: the unit's ExecStart waits
# for this script's lock, so waiting here would deadlock.
ensure_unit() {
  [[ -f "$IMAGES_ENV" ]] || return 0
  command -v systemctl >/dev/null || return 0
  systemctl is-active --quiet voyager.service && return 0
  systemctl start --no-block voyager.service 2>/dev/null ||
    log "could not queue a start of voyager.service"
}

notify() {
  # Same SMTP path as the governor (best effort)
  if [[ -x "$COMPOSE_DIR/governor.py" ]]; then
    "$COMPOSE_DIR/governor.py" mail --subject "$1" --body "$2" || true
  fi
}

ALLOW_DOWNGRADE=0
main() {
  local mode=deploy
  for arg in "$@"; do
    case "$arg" in
      --window) log "--window: no longer needed (Caddy deploys automatically); running a normal deploy" ;;
      --rollback) mode=rollback-app ;;
      --rollback-edge) mode=rollback-edge ;;
      --rollback-caddy) mode=rollback-caddy ;;
      --allow-downgrade) ALLOW_DOWNGRADE=1 ;;
      *) die "unknown argument: $arg" ;;
    esac
  done

  exec 9>"$LOCK"
  flock -n 9 || { log "another deploy is running"; exit 0; }
  install -d -m 0700 "$STATE_DIR"

  load_images
  ensure_edge || {
    notify "[voyager] edge release missing" "deploy.sh could not rebuild $EDGE_DIR/current from ${CONTENT:-$CADDY}; Caddy was left as it is."
    die "could not rebuild $EDGE_DIR/current; not touching Caddy"
  }

  case "$mode" in
    rollback-app) rollback_app; ensure_unit; exit 0 ;;
    rollback-edge) rollback_edge; exit 0 ;;
    rollback-caddy) rollback_caddy; ensure_unit; exit 0 ;;
  esac

  if backing_off; then
    log_once backoff "GHCR back-off until $(date -u -d "@$(cut -d' ' -f1 "$BACKOFF")" +%H:%M:%SZ 2>/dev/null || echo later): not polling"
    converge
    ensure_unit
    exit 0
  fi

  local app_digest caddy_digest
  if ! app_digest="$(resolve_digest "$APP_REPO")" || ! caddy_digest="$(resolve_digest "$CADDY_REPO")"; then
    converge
    ensure_unit
    exit 1
  fi
  rm -f "$BACKOFF"

  local new_app="$APP_REPO@$app_digest" new_caddy="$CADDY_REPO@$caddy_digest" rc=0
  if [[ -z "$APP" || -z "$CADDY" ]]; then
    first_deploy "$new_app" "$new_caddy" || rc=1
    ensure_unit
    exit "$rc"
  fi

  # App first (the new SPA may call new endpoints), then the edge
  local was="$APP $CADDY $CONTENT"
  if deploy_app "$new_app"; then
    deploy_edge "$new_caddy" || rc=1
  else
    rc=1
  fi
  converge
  # Something changed: drop dangling layers (old app/runtime images)
  [[ "$APP $CADDY $CONTENT" == "$was" ]] || docker image prune -f >/dev/null 2>&1 || true
  ensure_unit
  exit "$rc"
}

main "$@"
