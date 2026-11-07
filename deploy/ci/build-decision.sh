#!/usr/bin/env bash
# Decides whether the deploy workflow builds an image. Writes to
# $GITHUB_OUTPUT (stdout when unset):
#   build=false + prod=<digest>   the image `prod` points at already carries
#                                 io.voyager.NAME-inputs=WANT: skip the build,
#                                 leave `prod` where it is;
#   build=true                    anything else.
# Fail safe: FORCE=true, an empty WANT (the id couldn't be computed), a `prod`
# tag that can't be resolved, a config without the label or not readable as
# a single-platform image all mean build. Messages go to stdout.
#
# Usage: build-decision.sh NAME IMAGE WANT [FORCE]
#   NAME  app | caddy (the label is io.voyager.NAME-inputs)
set -euo pipefail

name="${1:?usage: build-decision.sh NAME IMAGE WANT [FORCE]}"
image="${2:?usage: build-decision.sh NAME IMAGE WANT [FORCE]}"
want="${3-}"
force="${4:-false}"
[[ "$name" =~ ^[a-z]+$ ]] || { echo "build-decision: bad NAME: $name" >&2; exit 2; }

out="${GITHUB_OUTPUT:-/dev/stdout}"
build() {
  echo "$name: $1: building"
  echo "build=true" >>"$out"
  exit 0
}

[[ "$force" != true ]] || build "forced rebuild"
[[ -n "$want" ]] || build "inputs id unknown"
digest="$(docker buildx imagetools inspect "$image:prod" --format '{{json .Manifest}}' 2>/dev/null |
  jq -r '.digest // empty' 2>/dev/null)" || digest=""
[[ "$digest" =~ ^sha256:[0-9a-f]{64}$ ]] || build "no readable $image:prod"
have="$(docker buildx imagetools inspect "$image@$digest" --format '{{json .Image}}' 2>/dev/null |
  jq -r --arg k "io.voyager.$name-inputs" \
    'if type == "object" and has("config") then (.config.Labels[$k] // "") else "" end' 2>/dev/null)" || have=""
[[ "$have" == "$want" ]] || build "inputs $want, prod has ${have:-none}"

echo "::notice::$name unchanged (inputs $want): prod stays $image@$digest, nothing built"
printf 'build=false\nprod=%s\n' "$digest" >>"$out"
