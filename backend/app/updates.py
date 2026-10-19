"""New releases: a daily check, and upgrades the host starts from Host admin → Updates.

Once a day the app asks GitHub for the latest release of this project (only the version and its notes
come back; nothing about this server is sent). The result is kept in the settings table.

The app runs in a container and can't run ``update.sh`` itself. "Upgrade" writes ``request.json`` into
the upgrade folder, which is shared with the host. ``scripts/upgrade-agent.sh``, run every few minutes
by cron on the host, picks it up, runs ``update.sh`` (database backup, rebuild, health check, rollback on
failure) and writes ``status.json`` and ``upgrade.log`` back for the admin page. Same protocol as
project-glasshaus.
"""
from __future__ import annotations

import json
import logging
import os
import re
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import httpx

from .db import Database

log = logging.getLogger("karoulette.updates")

SEMVER = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)$")
SETTING_KEY = "updates_latest"
CHECK_EVERY = timedelta(days=1)
RECHECK_AFTER = timedelta(seconds=60)
CLOCK_SKEW = timedelta(minutes=1)
AGENT_STALE = timedelta(minutes=3)
STALE_REQUEST = timedelta(hours=1)
STALE_RUNNING = timedelta(hours=1)
MAX_NOTES = 20_000
MAX_LOG = 64 * 1024


class UpdateError(Exception):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.message = message
        self.status = status


def _key(version: str) -> tuple[int, int, int]:
    m = SEMVER.match((version or "").strip())
    return (int(m[1]), int(m[2]), int(m[3])) if m else (0, 0, 0)


def newer(candidate: str, current: str) -> bool:
    return _key(candidate) > _key(current)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _when(value: Any) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _text(value: object, limit: int = 320) -> str | None:
    return value[:limit] if isinstance(value, str) and value else None


def _read_json(path: Path) -> dict | None:
    try:
        if path.is_symlink() or path.stat().st_size > 64 * 1024:
            return None
        data = json.loads(path.read_text())
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def changelog_section(changelog: str, version: str) -> str:
    """The notes for one version from a Keep a Changelog style file."""
    lines, out, inside = changelog.splitlines(), [], False
    for line in lines:
        if line.startswith("## "):
            if inside:
                break
            inside = f"[{version}]" in line or line[3:].strip().startswith(version)
            continue
        if inside:
            out.append(line)
    return "\n".join(out).strip()


