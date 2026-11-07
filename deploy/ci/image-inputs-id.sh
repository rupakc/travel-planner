#!/usr/bin/env bash
# Prints an image's inputs id: a SHA-256 over everything a `docker build` of
# DOCKERFILE (context = the current directory, the repo root) can read:
#   - the Dockerfile itself and the context's .dockerignore,
#   - every file the Dockerfile's COPY instructions take from the context
#     (derived from the Dockerfile, not listed by hand: a new COPY is covered
#     automatically), by path, executable bit and content,
#   - EXTRA strings: the base images pinned by digest (the exact build args),
#     so a new base digest gives a new id.
# The deploy workflow stores it in the image label io.voyager.app-inputs or
# io.voyager.caddy-inputs and skips the build (and so the VM's restart) when
# the `prod` image already carries this id.
#
# Not covered (by design, documented in deploy.yml and the runbook): what a
# RUN step fetches at build time, e.g. pip resolving the version ranges in
# backend/requirements.txt. The weekly forced rebuild picks those up.
#
# Fail safe: anything it can't account for exactly exits non-zero, and the
# workflow then builds:
#   - ADD; a JSON-form or heredoc COPY; a variable in a COPY source; a source
#     matching no file;
#   - COPY --from= or RUN --mount from= naming anything but an earlier stage
#     (an image or a named build context);
#   - RUN --mount without type= (the default type is bind) or a bind mount
#     without from= (the build context).
# Over-counting is harmless (a needless rebuild); under-counting is not:
#   - .dockerignore is applied only for plain path entries (e.g.
#     backend/tests). Glob entries (**/*.pyc) are not applied: those files
#     are untracked and gitignored, so they are not in a CI checkout anyway.
#   - A `!` re-include of the form `!**/NAME` (NAME without glob characters)
#     keeps every file named NAME under an excluded path. Any other `!` entry
#     turns all exclusions off.
#   - A Dockerfile-specific DOCKERFILE.dockerignore turns all exclusions off.
#
# Files: tracked plus untracked-but-not-gitignored (git ls-files), contents
# from the working tree. Order- and mtime-independent.
#
# Usage: image-inputs-id.sh [--list] DOCKERFILE [EXTRA...]
#   --list  print what is hashed (one line per input) instead of the id
set -euo pipefail

die() { echo "image-inputs-id: $*" >&2; exit 2; }

list=0
if [[ "${1:-}" == --list ]]; then
  list=1
  shift
fi
dockerfile="${1:?usage: image-inputs-id.sh [--list] DOCKERFILE [EXTRA...]}"
shift
[[ -f "$dockerfile" ]] || die "no such Dockerfile: $dockerfile"
git rev-parse --is-inside-work-tree >/dev/null 2>&1 || die "not inside a git work tree"

sha256() { if command -v sha256sum >/dev/null; then sha256sum; else shasum -a 256; fi | cut -c1-64; }
digest() { if ((list)); then cat; else sha256; fi; }
lower() { printf '%s' "$1" | tr '[:upper:]' '[:lower:]'; }

# Instructions with line continuations joined, comments and blank lines dropped
instructions() {
  awk '
    /^[[:space:]]*#/ && cont == "" { next }
    {
      line = $0
      if (line ~ /\\[[:space:]]*$/) { sub(/\\[[:space:]]*$/, "", line); cont = cont line " "; next }
      print cont line; cont = ""
    }
    END { if (cont != "") print cont }
  ' "$1" | grep -Ev '^[[:space:]]*$' || true
}

stages=() # names (lower case) of the stages defined so far
nstages=0
# is_stage REF → REF names an earlier stage (by name or index)
is_stage() {
  local ref s
  ref="$(lower "$1")"
  if [[ "$ref" =~ ^[0-9]+$ ]]; then
    ((ref < nstages))
    return
  fi
  for s in "${stages[@]+"${stages[@]}"}"; do [[ "$s" == "$ref" ]] && return 0; done
  return 1
}

