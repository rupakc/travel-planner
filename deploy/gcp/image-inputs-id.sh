#!/usr/bin/env bash
# Prints an image's inputs id: a SHA-256 over everything a `docker build` of
# DOCKERFILE (context = the current directory, the repo root) can read:
#   - the Dockerfile itself and the context's .dockerignore,
#   - every file the Dockerfile's COPY instructions take from the context
#     (derived from the Dockerfile, not listed by hand: a new COPY is covered
#     automatically), by path, executable bit and content,
#   - EXTRA strings, e.g. the base image pinned by digest (the exact build
#     arg), so a new base digest gives a new id.
# The deploy workflow stores it in the label io.voyager.inputs and skips the
# build (and so the VM's restart) when the `prod` image already has this id.
#
# Fail safe: anything it can't account for exactly (ADD, a JSON-form or
# heredoc COPY, a variable in a COPY source, a bind mount of the context, a
# source matching no file) exits non-zero, and the workflow then builds.
# Over-counting is harmless (a needless rebuild); under-counting is not, so
# .dockerignore is only applied for plain directory entries (e.g.
# backend/tests), and files under them whose name a `!` entry could re-include
# still count. Glob entries (**/*.pyc) are not applied: those files are
# untracked and gitignored, so they are not in a CI checkout anyway.
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

sources=()
while IFS= read -r ins; do
  read -r -a words <<<"$ins"
  op="$(printf '%s' "${words[0]}" | tr '[:lower:]' '[:upper:]')"
  case "$op" in
    ADD) die "ADD is not supported (use COPY): $ins" ;;
    RUN)
      for w in "${words[@]:1}"; do
        if [[ "$w" == --mount=* && "$w" == *type=bind* && "$w" != *from=* ]]; then
          die "a bind mount of the build context is not supported: $ins"
        fi
      done
      continue
      ;;
    COPY) ;;
    *) continue ;;
  esac
  args=()
  stage=0
  for w in "${words[@]:1}"; do
    case "$w" in
      --from=*) stage=1 ;;
      --*) ;;
      *) args+=("$w") ;;
    esac
  done
  ((stage)) && continue
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

# .dockerignore: plain directory/file entries only (see the header). With a
# Dockerfile-specific ignore file BuildKit ignores the root one: then apply
# nothing (over-counting is safe) but still hash the file.
ignore_file=.dockerignore
excludes=()
keep_names=()
if [[ -f "$dockerfile.dockerignore" ]]; then
  ignore_file="$dockerfile.dockerignore"
elif [[ -f .dockerignore ]]; then
  while IFS= read -r line || [[ -n "$line" ]]; do
    line="${line%%#*}"
    line="$(printf '%s' "$line" | sed 's/^[[:space:]]*//; s/[[:space:]]*$//')"
    [[ -n "$line" ]] || continue
    if [[ "$line" == '!'* ]]; then
      keep_names+=("${line##*/}")
      continue
    fi
    line="${line#/}"
    line="${line%/}"
    [[ "$line" == *[\*\?\[\]\\]* || "$line" == *..* || "$line" == . ]] && continue
    excludes+=("$line")
  done <.dockerignore
fi

excluded() {
  local f="$1" e n base="${1##*/}"
  for e in "${excludes[@]+"${excludes[@]}"}"; do
    if [[ "$f" == "$e" || "$f" == "$e"/* ]]; then
      for n in "${keep_names[@]+"${keep_names[@]}"}"; do
        # shellcheck disable=SC2053  # n is a glob on purpose
        [[ "$base" == $n ]] && return 1
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