class UpdateService:
    def __init__(self, db: Database, current: str, repo: str, upgrade_dir: str = "",
                 client: httpx.AsyncClient | None = None):
        self.db = db
        self.current = current
        self.repo = repo if re.fullmatch(r"[\w.-]+/[\w.-]+", repo or "") else ""
        self.dir = Path(upgrade_dir) if upgrade_dir else None
        self.client = client or httpx.AsyncClient(timeout=10, follow_redirects=True)

    # ------------------------------------------------------------------ release check

    async def fetch_latest(self) -> dict:
        if not self.repo:
            raise UpdateError("SOURCE_REPO isn't a GitHub owner/name, so releases can't be checked")
        headers = {"Accept": "application/vnd.github+json", "User-Agent": f"Karoulette/{self.current}"}
        r = await self.client.get(f"https://api.github.com/repos/{self.repo}/releases/latest", headers=headers)
        if r.status_code == 200:
            data = r.json()
            tag = str(data.get("tag_name", ""))
            if not SEMVER.match(tag):
                raise UpdateError(f"the latest release has an unexpected tag ({tag[:40]})")
            return {
                "version": tag.lstrip("v"),
                "notes": str(data.get("body") or "")[:MAX_NOTES],
                "url": str(data.get("html_url") or f"https://github.com/{self.repo}/releases/tag/{tag}"),
                "published_at": data.get("published_at"),
            }
        if r.status_code != 404:
            r.raise_for_status()
        # No GitHub Release yet: fall back to VERSION and CHANGELOG.md on the main branch.
        raw = f"https://raw.githubusercontent.com/{self.repo}/main"
        v = await self.client.get(f"{raw}/VERSION", headers=headers)
        if v.status_code == 404:
            raise UpdateError("no releases published yet")
        v.raise_for_status()
        version = v.text.strip()
        if not SEMVER.match(version):
            raise UpdateError(f"VERSION on main is not a version number ({version[:40]})")
        notes = ""
        c = await self.client.get(f"{raw}/CHANGELOG.md", headers=headers)
        if c.status_code == 200:
            notes = changelog_section(c.text, version)[:MAX_NOTES]
        return {"version": version, "notes": notes,
                "url": f"https://github.com/{self.repo}/blob/main/CHANGELOG.md", "published_at": None}

    async def check(self) -> dict:
        entry: dict[str, Any] = {"checked_at": _now().isoformat()}
        try:
            entry["release"] = await self.fetch_latest()
        except (httpx.HTTPError, UpdateError, ValueError) as exc:
            previous = self.db.get_setting(SETTING_KEY, {}) or {}
            entry["release"] = previous.get("release")
            entry["error"] = (getattr(exc, "message", None) or str(exc) or exc.__class__.__name__)[:300]
            log.warning("Update check failed: %s", entry["error"])
        self.db.set_setting(SETTING_KEY, entry)
        if entry.get("release") and newer(entry["release"]["version"], self.current):
            log.info("Karoulette %s is available (running %s)", entry["release"]["version"], self.current)
        return entry

    async def daily_check(self) -> None:
        last = _when((self.db.get_setting(SETTING_KEY, {}) or {}).get("checked_at"))
        if last is None or _now() - last > CHECK_EVERY:
            await self.check()

    async def check_now(self) -> dict:
        last = _when((self.db.get_setting(SETTING_KEY, {}) or {}).get("checked_at"))
        if last is None or _now() - last > RECHECK_AFTER:
            await self.check()
        return self.status()

    # ------------------------------------------------------------------ upgrade folder

    def _helper(self, now: datetime) -> dict:
        if self.dir is None or not self.dir.is_dir():
            return {"configured": False, "connected": False, "last_seen": None, "every_minutes": 15}
        agent = _read_json(self.dir / "agent.json") or {}
        seen = _when(agent.get("last_seen"))
        try:
            every = min(max(int(agent.get("every_minutes") or 15), 1), 60)
        except (TypeError, ValueError):
            every = 15
        limit = max(AGENT_STALE, timedelta(minutes=2 * every + 1))  # tolerate one missed run
        return {"configured": True, "connected": bool(seen and -CLOCK_SKEW < now - seen < limit),
                "last_seen": _iso(seen), "every_minutes": every}

    def _upgrade(self, now: datetime) -> dict | None:
        if self.dir is None:
            return None
        request = _read_json(self.dir / "request.json")
        if request:
            requested_at = _when(request.get("requested_at"))
            state = {"id": str(request.get("id", ""))[:64], "state": "requested",
                     "to_version": _text(request.get("version"), 32), "requested_at": _iso(requested_at),
                     "message": None}
            if requested_at and now - requested_at > STALE_REQUEST:
                state["state"] = "failed"
                state["message"] = "The upgrade helper never picked this request up. Check it's running, then try again."
            return state
        status = _read_json(self.dir / "status.json")
        if not status or status.get("state") not in ("running", "succeeded", "failed"):
            return None
        started = _when(status.get("started_at"))
        state = {"id": str(status.get("id", ""))[:64], "state": status["state"],
                 "from_version": _text(status.get("from_version"), 32),
                 "to_version": _text(status.get("to_version"), 32), "started_at": _iso(started),
                 "finished_at": _iso(_when(status.get("finished_at"))),
                 "message": _text(status.get("message"), 500)}
        if state["state"] == "running" and started and now - started > STALE_RUNNING:
            state["state"] = "failed"
            state["message"] = "The upgrade helper stopped reporting. See the log, and check the server."
        return state

    def _log_tail(self) -> str | None:
        if self.dir is None:
            return None
        path = self.dir / "upgrade.log"
        try:
            if path.is_symlink():
                return None
            with path.open("rb") as f:
                f.seek(0, os.SEEK_END)
                f.seek(max(0, f.tell() - MAX_LOG))
                return f.read().decode("utf-8", "replace")
        except OSError:
            return None

    def status(self) -> dict:
        now = _now()
        cached = self.db.get_setting(SETTING_KEY, {}) or {}
        latest = cached.get("release")
        available = bool(latest and newer(latest["version"], self.current))
        helper = self._helper(now)
        upgrade = self._upgrade(now)
        busy = bool(upgrade and upgrade["state"] in ("requested", "running"))
        return {
            "current": self.current,
            "latest": latest,
            "update_available": available,
            "checked_at": cached.get("checked_at"),
            "check_error": cached.get("error"),
            "helper": helper,
            "upgrade": upgrade,
            "can_upgrade": available and helper["connected"] and not busy,
            "log": self._log_tail(),
        }

    def request_upgrade(self, version: str) -> dict:
        current = self.status()
        if current["upgrade"] and current["upgrade"]["state"] in ("requested", "running"):
            raise UpdateError("An upgrade is already under way.", 409)
        latest = current["latest"]
        if not latest or version != latest["version"] or not current["update_available"]:
            raise UpdateError("You can only upgrade to the latest release, and it must be newer than this one.")
        if not current["helper"]["connected"]:
            raise UpdateError("The upgrade helper on the server isn't running. See the setup steps on this page.")
        assert self.dir is not None
        request_id = str(uuid.uuid4())
        body = {"id": request_id, "version": version, "requested_by": "host",
                "requested_at": _now().isoformat()}
        tmp = self.dir / f".request-{request_id}.tmp"
        try:
            tmp.write_text(json.dumps(body))
            os.replace(tmp, self.dir / "request.json")
        except OSError as exc:
            tmp.unlink(missing_ok=True)
            raise UpdateError("Karoulette can't write to the upgrade folder. "
                              "Run sudo ./scripts/upgrade-agent.sh --install on the server.") from exc
        log.info("Upgrade to %s requested", version)
        return self.status()

    async def aclose(self) -> None:
        await self.client.aclose()

