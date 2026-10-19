#!/usr/bin/env bash
# Host helper for upgrades started in Host admin > Updates. The app (a container) can't run update.sh,
# so it leaves request.json in the upgrade folder; this script, run every few minutes as root, picks it
# up, runs update.sh (backup, rebuild, health check, rollback on failure) and writes its progress and log
# back for the admin page. Same protocol as project-glasshaus.
#
#   scripts/upgrade-agent.sh              check for a request (what the schedule runs)
#   scripts/upgrade-agent.sh --install    run it every 15 minutes: a TrueNAS cron job (via midclt) on
#                                         TrueNAS SCALE, else /etc/cron.d, else a systemd timer
#   scripts/upgrade-agent.sh --print      only print what to schedule
#   scripts/upgrade-agent.sh --uninstall  remove the schedule
#   --every N                             minutes between runs (1, 2, 3, 4, 5, 6, 10, 12, 15, 20 or 30)
set -euo pipefail
# shellcheck source=scripts/lib.sh
source "$(dirname "$(readlink -f "$0")")/lib.sh"
cd "$ROOT_DIR"

now() { date -u +%Y-%m-%dT%H:%M:%SZ; }

DESCRIPTION="KaraokeQueue upgrade helper"
CRON_FILE=/etc/cron.d/karaokequeue-upgrade
SYSTEMD_TIMER=/etc/systemd/system/karaokequeue-upgrade.timer
SYSTEMD_SERVICE=/etc/systemd/system/karaokequeue-upgrade.service
EVERY=""

cron_spec() { if (( EVERY == 1 )); then printf '*'; else printf '*/%s' "$EVERY"; fi; }

print_schedule() {
  say "Schedule this command to run every $EVERY minute(s) as root:"
  printf '    %s --every %s\n' "$1" "$EVERY"
  printf '  cron line:  %s * * * * root %s --every %s >/dev/null 2>&1\n' "$(cron_spec)" "$1" "$EVERY"
  printf '  TrueNAS:    System > Advanced Settings > Cron Jobs > Add (run as root, schedule %s * * * *)\n' "$(cron_spec)"
}

truenas_job_ids() {
  midclt call cronjob.query "[[\"description\", \"=\", \"$DESCRIPTION\"]]" 2>/dev/null \
    | python3 -c 'import json,sys; print(" ".join(str(j["id"]) for j in json.load(sys.stdin)))' 2>/dev/null || true
}

install_schedule() {
  local self mode="$1" id payload
  EVERY="${EVERY:-15}"
  self="$(readlink -f "$0")"
  ensure_upgrade_dir
  if [[ "$mode" == print ]]; then
    print_schedule "$self"
    return 0
  elif command -v midclt >/dev/null 2>&1 && [[ "$(id -u)" == 0 ]]; then
    # TrueNAS SCALE resets /etc on upgrades, so register a real TrueNAS cron job instead.
    for id in $(truenas_job_ids); do midclt call cronjob.delete "$id" >/dev/null; done
    payload=$(printf '{"user": "root", "command": "%s --every %s", "description": "%s", "enabled": true, "stdout": false, "stderr": false, "schedule": {"minute": "%s", "hour": "*", "dom": "*", "month": "*", "dow": "*"}}' \
      "$self" "$EVERY" "$DESCRIPTION" "$(cron_spec)")
    midclt call cronjob.create "$payload" >/dev/null
    ok "added the TrueNAS cron job \"$DESCRIPTION\" (every $EVERY minute(s))"
  elif [[ -d /etc/cron.d && -w /etc/cron.d ]] && { command -v cron || command -v crond; } >/dev/null 2>&1; then
    printf '# %s (see %s)\n%s * * * * root %s --every %s >/dev/null 2>&1\n' \
      "$DESCRIPTION" "$self" "$(cron_spec)" "$self" "$EVERY" > "$CRON_FILE"
    chmod 0644 "$CRON_FILE"
    ok "installed $CRON_FILE (every $EVERY minute(s))"
  elif [[ -d /run/systemd/system && -w /etc/systemd/system ]] && command -v systemctl >/dev/null; then
    printf '[Unit]\nDescription=%s\n\n[Service]\nType=oneshot\nExecStart=%s --every %s\n' \
      "$DESCRIPTION" "$self" "$EVERY" > "$SYSTEMD_SERVICE"
    printf '[Unit]\nDescription=Run the %s every %s minute(s)\n\n[Timer]\nOnCalendar=*:0/%s\nAccuracySec=5s\n\n[Install]\nWantedBy=timers.target\n' \
      "$DESCRIPTION" "$EVERY" "$EVERY" > "$SYSTEMD_TIMER"
    systemctl daemon-reload
    systemctl enable --now karaokequeue-upgrade.timer >/dev/null
    ok "installed the karaokequeue-upgrade.timer systemd timer (every $EVERY minute(s))"
  else
    warn "no TrueNAS, cron (/etc/cron.d) or systemd found, or not running as root"
    print_schedule "$self"
    return 0
  fi
  "$self" --every "$EVERY"  # check in now so Admin > Updates shows the helper as connected
}

