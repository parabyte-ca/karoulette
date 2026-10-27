#!/usr/bin/env bash
# Shared helpers for setup.sh, update.sh and scripts/*. Source, don't execute.
# shellcheck disable=SC2034

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="${ROOT_DIR}/.env"
PROJECT="karoulette"
CONTAINER="karoulette"
# Names used before the rename from KaraokeQueue (v0.5.0); kept so updates migrate old installs.
LEGACY_CONTAINER="karaokequeue"
LEGACY_IMAGE="parabyte-ca/karaokequeue"

# Colour only on a terminal, so the upgrade log shown in Host admin stays plain text.
if [[ -t 1 ]]; then C_SAY=$'\e[1;35m'; C_OK=$'\e[1;32m'; C_WARN=$'\e[1;33m'; C_ERR=$'\e[1;31m'; C_END=$'\e[0m'
else C_SAY=; C_OK=; C_WARN=; C_ERR=; C_END=; fi
say()  { printf '%s==>%s %s\n' "$C_SAY" "$C_END" "$*"; }
ok()   { printf '%s ok%s %s\n' "$C_OK" "$C_END" "$*"; }
warn() { printf '%s!!%s %s\n' "$C_WARN" "$C_END" "$*" >&2; }
die()  { printf '%sxx%s %s\n' "$C_ERR" "$C_END" "$*" >&2; exit 1; }

# get_env KEY -> value from .env (empty if missing)
get_env() {
  [[ -f "$ENV_FILE" ]] || return 0
  awk -F= -v k="$1" '$1 == k { sub(/^[^=]*=/, ""); v = $0 } END { print v }' "$ENV_FILE"
}

# set_env KEY VALUE -> replace or append in .env
set_env() {
  local key="$1" value="$2" tmp
  tmp="$(mktemp "${ENV_FILE}.XXXXXX")"
  awk -F= -v k="$key" -v v="$value" '
    $1 == k { print k "=" v; found = 1; next } { print }
    END { if (!found) print k "=" v }' "$ENV_FILE" > "$tmp"
  chmod 600 "$tmp"
  mv "$tmp" "$ENV_FILE"
}

# abs_path PATH -> absolute path; relative paths are resolved against the repo
abs_path() { case "$1" in /*) printf '%s' "$1" ;; *) printf '%s/%s' "$ROOT_DIR" "${1#./}" ;; esac; }

image() { local i; i="$(get_env KQ_IMAGE)"; printf '%s' "${i:-parabyte-ca/$PROJECT}"; }

# running_container -> name of the app container that is up now (new or pre-rename name)
running_container() {
  docker ps --format '{{.Names}}' | grep -xE "$CONTAINER|$LEGACY_CONTAINER" | head -1
}

# migrate_legacy_env -> point an old KQ_IMAGE (parabyte-ca/karaokequeue) at the renamed image
migrate_legacy_env() {
  local img
  img="$(get_env KQ_IMAGE)"
  case "$img" in
    "$LEGACY_IMAGE") set_env KQ_IMAGE "parabyte-ca/$PROJECT"; ok "KQ_IMAGE renamed to parabyte-ca/$PROJECT" ;;
    "ghcr.io/parabyte-ca/karaokequeue") set_env KQ_IMAGE "ghcr.io/parabyte-ca/$PROJECT"; ok "KQ_IMAGE renamed to ghcr.io/parabyte-ca/$PROJECT" ;;
  esac
  # 1.0 enforces the Content-Security-Policy; a .env from 0.16 still says report. Say so, but leave the choice.
  [[ "$(get_env CSP_MODE)" == "report" ]] && \
    warn "CSP_MODE=report in .env: 1.0 enforces it by default. Set CSP_MODE=enforce once the TV's browser console is clean."
  return 0
}
port() { local p; p="$(get_env KQ_PORT)"; printf '%s' "${p:-8095}"; }
puid() { local u; u="$(get_env PUID)"; printf '%s' "${u:-568}"; }
pgid() { local g; g="$(get_env PGID)"; printf '%s' "${g:-568}"; }
upgrade_dir() { local d; d="$(get_env KQ_UPGRADE_FOLDER)"; abs_path "${d:-./upgrade}"; }

# git as root in a checkout owned by another user needs safe.directory.
git_() { git -c safe.directory="$ROOT_DIR" -C "$ROOT_DIR" "$@"; }

# wait_healthy SECONDS -> 0 once /api/health answers
wait_healthy() {
  local deadline=$((SECONDS + ${1:-60}))
  while (( SECONDS < deadline )); do
    curl -fsS "http://127.0.0.1:$(port)/api/health" >/dev/null 2>&1 && return 0
    sleep 2
  done
  return 1
}

# ensure_upgrade_dir -> the folder shared with the app for Admin > Updates, owned by the app user
ensure_upgrade_dir() {
  local dir
  dir="$(upgrade_dir)"
  mkdir -p "$dir"
  chown "$(puid):$(pgid)" "$dir" 2>/dev/null || sudo chown "$(puid):$(pgid)" "$dir" 2>/dev/null \
    || warn "couldn't chown $dir; make sure UID $(puid) can write to it"
  chmod 0755 "$dir" 2>/dev/null || true
}
