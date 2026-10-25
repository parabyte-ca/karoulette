"""HTTP API: auth, the guest flow, validation, rate limits and admin endpoints (``client`` is in conftest)."""


def login(client):
    assert client.post("/api/host/login", json={"pin": "0000"}).status_code == 401
    assert client.post("/api/host/login", json={"pin": "4321"}).status_code == 200


def test_host_endpoints_require_login(client):
    assert client.get("/api/host/events").status_code == 401
    login(client)
    assert client.get("/api/host/events").status_code == 200


def test_full_guest_flow(client):
    login(client)
    created = client.post("/api/host/events", json={"name": "Friday", "config": {"superset_chance": 0, "themes_enabled": True}}).json()
    code = created["join_code"]
    assert client.get(f"/api/public/events/{code}").json()["name"] == "Friday"
    assert client.get(f"/api/public/qr.svg?code={code}").headers["content-type"].startswith("image/svg")

    guest = client.post("/api/guest/join", json={"code": code, "name": "Alex"}).json()
    headers = {"Authorization": f"Bearer {guest['token']}"}
    assert client.post(f"/api/host/events/{created['id']}/actions/start").status_code == 200
    state = client.get("/api/guest/state", headers=headers).json()
    assert state["round"]["number"] == 1 and state["round"]["theme"]["name"]

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


def test_song_actions_endpoints(client):
    login(client)
    created = client.post("/api/host/events", json={"name": "Free", "config": {"superset_chance": 0,
                                                                              "prevent_duplicates": False,
                                                                              "autoplay": False}}).json()
    a = client.post("/api/guest/join", json={"code": created["join_code"], "name": "A"}).json()
    b = client.post("/api/guest/join", json={"code": created["join_code"], "name": "B"}).json()
    ha = {"Authorization": f"Bearer {a['token']}"}
    hb = {"Authorization": f"Bearer {b['token']}"}
    # No waiting for a turn: both can add several songs straight away, even before the start.
    ids = [client.post("/api/guest/queue", json={"video_id": "abcdefghijk"}, headers=h).json()["item_id"]
           for h in (ha, ha, hb)]
    queue = client.get("/api/guest/state", headers=ha).json()["queue"]
    assert [q["guest_id"] for q in queue] == [a["guest"]["id"], b["guest"]["id"], a["guest"]["id"]]
    assert client.post(f"/api/guest/queue/{ids[0]}/let-next-go-first", headers=hb).status_code == 409
    assert client.post(f"/api/guest/queue/{ids[0]}/let-next-go-first", headers=ha).status_code == 200
    queue = client.get("/api/guest/state", headers=ha).json()["queue"]
    assert queue[0]["guest_id"] == b["guest"]["id"]
    assert client.post(f"/api/host/events/{created['id']}/queue/{ids[1]}/play-next").status_code == 200
    assert client.get("/api/guest/state", headers=ha).json()["queue"][0]["id"] == ids[1]
    assert client.post(f"/api/host/events/{created['id']}/guests/{b['guest']['id']}/up").status_code == 200


def test_updates_endpoints_need_host(client):
    assert client.get("/api/host/updates").status_code == 401
    login(client)
    body = client.get("/api/host/updates").json()
    assert body["current"] and body["helper"]["configured"] is False
    assert client.post("/api/host/updates/upgrade", json={"version": "bad"}).status_code == 422


def test_colour_scheme_setting(client):
    assert client.get("/api/public/appearance").json()["scheme"] == "neon"
    assert client.put("/api/host/appearance", json={"scheme": "aurora"}).status_code == 401
    login(client)
    assert client.put("/api/host/appearance", json={"scheme": "nope"}).status_code == 400
    assert client.put("/api/host/appearance", json={"scheme": "synthwave"}).json()["scheme"] == "synthwave"
    assert client.get("/api/public/appearance").json()["scheme"] == "synthwave"
    code = client.post("/api/host/events", json={"name": "Look"}).json()["join_code"]
    token = client.post("/api/guest/join", json={"code": code, "name": "Ana"}).json()["token"]
    with client.websocket_connect(f"/ws/{code}?token={token}") as ws:
        assert ws.receive_json()["data"]["appearance"]["scheme"] == "synthwave"
        client.put("/api/host/appearance", json={"scheme": "velvet"})
        msg = ws.receive_json()
        while msg["type"] != "state":
            msg = ws.receive_json()
        assert msg["data"]["appearance"]["scheme"] == "velvet"


def test_search_marks_songs_already_queued(client):
    login(client)
    ev = client.post("/api/host/events", json={"name": "Dup Night"}).json()
    token = client.post("/api/guest/join", json={"code": ev["join_code"], "name": "Alex"}).json()["token"]
    auth = {"Authorization": f"Bearer {token}"}
    assert client.get("/api/guest/search?q=test", headers=auth).json()["results"][0]["already"] is False
    client.post("/api/guest/queue", headers=auth, json={"video_id": "zyxwvutsrqp"})   # "Test Song" again
    hit = client.get("/api/guest/search?q=test", headers=auth).json()["results"][0]
    assert hit["already"] is True and hit["blocked"] is True                            # other channel, same song
    refused = client.post("/api/guest/queue", headers=auth, json={"video_id": "abcdefghijk"})
    assert refused.status_code == 409 and "already in the queue (picked by you)" in refused.json()["detail"]