sources=()
while IFS= read -r ins; do
  read -r -a words <<<"$ins"
  op="$(printf '%s' "${words[0]}" | tr '[:lower:]' '[:upper:]')"
  case "$op" in
    FROM)
      # FROM [--platform=…] IMAGE [AS NAME]
      args=()
      for w in "${words[@]:1}"; do [[ "$w" == --* ]] || args+=("$w"); done
      if ((${#args[@]} >= 3)) && [[ "$(lower "${args[1]}")" == as ]]; then
        stages+=("$(lower "${args[2]}")")
      else
        stages+=("")
      fi
      nstages=$((nstages + 1))
      continue
      ;;
    ADD) die "ADD is not supported (use COPY): $ins" ;;
    RUN)
      for w in "${words[@]:1}"; do
        [[ "$w" == --* ]] || break
        [[ "$w" == --mount* ]] || continue
        [[ "$w" == --mount=* ]] || die "unsupported --mount syntax: $ins"
        type="" from=""
        IFS=, read -r -a opts <<<"${w#--mount=}"
        for o in "${opts[@]}"; do
          case "$o" in
            type=*) type="${o#type=}" ;;
            from=*) from="${o#from=}" ;;
          esac
        done
        [[ -n "$type" ]] || die "a --mount without type= is a bind mount of the context: $ins"
        if [[ "$type" == bind && -z "$from" ]]; then
          die "a bind mount of the build context is not supported: $ins"
        fi
        if [[ -n "$from" ]] && ! is_stage "$from"; then
          die "--mount from= must name an earlier stage, not '$from': $ins"
        fi
      done
      continue
      ;;
    COPY) ;;
    *) continue ;;
  esac
  args=()
  from=""
  for w in "${words[@]:1}"; do
    case "$w" in
      --from=*) from="${w#--from=}" ;;
      --*) ;;
      *) args+=("$w") ;;
    esac
  done
  if [[ -n "$from" ]]; then
    is_stage "$from" || die "COPY --from= must name an earlier stage, not '$from': $ins"
    continue
  fi
  ((${#args[@]} >= 2)) || die "COPY without a source: $ins"
  for src in "${args[@]:0:${#args[@]}-1}"; do
    case "$src" in
      \[* | *\] | \<\<*) die "JSON-form or heredoc COPY is not supported: $ins" ;;
      *\$*) die "a variable in a COPY source is not supported: $ins" ;;
    esac
    src="${src#./}"
    [[ -n "$src" ]] || src=.
    sources+=("$src")
  done
done < <(instructions "$dockerfile")
((${#sources[@]})) || die "no COPY from the build context in $dockerfile"

# .dockerignore (see the header for what is applied)
ignore_file=.dockerignore
excludes=()
keep_names=()
if [[ -f "$dockerfile.dockerignore" ]]; then
  ignore_file="$dockerfile.dockerignore"
elif [[ -f .dockerignore ]]; then
  all_off=0
  while IFS= read -r line || [[ -n "$line" ]]; do
    line="${line%%#*}"
    line="$(printf '%s' "$line" | sed 's/^[[:space:]]*//; s/[[:space:]]*$//')"
    [[ -n "$line" ]] || continue
    if [[ "$line" == '!'* ]]; then
      name="${line#!}"
      name="${name#\*\*/}"
      if [[ "$line" == '!**/'* && -n "$name" && "$name" != *[/\*\?\[\]\\]* ]]; then
        keep_names+=("$name")
      else
        all_off=1
      fi
      continue
    fi
    line="${line#/}"
    line="${line%/}"
    [[ "$line" == *[\*\?\[\]\\]* || "$line" == *..* || "$line" == . ]] && continue
    excludes+=("$line")
  done <.dockerignore
  if ((all_off)); then
    excludes=()
    keep_names=()
  fi
fi

excluded() {
  local f="$1" e n base="${1##*/}"
  for e in "${excludes[@]+"${excludes[@]}"}"; do
    if [[ "$f" == "$e" || "$f" == "$e"/* ]]; then
      for n in "${keep_names[@]+"${keep_names[@]}"}"; do
        [[ "$base" == "$n" ]] && return 1
      done
      return 0
    fi
  done
  return 1
}

for src in "${sources[@]}"; do
  [[ -n "$(git ls-files --cached --others --exclude-standard -- "$src" | head -n1)" ]] ||
    die "COPY source matches no file: $src"
done

{
  echo "image-inputs v1"
  for x in "$@"; do printf 'extra %s\n' "$x"; done
  printf 'dockerfile %s\n' "$(sha256 <"$dockerfile")"
  if [[ -f "$ignore_file" ]]; then printf 'ignore %s\n' "$(sha256 <"$ignore_file")"; fi
  git ls-files -z --cached --others --exclude-standard -- "${sources[@]}" |
    tr '\0' '\n' | LC_ALL=C sort -u |
    while IFS= read -r f; do
      excluded "$f" && continue
      if [[ -L "$f" ]]; then
        printf 'link %s %s\n' "$f" "$(readlink "$f")"
      elif [[ -f "$f" ]]; then
        mode=644
        [[ -x "$f" ]] && mode=755
        printf 'file %s %s %s\n' "$mode" "$(sha256 <"$f")" "$f"
      fi # else: deleted from the working tree, not in the context
    done
} | digest
