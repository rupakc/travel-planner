#!/usr/bin/env bash
# Promotes one image in the deploy workflow (jobs promote-app/promote-caddy,
# which run only after CI and that image's build job succeeded):
#   1. Still main's HEAD? `git ls-remote` must give a 40-hex SHA (else fail);
#      if main moved on, stop here: nothing is signed, `prod` doesn't move.
#   2. Built (BUILT=true): sign NEW_DIGEST with cosign keyless, verify it
#      exactly as the VM will (CERT_IDENTITY/CERT_ISSUER), then move
#      IMAGE:prod to it and check the tag resolves to exactly that digest.
#      Signing happens only here, so every image signed as
#      deploy.yml@refs/heads/main passed CI and was main's HEAD when signed.
#   3. Skipped (BUILT=false): nothing is signed (it was when it was built);
#      IMAGE:prod must still be PROD_DIGEST, the digest the build job
#      compared, or this fails.
#
# Env: NAME IMAGE BUILT NEW_DIGEST PROD_DIGEST REPO SHA CERT_IDENTITY
#      CERT_ISSUER; GITHUB_STEP_SUMMARY optional.
set -euo pipefail

: "${NAME:?}" "${IMAGE:?}" "${REPO:?}" "${SHA:?}" "${CERT_IDENTITY:?}" "${CERT_ISSUER:?}"
BUILT="${BUILT:-}" NEW_DIGEST="${NEW_DIGEST:-}" PROD_DIGEST="${PROD_DIGEST:-}"
summary="${GITHUB_STEP_SUMMARY:-/dev/null}"
is_digest() { [[ "$1" =~ ^sha256:[0-9a-f]{64}$ ]]; }
prod_digest() { docker buildx imagetools inspect "$IMAGE:prod" --format '{{json .Manifest}}' | jq -r .digest; }

[[ "$BUILT" == true || "$BUILT" == false ]] || { echo "::error::$NAME: build decision missing"; exit 1; }

head="$(git ls-remote "https://github.com/$REPO" refs/heads/main | cut -f1)"
[[ "$head" =~ ^[0-9a-f]{40}$ ]] || { echo "::error::could not read main's HEAD (got '$head')"; exit 1; }
if [[ "$head" != "$SHA" ]]; then
  echo "::notice::main moved on to $head; $NAME for $SHA is not signed and prod is not moved"
  echo "- $NAME: main moved on, not promoted" >>"$summary"
  exit 0
fi

if [[ "$BUILT" == false ]]; then
  is_digest "$PROD_DIGEST" || { echo "::error::$NAME: no prod digest from the build job"; exit 1; }
  got="$(prod_digest)"
  [[ "$got" == "$PROD_DIGEST" ]] || { echo "::error::$IMAGE:prod moved to $got while this run kept $PROD_DIGEST"; exit 1; }
  echo "- $NAME: \`$IMAGE@$PROD_DIGEST\` (unchanged, prod not moved)" >>"$summary"
  exit 0
fi

is_digest "$NEW_DIGEST" || { echo "::error::$NAME: no built digest"; exit 1; }
ref="$IMAGE@$NEW_DIGEST"
cosign sign --yes "$ref"
cosign verify --certificate-identity "$CERT_IDENTITY" --certificate-oidc-issuer "$CERT_ISSUER" "$ref" >/dev/null
docker buildx imagetools create --tag "$IMAGE:prod" "$ref"
got="$(prod_digest)"
[[ "$got" == "$NEW_DIGEST" ]] || { echo "::error::$IMAGE:prod is $got, expected $NEW_DIGEST"; exit 1; }
echo "- $NAME: \`$ref\` (new; the VM picks it up within about a minute)" >>"$summary"
