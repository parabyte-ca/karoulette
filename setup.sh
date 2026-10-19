#!/usr/bin/env bash
# KaraokeQueue first-time install. Idempotent: safe to re-run.
# Usage: ./setup.sh                 (interactive)
#        HOST_PIN=1234 ./setup.sh -y (non-interactive; values come from env or defaults)
set -euo pipefail

PROJECT="karaokequeue"
cd "$(dirname "$0")"
VERSION="$(cat VERSION 2>/dev/null || echo latest)"
NONINTERACTIVE=0
[[ "${1:-}" == "-y" || "${1:-}" == "--non-interactive" ]] && NONINTERACTIVE=1

say()  { printf '\033[1;35m==>\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m!!\033[0m %s\n' "$*"; }
die()  { printf '\033[1;31mxx\033[0m %s\n' "$*" >&2; exit 1; }

command -v docker >/dev/null || die "Docker is not installed."
docker compose version >/dev/null 2>&1 || die "Docker Compose v2 ('docker compose') is required."

say "Setting up KaraokeQueue v${VERSION}"

[[ -f .env ]] || { cp .env.example .env; say "Created .env from .env.example"; }

get_env() { grep -E "^$1=" .env | tail -1 | cut -d= -f2- || true; }
set_env() {
  local key="$1" value="$2"
  if grep -qE "^${key}=" .env; then
    # Use a delimiter unlikely to appear in values.
    sed -i.bak "s|^${key}=.*|${key}=${value//|/\\|}|" .env && rm -f .env.bak
  else
    echo "${key}=${value}" >> .env
  fi
}
ask() {
  # ask KEY "Prompt" default [secret]
  local key="$1" prompt="$2" default="$3" secret="${4:-}" current value
  current="${!key:-$(get_env "$key")}"
  [[ -n "$current" ]] && default="$current"
  if [[ $NONINTERACTIVE -eq 1 ]]; then
    value="$default"
  elif [[ -n "$secret" ]]; then
    read -r -s -p "$prompt [${default:+keep current}]: " value; echo
    value="${value:-$default}"
  else
    read -r -p "$prompt [$default]: " value
    value="${value:-$default}"
  fi
  set_env "$key" "$value"
}

ask KQ_PORT "Host port" "8095"
ask KQ_DATA_DIR "Data folder (TrueNAS: /mnt/<pool>/apps/karaokequeue)" "./data"
ask HOST_PIN "Host PIN or password (4+ characters)" "" secret
ask YOUTUBE_API_KEY "YouTube Data API v3 key (blank = backup search)" "" secret
ask PUBLIC_BASE_URL "Public URL for the QR code (blank = auto)" ""

PIN="$(get_env HOST_PIN)"
[[ ${#PIN} -ge 4 ]] || die "HOST_PIN must be at least 4 characters. Edit .env and re-run."
if [[ -z "$(get_env SECRET_KEY)" ]]; then
  set_env SECRET_KEY "$(head -c 48 /dev/urandom | base64 | tr -d '\n/+=' | cut -c1-48)"
  say "Generated SECRET_KEY"
fi
chmod 600 .env

DATA_DIR="$(get_env KQ_DATA_DIR)"
PUID="$(get_env PUID)"; PUID="${PUID:-568}"
PGID="$(get_env PGID)"; PGID="${PGID:-568}"
mkdir -p "$DATA_DIR"
if [[ "$(stat -c '%u' "$DATA_DIR")" != "$PUID" ]]; then
  say "Setting owner of $DATA_DIR to $PUID:$PGID"
  chown "$PUID:$PGID" "$DATA_DIR" 2>/dev/null || sudo chown "$PUID:$PGID" "$DATA_DIR" \
    || warn "Couldn't chown $DATA_DIR. Make sure UID $PUID can write to it."
fi

IMAGE="$(get_env KQ_IMAGE)"; IMAGE="${IMAGE:-parabyte-ca/$PROJECT}"
if [[ "$IMAGE" == ghcr.io/* ]]; then
  say "Pulling $IMAGE"
  docker compose pull
else
  say "Building $IMAGE:$VERSION"
  docker build -t "$IMAGE:$VERSION" -t "$IMAGE:latest" .
fi

say "Starting container"
docker compose up -d --remove-orphans

PORT="$(get_env KQ_PORT)"
say "Waiting for KaraokeQueue to report healthy…"
for _ in $(seq 1 30); do
  if curl -fsS "http://127.0.0.1:${PORT}/api/health" >/dev/null 2>&1; then
    IP="$(hostname -I 2>/dev/null | awk '{print $1}')"
    say "KaraokeQueue v${VERSION} is running."
    echo "    TV / host screen: http://${IP:-localhost}:${PORT}/host"
    echo "    Guests join at:   http://${IP:-localhost}:${PORT}/join"
    exit 0
  fi
  sleep 2
done
warn "No health response yet. Check logs: docker compose logs -f"
exit 1
