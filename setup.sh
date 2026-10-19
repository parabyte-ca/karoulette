#!/usr/bin/env bash
# Karoulette first-time install. Idempotent: safe to re-run.
# Usage: ./setup.sh                  (interactive)
#        HOST_PIN=1234 ./setup.sh -y  (non-interactive; values come from the environment or defaults)
set -euo pipefail
# shellcheck source=scripts/lib.sh
source "$(dirname "$(readlink -f "$0")")/scripts/lib.sh"
cd "$ROOT_DIR"

VERSION="$(cat VERSION 2>/dev/null || echo latest)"
NONINTERACTIVE=0
[[ "${1:-}" == "-y" || "${1:-}" == "--non-interactive" ]] && NONINTERACTIVE=1

command -v docker >/dev/null || die "Docker is not installed."
docker compose version >/dev/null 2>&1 || die "Docker Compose v2 ('docker compose') is required."

say "Setting up Karoulette v${VERSION}"
[[ -f .env ]] || { cp .env.example .env; say "Created .env from .env.example"; }
migrate_legacy_env

ask() {
  # ask KEY "Prompt" default [secret] -> environment value, else current .env value, else default
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
ask KQ_DATA_DIR "Data folder (TrueNAS: /mnt/<pool>/apps/karoulette)" "./data"
ask HOST_PIN "Host PIN or password (4+ characters)" "" secret
ask YOUTUBE_API_KEY "YouTube Data API v3 key (blank = backup search)" "" secret
ask PUBLIC_BASE_URL "Public site address for the QR code, e.g. https://karaoke.example.ca (blank = auto)" ""

PIN="$(get_env HOST_PIN)"
[[ ${#PIN} -ge 4 ]] || die "HOST_PIN must be at least 4 characters. Edit .env and re-run."
if [[ -z "$(get_env SECRET_KEY)" ]]; then
  set_env SECRET_KEY "$(head -c 48 /dev/urandom | base64 | tr -d '\n/+=' | cut -c1-48)"
  ok "generated SECRET_KEY"
fi
[[ -n "$(get_env KQ_UPGRADE_FOLDER)" ]] || set_env KQ_UPGRADE_FOLDER "./upgrade"
chmod 600 .env

DATA_DIR="$(abs_path "$(get_env KQ_DATA_DIR)")"
mkdir -p "$DATA_DIR"
if [[ "$(stat -c '%u' "$DATA_DIR")" != "$(puid)" ]]; then
  say "Setting owner of $DATA_DIR to $(puid):$(pgid)"
  chown "$(puid):$(pgid)" "$DATA_DIR" 2>/dev/null || sudo chown "$(puid):$(pgid)" "$DATA_DIR" \
    || warn "Couldn't chown $DATA_DIR. Make sure UID $(puid) can write to it."
fi
ensure_upgrade_dir

IMAGE="$(image)"
if [[ "$IMAGE" == ghcr.io/* ]]; then
  say "Pulling $IMAGE"
  docker compose pull
else
  say "Building $IMAGE:$VERSION"
  docker build -t "$IMAGE:$VERSION" -t "$IMAGE:latest" .
fi

say "Starting container"
docker compose up -d --remove-orphans

say "Waiting for Karoulette to report healthy…"
wait_healthy 60 || { warn "No health response yet. Check logs: docker compose logs -f"; exit 1; }
IP="$(hostname -I 2>/dev/null | awk '{print $1}')"
ok "Karoulette v${VERSION} is running."
echo "    TV / host screen: http://${IP:-localhost}:$(port)/host"
echo "    Guests join at:   http://${IP:-localhost}:$(port)/join"

# Upgrades from Host admin > Updates need the host helper on a schedule (root, every 15 minutes).
INSTALL_AGENT="${INSTALL_AGENT:-}"
if [[ -z "$INSTALL_AGENT" && $NONINTERACTIVE -eq 0 ]]; then
  read -r -p "Allow one-click upgrades from Host admin > Updates (installs a 15-minute root cron job)? [Y/n]: " INSTALL_AGENT
  INSTALL_AGENT="${INSTALL_AGENT:-y}"
fi
case "${INSTALL_AGENT,,}" in
  y|yes|1|true)
    if [[ "$(id -u)" == 0 ]]; then "$ROOT_DIR/scripts/upgrade-agent.sh" --install
    else sudo "$ROOT_DIR/scripts/upgrade-agent.sh" --install || warn "Run later: sudo ./scripts/upgrade-agent.sh --install"
    fi ;;
  *) say "Skipped. Enable later with: sudo ./scripts/upgrade-agent.sh --install" ;;
esac
