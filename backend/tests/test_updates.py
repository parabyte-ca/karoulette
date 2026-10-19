import asyncio
import json
from datetime import datetime, timedelta, timezone

import httpx
import pytest

from app.config import normalise_base_url
from app.db import Database
from app.updates import UpdateError, UpdateService, changelog_section, newer

CHANGELOG = """# Changelog

## [0.4.0] - 2026-11-01
### Added
- Something new.

## [0.3.0] - 2026-10-19
### Added
- Older.
"""


def service(handler, tmp_path=None, current="0.3.0"):
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return UpdateService(Database(":memory:"), current, "parabyte-ca/karoulette",
                         str(tmp_path) if tmp_path else "", client=client)


def test_newer_and_changelog():
    assert newer("0.10.0", "0.9.9") and not newer("0.3.0", "0.3.0") and not newer("junk", "0.1.0")
    assert changelog_section(CHANGELOG, "0.4.0") == "### Added\n- Something new."


@pytest.mark.parametrize("raw,expected", [
    ("https://karoulette.moot.es/join", "https://karoulette.moot.es"),
    ("https://karoulette.moot.es/join/", "https://karoulette.moot.es"),
    ("https://k.ca/host/", "https://k.ca"),
    ("https://k.ca/join/AB2CD", "https://k.ca"),
    ("http://10.0.0.5:8095", "http://10.0.0.5:8095"),
    ("", ""),
])
def test_public_base_url_is_normalised(raw, expected):
    assert normalise_base_url(raw) == expected


def test_check_uses_github_release():
    def handler(request):
        assert request.url.path == "/repos/parabyte-ca/karoulette/releases/latest"
        return httpx.Response(200, json={"tag_name": "v0.4.0", "body": "Notes", "html_url": "https://x",
                                         "published_at": "2026-11-01T00:00:00Z"})
    upd = service(handler)
    asyncio.run(upd.check())
    s = upd.status()
    assert s["update_available"] and s["latest"]["version"] == "0.4.0" and s["latest"]["notes"] == "Notes"


def test_check_falls_back_to_main_branch_version():
    def handler(request):
        if "releases" in request.url.path:
            return httpx.Response(404)
        if request.url.path.endswith("/VERSION"):
            return httpx.Response(200, text="0.4.0\n")
        return httpx.Response(200, text=CHANGELOG)
    upd = service(handler)
    asyncio.run(upd.check())
    s = upd.status()
    assert s["latest"]["version"] == "0.4.0" and "Something new" in s["latest"]["notes"]


def test_failed_check_keeps_previous_release():
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(200, json={"tag_name": "v0.4.0", "body": ""})
        return httpx.Response(500)
    upd = service(handler)
    asyncio.run(upd.check())
    asyncio.run(upd.check())
    s = upd.status()
    assert s["latest"]["version"] == "0.4.0" and s["check_error"]


def _release(request):
    return httpx.Response(200, json={"tag_name": "v0.4.0", "body": ""})


def _agent(tmp_path, minutes_ago=1, every=15):
    seen = datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)
    (tmp_path / "agent.json").write_text(json.dumps({"last_seen": seen.isoformat(), "every_minutes": str(every)}))


def test_upgrade_requires_connected_helper(tmp_path):
    upd = service(_release, tmp_path)
    asyncio.run(upd.check())
    assert upd.status()["helper"] == {"configured": True, "connected": False, "last_seen": None, "every_minutes": 15}
    with pytest.raises(UpdateError):
        upd.request_upgrade("0.4.0")
    _agent(tmp_path, minutes_ago=60)
    assert not upd.status()["helper"]["connected"]


def test_upgrade_request_written_for_agent(tmp_path):
    upd = service(_release, tmp_path)
    asyncio.run(upd.check())
    _agent(tmp_path)
    assert upd.status()["can_upgrade"]
    with pytest.raises(UpdateError):
        upd.request_upgrade("0.5.0")  # only the latest
    s = upd.request_upgrade("0.4.0")
    req = json.loads((tmp_path / "request.json").read_text())
    assert req["version"] == "0.4.0" and s["upgrade"]["state"] == "requested" and not s["can_upgrade"]
    with pytest.raises(UpdateError):
        upd.request_upgrade("0.4.0")  # already under way


def test_status_reads_agent_progress_and_log(tmp_path):
    upd = service(_release, tmp_path)
    (tmp_path / "status.json").write_text(json.dumps({
        "id": "x", "state": "succeeded", "from_version": "0.3.0", "to_version": "0.4.0",
        "started_at": datetime.now(timezone.utc).isoformat(), "message": "Upgraded to 0.4.0."}))
    (tmp_path / "upgrade.log").write_text("built\nhealthy\n")
    s = upd.status()
    assert s["upgrade"]["state"] == "succeeded" and s["log"].endswith("healthy\n")


def test_no_upgrade_folder_means_not_configured():
    upd = service(_release)
    s = upd.status()
    assert s["helper"]["configured"] is False and s["upgrade"] is None and not s["can_upgrade"]
