#!/usr/bin/env bash
# Karoulette safe update: pull code -> back up the database -> rebuild (or pull image) -> restart ->
# health check -> roll back to the previous image and code if it isn't healthy. Data is preserved.
#   ./update.sh            normal update (also what Host admin > Updates runs via scripts/upgrade-agent.sh)
#   ./update.sh --no-git   rebuild and restart the current checkout without pulling
set -euo pipefail
# shellcheck source=scripts/lib.sh
source "$(dirname "$(readlink -f "$0")")/scripts/lib.sh"
cd "$ROOT_DIR"

# Everything runs inside main so bash has read the whole file before `git pull` replaces it.
main() {

  use_git=1
  for arg in "$@"; do
    case "$arg" in
      --no-git) use_git=0 ;;
      *) die "unknown option: $arg (use --no-git)" ;;
    esac
  done

  [[ -f .env ]] || die "No .env found. Run ./setup.sh first."
  command -v docker >/dev/null || die "Docker is not installed."

  OLD_VERSION="$(cat VERSION 2>/dev/null || echo unknown)"
  OLD_REV="$(git_ rev-parse HEAD 2>/dev/null || echo "")"
  OLD_IMAGE="$(image)"

  if [[ "$use_git" == 1 ]]; then
    say "Pulling latest code"
    git_ pull --ff-only
  fi
  VERSION="$(cat VERSION 2>/dev/null || echo latest)"
  migrate_legacy_env
  IMAGE="$(image)"

  # 1. Back up the database from inside the running container (SQLite online backup; keeps the last 10).
  RUNNING="$(running_container || true)"
  if [[ -n "$RUNNING" ]]; then
    say "Backing up the database"
    docker exec -i "$RUNNING" python - "$OLD_VERSION" <<'PY' || warn "backup failed; continuing (the data folder is untouched)"
import sqlite3, sys, time
from pathlib import Path
backups = Path("/data/backups")
backups.mkdir(exist_ok=True)
dest = backups / f"pre-update-{sys.argv[1]}-{time.strftime('%Y%m%d-%H%M%S')}.db"
db = Path("/data/karoulette.db")
if not db.exists() and Path("/data/karaokequeue.db").exists():
    db = Path("/data/karaokequeue.db")  # still running a pre-0.5.0 version
src, out = sqlite3.connect(db), sqlite3.connect(dest)
src.backup(out)
out.close()
src.close()
for old in sorted(backups.glob("pre-update-*.db"))[:-10]:
    old.unlink()
print(f"backup: {dest}")
PY
  fi

  # 2. Keep the running image so we can go back to it.
  # (The running image may still carry the pre-rename name.)
  HAVE_ROLLBACK=0
  for candidate in "$IMAGE" "$OLD_IMAGE"; do
    if docker image inspect "$candidate:latest" >/dev/null 2>&1; then
      docker tag "$candidate:latest" "$IMAGE:rollback" && HAVE_ROLLBACK=1
      break
    fi
  done

  rollback() {
    warn "Karoulette $VERSION did not come up healthy; rolling back to $OLD_VERSION"
    if [[ "$HAVE_ROLLBACK" == 1 ]]; then
      docker tag "$IMAGE:rollback" "$IMAGE:latest"
      if [[ -n "$OLD_REV" && "$use_git" == 1 ]]; then git_ reset --hard "$OLD_REV" >/dev/null; fi
      docker compose up -d --remove-orphans
      if wait_healthy 90; then
        die "Update failed; rolled back to $OLD_VERSION, which is healthy. See: docker compose logs --tail 100"
      fi
    fi
    die "Update failed and the rollback isn't healthy. Check: docker compose logs --tail 100 (database backups are in the data folder under backups/)"
  }

  # 3. Build or pull.
  if [[ "$IMAGE" == ghcr.io/* ]]; then
    say "Pulling $IMAGE"
    docker compose pull || rollback
  else
    say "Building $IMAGE:$VERSION"
    docker build -t "$IMAGE:$VERSION" -t "$IMAGE:latest" . || rollback
  fi

  # 4. Restart and check.
  ensure_upgrade_dir
  say "Restarting"
  docker compose up -d --remove-orphans || rollback
  wait_healthy 90 || rollback
  docker image prune -f >/dev/null 2>&1 || true
  ok "Updated Karoulette $OLD_VERSION -> $VERSION. The running event resumes where it left off."
}

main "$@"