uninstall_schedule() {
  local removed=0 id
  if command -v midclt >/dev/null 2>&1; then
    for id in $(truenas_job_ids); do midclt call cronjob.delete "$id" >/dev/null && removed=1; done
  fi
  if [[ -f "$CRON_FILE" ]]; then rm -f -- "$CRON_FILE"; removed=1; fi
  if [[ -f "$SYSTEMD_TIMER" ]]; then
    systemctl disable --now karaokequeue-upgrade.timer >/dev/null 2>&1 || true
    rm -f -- "$SYSTEMD_TIMER" "$SYSTEMD_SERVICE"
    systemctl daemon-reload 2>/dev/null || true
    removed=1
  fi
  if [[ "$removed" == 1 ]]; then ok "removed the upgrade helper schedule"; else say "no schedule installed here"; fi
}

field() {  # field NAME FILE -> a string value from a flat JSON file, without needing jq
  sed -n "s/.*\"$1\"[[:space:]]*:[[:space:]]*\"\\([^\"]*\\)\".*/\\1/p" "$2" | head -1
}

write_json() {  # write_json FILE key value ... (values are validated or ours)
  local file="$1" tmp out="{" sep=""
  shift
  while (( $# )); do
    out+="$sep\"$1\": \"$2\""
    sep=", "
    shift 2
  done
  tmp="$(mktemp "$file.XXXXXX")"
  printf '%s}\n' "$out" > "$tmp"
  chmod 0644 "$tmp"
  mv -f "$tmp" "$file"
}

main() {
  local action=run
  while (( $# )); do
    case "$1" in
      --install) action=install ;;
      --print) action=print ;;
      --uninstall) action=uninstall ;;
      --every)
        EVERY="${2:-}"
        [[ "$EVERY" =~ ^(1|2|3|4|5|6|10|12|15|20|30)$ ]] || die "--every must be 1, 2, 3, 4, 5, 6, 10, 12, 15, 20 or 30 (minutes)"
        shift ;;
      *) die "unknown option: $1 (use --install, --print, --uninstall or --every N)" ;;
    esac
    shift
  done
  case "$action" in
    install | print) install_schedule "$action"; return ;;
    uninstall) uninstall_schedule; return ;;
  esac
  EVERY="${EVERY:-15}"
  [[ "$(id -u)" == 0 ]] || die "run as root (update.sh needs Docker)"
  [[ -f "$ENV_FILE" ]] || die ".env not found; run ./setup.sh first"
  local dir
  dir="$(upgrade_dir)"
  [[ -n "$dir" && "$dir" != "/" ]] || die "bad upgrade folder"
  ensure_upgrade_dir
  # The folder is shared with the app and this runs as root: never follow a link the app could have
  # planted. Lock the folder itself; create the log with noclobber.
  exec 9<"$dir"
  flock -n 9 || exit 0  # an upgrade is already running
  write_json "$dir/agent.json" last_seen "$(now)" every_minutes "$EVERY"

  [[ -f "$dir/request.json" ]] || return 0
  if [[ -L "$dir/request.json" ]]; then
    rm -f -- "$dir/request.json"
    warn "ignoring an upgrade request that was a link"
    return 0
  fi
  local id version from started
  id="$(field id "$dir/request.json")"
  version="$(field version "$dir/request.json")"
  rm -f -- "$dir/request.json"
  [[ "$id" =~ ^[0-9a-f-]{36}$ && "$version" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] || {
    warn "ignoring a malformed upgrade request"
    return 0
  }
  from="$(cat "$ROOT_DIR/VERSION" 2>/dev/null || echo unknown)"
  started="$(now)"
  write_json "$dir/status.json" id "$id" state running from_version "$from" to_version "$version" \
    started_at "$started"
  rm -f -- "$dir/upgrade.log"  # removes a planted link without following it
  (set -o noclobber; exec 8> "$dir/upgrade.log") 2>/dev/null || die "cannot create $dir/upgrade.log"
  exec 8>> "$dir/upgrade.log"
  chmod 0644 "$dir/upgrade.log" 2>/dev/null || true
  if "$ROOT_DIR/update.sh" >&8 2>&1; then
    write_json "$dir/status.json" id "$id" state succeeded from_version "$from" \
      to_version "$(cat "$ROOT_DIR/VERSION")" started_at "$started" finished_at "$(now)" \
      message "Upgraded to $(cat "$ROOT_DIR/VERSION")."
  else
    write_json "$dir/status.json" id "$id" state failed from_version "$from" to_version "$version" \
      started_at "$started" finished_at "$(now)" \
      message "The upgrade stopped; $(cat "$ROOT_DIR/VERSION") is running. See the log."
  fi
  write_json "$dir/agent.json" last_seen "$(now)" every_minutes "$EVERY"
}

main "$@"
