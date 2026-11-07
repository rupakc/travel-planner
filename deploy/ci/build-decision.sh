#!/usr/bin/env bash
# Decides whether and how the deploy workflow builds an image. Writes to
# $GITHUB_OUTPUT (stdout when unset):
#   build=false prod=<digest>
#       the image `prod` points at already carries io.voyager.NAME-inputs=WANT
#       and was refreshed (built without cache) less than MAX_AGE ago: skip
#       the build, leave `prod` where it is;
#   build=true fresh=true fresh_at=<now>
#       a refresh: FORCE=true (the weekly schedule, a dispatch), or `prod`'s
#       io.voyager.fresh-at is missing, unreadable or older than MAX_AGE.
#       The workflow builds without cache, so pip re-resolves its version
#       ranges and every layer is rebuilt on the newest pinned bases;
#   build=true fresh=false fresh_at=<prod's fresh-at>
#       inputs changed: a normal (cached) build that carries the last
#       refresh time forward.
# The fresh-at check makes the weekly refresh robust: if the scheduled run is
# dropped (a queued push replaces it in the concurrency group) or GitHub has
# disabled the schedule, the next push still refreshes.
# Fail safe: an empty WANT (the id couldn't be computed), a `prod` tag that
# can't be resolved, a config that can't be read as a single-platform image
# all mean build (and, having no readable fresh-at, a refresh).
#
# Usage: build-decision.sh NAME IMAGE WANT [FORCE]
#   NAME  app | caddy (labels io.voyager.NAME-inputs, io.voyager.fresh-at)
# Env: MAX_AGE seconds (default 604800 = 7 days), NOW (default: date +%s)
set -euo pipefail

name="${1:?usage: build-decision.sh NAME IMAGE WANT [FORCE]}"
image="${2:?usage: build-decision.sh NAME IMAGE WANT [FORCE]}"
want="${3-}"
force="${4:-false}"
max_age="${MAX_AGE:-604800}"
now="${NOW:-$(date +%s)}"
[[ "$name" =~ ^[a-z]+$ ]] || { echo "build-decision: bad NAME: $name" >&2; exit 2; }
[[ "$now" =~ ^[0-9]+$ && "$max_age" =~ ^[0-9]+$ ]] || { echo "build-decision: bad NOW/MAX_AGE" >&2; exit 2; }
out="${GITHUB_OUTPUT:-/dev/stdout}"

refresh() {
  echo "$name: $1: building without cache (refresh)"
  printf 'build=true\nfresh=true\nfresh_at=%s\n' "$now" >>"$out"
  exit 0
}

[[ "$force" != true ]] || refresh "forced"
digest="$(docker buildx imagetools inspect "$image:prod" --format '{{json .Manifest}}' 2>/dev/null |
  jq -r '.digest // empty' 2>/dev/null)" || digest=""
[[ "$digest" =~ ^sha256:[0-9a-f]{64}$ ]] || refresh "no readable $image:prod"
labels="$(docker buildx imagetools inspect "$image@$digest" --format '{{json .Image}}' 2>/dev/null |
  jq -c 'if type == "object" and has("config") then (.config.Labels // {}) else {} end' 2>/dev/null)" || labels="{}"
label() { jq -r --arg k "$1" '.[$k] // ""' <<<"$labels"; }
have="$(label "io.voyager.$name-inputs")"
fresh_at="$(label io.voyager.fresh-at)"
[[ "$fresh_at" =~ ^[0-9]+$ ]] || refresh "prod has no readable io.voyager.fresh-at"
((now - fresh_at <= max_age)) || refresh "last refresh $(((now - fresh_at) / 3600)) h ago"

if [[ -z "$want" || "$have" != "$want" ]]; then
  echo "$name: inputs ${want:-unknown}, prod has ${have:-none}: building"
  printf 'build=true\nfresh=false\nfresh_at=%s\n' "$fresh_at" >>"$out"
  exit 0
fi
echo "::notice::$name unchanged (inputs $want): prod stays $image@$digest, nothing built"
printf 'build=false\nprod=%s\n' "$digest" >>"$out"
