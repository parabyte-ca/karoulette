#!/usr/bin/env bash
# KaraokeQueue update: pull latest code, rebuild (or pull image), restart. Data is preserved.
set -euo pipefail

PROJECT="karaokequeue"
cd "$(dirname "$0")"

say() { printf '\033[1;35m==>\033[0m %s\n' "$*"; }
die() { printf '\033[1;31mxx\033[0m %s\n' "$*" >&2; exit 1; }

[[ -f .env ]] || die "No .env found. Run ./setup.sh first."
get_env() { grep -E "^$1=" .env | tail -1 | cut -d= -f2- || true; }

OLD="$(cat VERSION 2>/dev/null || echo unknown)"
say "Pulling latest code"
git pull --ff-only
VERSION="$(cat VERSION 2>/dev/null || echo latest)"

IMAGE="$(get_env KQ_IMAGE)"; IMAGE="${IMAGE:-parabyte-ca/$PROJECT}"
if [[ "$IMAGE" == ghcr.io/* ]]; then
  say "Pulling $IMAGE"
  docker compose pull
else
  say "Building $IMAGE:$VERSION"
  docker build -t "$IMAGE:$VERSION" -t "$IMAGE:latest" .
fi

say "Restarting"
docker compose up -d --remove-orphans
docker image prune -f >/dev/null || true

PORT="$(get_env KQ_PORT)"; PORT="${PORT:-8095}"
for _ in $(seq 1 30); do
  if curl -fsS "http://127.0.0.1:${PORT}/api/health" >/dev/null 2>&1; then
    say "Updated KaraokeQueue ${OLD} -> ${VERSION}. The running event resumes where it left off."
    exit 0
  fi
  sleep 2
done
die "Not healthy after restart. Check: docker compose logs --tail 100"
