import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.youtube import YouTubeService


class StubYouTube(YouTubeService):
    def __init__(self, db):
        super().__init__(db, api_key="SECRET-KEY-DO-NOT-LEAK", enable_ytdlp=False)
        self.searches = 0

    async def search(self, raw_query, safe_search="moderate"):
        self.searches += 1
        return {"query": raw_query + " karaoke", "source": "api", "cached": False,
                "results": [{"video_id": "abcdefghijk", "title": "Test Song", "channel": "Ch",
                             "duration_s": 180, "thumbnail": "", "embeddable": True}]}

    async def verify(self, video_id):
        if video_id == "blockedvid0":
            return {"video_id": video_id, "embeddable": False}
        return {"video_id": video_id, "title": "Test Song", "channel": "Ch", "duration_s": 180,
                "embeddable": True, "thumbnail": ""}


@pytest.fixture
def client(tmp_path):
    settings = Settings(data_path=tmp_path, host_pin="4321", static_dir=tmp_path / "static",
                        youtube_api_key="SECRET-KEY-DO-NOT-LEAK")
    holder = {}

    def make():
        from app.db import Database
        return StubYouTube(Database(tmp_path / "karaokequeue.db"))

    app = create_app(settings, start_ticker=False, youtube=make())
    with TestClient(app) as c:
        holder["app"] = app
        yield c


def login(client):
    assert client.post("/api/host/login", json={"pin": "0000"}).status_code == 401
    assert client.post("/api/host/login", json={"pin": "4321"}).status_code == 200


def test_host_endpoints_require_login(client):
    assert client.get("/api/host/events").status_code == 401
    login(client)
    assert client.get("/api/host/events").status_code == 200


def test_full_guest_flow(client):
    login(client)
    created = client.post("/api/host/events", json={"name": "Friday", "config": {"announce_seconds": 0,
                                                                                 "superset_chance": 0}}).json()
    code = created["join_code"]
    assert client.get(f"/api/public/events/{code}").json()["name"] == "Friday"
    assert client.get(f"/api/public/qr.svg?code={code}").headers["content-type"].startswith("image/svg")

    guest = client.post("/api/guest/join", json={"code": code, "name": "Alex"}).json()
    headers = {"Authorization": f"Bearer {guest['token']}"}
    assert client.post(f"/api/host/events/{created['id']}/actions/start").status_code == 200

    engine = client.app.state.engine
    clock_now = engine.get_event(created["id"])["phase_deadline"]
    engine.tick(clock_now + 0.1)  # spin -> choosing
    state = client.get("/api/guest/state", headers=headers).json()
    assert state["turn"]["guest_id"] == guest["guest"]["id"]

    res = client.get("/api/guest/search?q=bohemian", headers=headers)
    assert res.status_code == 200 and "SECRET" not in res.text
    blocked = client.post("/api/guest/queue", json={"video_id": "blockedvid0"}, headers=headers)
    assert blocked.status_code == 422
    ok = client.post("/api/guest/queue", json={"video_id": "abcdefghijk"}, headers=headers)
    assert ok.status_code == 200, ok.text

    with client.websocket_connect(f"/ws/{code}?token={guest['token']}") as ws:
        msg = ws.receive_json()
        assert msg["type"] == "state" and msg["data"]["now_playing"]["video_id"] == "abcdefghijk"

    csv = client.get(f"/api/host/events/{created['id']}/history.csv")
    assert csv.status_code == 200 and "Test Song" in csv.text


def test_input_validation_and_rate_limit(client):
    login(client)
    code = client.post("/api/host/events", json={"name": "V"}).json()["join_code"]
    assert client.post("/api/guest/join", json={"code": code, "name": ""}).status_code == 422
    token = client.post("/api/guest/join", json={"code": code, "name": "Rae"}).json()["token"]
    headers = {"Authorization": f"Bearer {token}"}
    assert client.post("/api/guest/queue", json={"video_id": "../etc"}, headers=headers).status_code == 422
    assert client.get("/api/guest/search?q=", headers=headers).status_code == 422
    codes = [client.get(f"/api/guest/search?q=s{i}", headers=headers).status_code for i in range(12)]
    assert 429 in codes


def test_bad_guest_token(client):
    assert client.get("/api/guest/state", headers={"Authorization": "Bearer nope"}).status_code == 401


def test_quota_never_leaks_key(client):
    login(client)
    body = client.get("/api/host/quota").text
    assert "SECRET" not in body and '"api_key_configured":true' in body


def test_themes_crud(client):
    login(client)
    themes = client.get("/api/host/themes").json()
    assert {"80s", "Canadiana", "One-Hit Wonders"} <= {t["name"] for t in themes}
    t = client.post("/api/host/themes", json={"name": "Disco", "weight": 2}).json()
    assert client.post("/api/host/themes", json={"name": "disco"}).status_code == 409
    upd = client.put(f"/api/host/themes/{t['id']}", json={"name": "Disco", "enabled": False}).json()
    assert upd["enabled"] is False
    assert client.delete(f"/api/host/themes/{t['id']}").status_code == 200


def test_guest_pass_endpoint(client):
    login(client)
    created = client.post("/api/host/events", json={"name": "Pass", "config": {"announce_seconds": 0,
                                                                               "superset_chance": 0}}).json()
    a = client.post("/api/guest/join", json={"code": created["join_code"], "name": "A"}).json()
    b = client.post("/api/guest/join", json={"code": created["join_code"], "name": "B"}).json()
    client.post(f"/api/host/events/{created['id']}/actions/start")
    ha = {"Authorization": f"Bearer {a['token']}"}
    hb = {"Authorization": f"Bearer {b['token']}"}
    assert client.post("/api/guest/pass", headers=hb).status_code == 409
    assert client.post("/api/guest/pass", headers=ha).status_code == 200
    state = client.get("/api/guest/state", headers=ha).json()
    assert state["turn"]["guest_id"] == b["guest"]["id"]
    assert state["upcoming"][0] == a["guest"]["id"]


def test_updates_endpoints_need_host(client):
    assert client.get("/api/host/updates").status_code == 401
    login(client)
    body = client.get("/api/host/updates").json()
    assert body["current"] and body["helper"]["configured"] is False
    assert client.post("/api/host/updates/upgrade", json={"version": "bad"}).status_code == 422
