#!/usr/bin/env bash
# The one Trivy policy for the images that ship (deploy build jobs, PR CI,
# the daily scan of :prod): unfixed findings ignored, any fixed CRITICAL
# fails; .trivyignore (repo root) lists accepted ones with a reason.
# Installs the pinned Trivy release, checked against its sha256 (the deploy
# build jobs can push images), unless that version is already on PATH.
#
# Usage: trivy-scan.sh REF...   (TRIVY_IMAGE_SRC: remote (default) | docker)
set -euo pipefail

TRIVY_VERSION=0.70.0
TRIVY_SHA256=8b4376d5d6befe5c24d503f10ff136d9e0c49f9127a4279fd110b727929a5aa9
(($#)) || { echo "usage: trivy-scan.sh REF..." >&2; exit 2; }

if ! trivy --version 2>/dev/null | grep -q "Version: $TRIVY_VERSION\$"; then
  dir="${RUNNER_TEMP:-${TMPDIR:-/tmp}}/trivy-$TRIVY_VERSION"
  mkdir -p "$dir"
  if [[ ! -x "$dir/trivy" ]]; then
    wget -qO "$dir/trivy.tar.gz" \
      "https://github.com/aquasecurity/trivy/releases/download/v${TRIVY_VERSION}/trivy_${TRIVY_VERSION}_Linux-64bit.tar.gz"
    echo "$TRIVY_SHA256  $dir/trivy.tar.gz" | sha256sum -c - >/dev/null
    tar -xzf "$dir/trivy.tar.gz" -C "$dir" trivy
    rm -f "$dir/trivy.tar.gz"
  fi
  PATH="$dir:$PATH"
fi
trivy --version | head -n1

rc=0
for ref in "$@"; do
  echo "::group::trivy $ref"
  one=0
  trivy image --image-src "${TRIVY_IMAGE_SRC:-remote}" --exit-code 1 --severity CRITICAL \
    --ignore-unfixed --no-progress "$ref" || one=1
  echo "::endgroup::"
  if ((one)); then
    rc=1
    echo "::error::$ref has fixed CRITICAL vulnerabilities (or the scan failed; Trivy $TRIVY_VERSION)"
  fi
done
exit "$rc"
