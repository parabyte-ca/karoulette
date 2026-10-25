"""Archived events, the event timeline and the banner travelling with backups (v0.12.0)."""
import pytest

from app.banner import BannerStore
from app.db import Database
from app.engine import EngineError
from tests.conftest import add
from tests.test_api import login

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32


def test_archive_hides_but_keeps_songs(engine, make_event):
    eid, (a,) = make_event(names=("Alex",))
    add(engine, a)
    engine.play_next(eid)
    with pytest.raises(EngineError):
        engine.archive_event(eid)                              # still running
    engine.end_event(eid)
    engine.archive_event(eid)
    assert next(e for e in engine.list_events() if e["id"] == eid)["archived_at"]
    assert [s["event"] for s in engine.history()["songs"]] == ["Test Night"]   # still in the history
    with pytest.raises(EngineError):
        engine.join(eid, "Late")
    engine.archive_event(eid, False)
    assert not next(e for e in engine.list_events() if e["id"] == eid)["archived_at"]


def test_timeline_records_who_did_what(client):
    login(client)
    ev = client.post("/api/host/events", json={"name": "Log Night", "config": {"autoplay": True, "ready_seconds": 0}}).json()
    alex = client.post("/api/guest/join", json={"code": ev["join_code"], "name": "Alex"}).json()["token"]
    blake = client.post("/api/guest/join", json={"code": ev["join_code"], "name": "Blake"}).json()["token"]
    client.post(f"/api/host/events/{ev['id']}/actions/start")
    first = client.post("/api/guest/queue", headers={"Authorization": f"Bearer {alex}"},
                        json={"video_id": "abcdefghijk"}).json()["item_id"]
    refused = client.post("/api/guest/queue", headers={"Authorization": f"Bearer {blake}"},
                          json={"video_id": "zyxwvutsrqp"})                    # "Test Song" again
    assert refused.status_code == 409
    client.post(f"/api/host/events/{ev['id']}/actions/skip-song")
    client.post(f"/api/host/events/{ev['id']}/actions/end")

    log = client.get(f"/api/host/events/{ev['id']}/timeline").json()
    lines = [(r["actor_name"], r["kind"], r["text"]) for r in log]
    assert ("Host", "event", "Event started") in lines
    assert ("Alex", "singers", "Alex joined") in lines
    assert any(who == "Alex" and text.startswith("Alex added “Test Song”, round 1") for who, _, text in lines)
    assert any(who == "Karoulette" and text.startswith("Now playing: Alex") for who, _, text in lines)   # autoplay
    assert any(who == "Blake" and "refused" in text and "duplicate" in text for who, _, text in lines)
    assert any(who == "Host" and text.startswith("Skipped “Test Song” (Alex)") for who, _, text in lines)
    assert next(r for r in log if r["text"].startswith("Alex added"))["data"]["item_id"] == first
    csv = client.get(f"/api/host/events/{ev['id']}/timeline.csv")
    assert csv.headers["content-type"].startswith("text/csv") and "Event started" in csv.text
    client.cookies.clear()
    assert client.get(f"/api/host/events/{ev['id']}/timeline").status_code == 401


def test_archive_endpoint_and_delete_for_good(client):
    login(client)
    ev = client.post("/api/host/events", json={"name": "Old Night"}).json()
    assert client.post(f"/api/host/events/{ev['id']}/archive", json={"on": True}).json()["archived_at"]
    assert client.get("/api/host/events").json()[0]["archived_at"]
    assert client.delete(f"/api/host/events/{ev['id']}").status_code == 200
    assert client.get("/api/host/events").json() == []


def test_banner_lives_in_the_database_and_backups(client):
    login(client)
    client.put("/api/host/appearance/banner", content=PNG)
    made = client.post("/api/host/backups").json()
    client.delete("/api/host/appearance/banner")
    assert client.get("/api/public/banner").status_code == 404
    client.post(f"/api/host/backups/{made['name']}/restore")            # the backup brings it back
    got = client.get("/api/public/banner")
    assert got.status_code == 200 and got.content == PNG and got.headers["content-type"] == "image/png"


def test_old_banner_file_is_moved_into_the_database(tmp_path):
    (tmp_path / "banner").mkdir()
    (tmp_path / "banner" / "banner.png").write_bytes(PNG)
    store = BannerStore(Database(":memory:"), tmp_path)
    store.migrate()
    assert store.get() == (PNG, "image/png")
    store.delete()
    assert store.get() is None and not (tmp_path / "banner" / "banner.png").exists()
