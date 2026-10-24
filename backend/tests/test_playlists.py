"""Playlists from events and the song history: original-song lookup, access rules and the Spotify setting."""
import asyncio

from app import logic
from app.db import Database
from app.youtube import YouTubeService
from tests.test_api import login


def test_playlist_song_cleans_karaoke_titles():
    assert logic.playlist_song("Africa (In the Style of Toto) (Karaoke Version)") == "Toto - Africa"
    assert logic.playlist_song("Bon Jovi - Livin' On A Prayer (Karaoke Version)") == "Bon Jovi - Livin' On A Prayer"
    assert logic.playlist_song("Queen - Bohemian Rhapsody (Lyrics) [HD]") == "Queen - Bohemian Rhapsody"
    assert logic.playlist_song("Bon Jovi | Livin' on a prayer | Karaoke") == "Bon Jovi - Livin' on a prayer"


def test_find_original_skips_karaoke_and_caches():
    yt = YouTubeService(Database(":memory:"), api_key="", enable_ytdlp=True)
    calls = []

    async def fake_search(query):
        calls.append(query)
        if "Nowhere" in query:
            return [{"video_id": "karaoke0001", "title": "Nowhere Song (Karaoke)"}]
        return [{"video_id": "karaoke0002", "title": "Toto - Africa (Karaoke Version)"},
                {"video_id": "original001", "title": "Toto - Africa (Official Audio)"}]

    yt._ytdlp_search = fake_search
    run = asyncio.run
    assert run(yt.find_original("Toto - Africa")) == "original001"
    assert run(yt.find_original("toto - africa")) == "original001"      # cached: no second search
    assert calls == ["Toto - Africa official audio"]
    assert run(yt.find_original("Nowhere Song")) is None                # only karaoke versions: none
    assert run(yt.find_original("Nowhere Song")) is None and len(calls) == 2


def test_find_original_without_any_search_tries_again_later():
    yt = YouTubeService(Database(":memory:"), api_key="", enable_ytdlp=False)
    assert asyncio.run(yt.find_original("Toto - Africa")) is None
    assert yt.db.one("SELECT * FROM song_originals") is None


def test_event_playlist_and_originals_endpoint(client):
    login(client)
    ev = client.post("/api/host/events", json={"name": "Friday", "config": {"autoplay": True, "ready_seconds": 0}}).json()
    token = client.post("/api/guest/join", json={"code": ev["join_code"], "name": "Alex"}).json()["token"]
    auth = {"Authorization": f"Bearer {token}"}
    client.post(f"/api/host/events/{ev['id']}/actions/start")
    item_id = client.post("/api/guest/queue", headers=auth, json={"video_id": "abcdefghijk"}).json()["item_id"]
    client.post(f"/api/host/events/{ev['id']}/player", json={"item_id": item_id, "state": "ended"})

    client.cookies.clear()                                           # a guest, not the host
    pl = client.get(f"/api/public/events/{ev['join_code']}/playlist").json()
    assert pl["event"]["name"] == "Friday" and [t["track"] for t in pl["tracks"]] == ["Test Song"]
    # No search available in tests: the karaoke video stands in for the original.
    got = client.post("/api/public/playlist/originals", json={"item_ids": [item_id], "code": ev["join_code"]}).json()
    assert got == [{"item_id": item_id, "track": "Test Song", "video_id": "abcdefghijk", "original": False}]
    # The wrong event's code finds nothing; without a code it follows the history sharing switch.
    assert client.post("/api/public/playlist/originals", json={"item_ids": [item_id], "code": "ZZZZZ"}).json() == []
    assert len(client.post("/api/public/playlist/originals", json={"item_ids": [item_id]}).json()) == 1
    login(client)
    client.put("/api/host/history/public", json={"on": False})
    client.cookies.clear()
    assert client.post("/api/public/playlist/originals", json={"item_ids": [item_id]}).status_code == 403


def test_spotify_client_id_setting(client):
    assert client.get("/api/public/playlist-config").json() == {"spotify_client_id": ""}
    assert client.put("/api/host/playlists/spotify", json={"client_id": "abc"}).status_code == 401
    login(client)
    assert client.put("/api/host/playlists/spotify", json={"client_id": "bad id!"}).status_code == 422
    client.put("/api/host/playlists/spotify", json={"client_id": "0123abcdef"})
    assert client.get("/api/public/playlist-config").json() == {"spotify_client_id": "0123abcdef"}
