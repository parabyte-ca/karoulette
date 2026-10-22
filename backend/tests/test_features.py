"""v0.7.0: get-ready countdown, song limit, duets, rejoin codes, recap, reactions and the host remote."""
import pytest

from app.engine import EngineError

from .conftest import add, play_all, video
from .test_api import client, login  # noqa: F401  (fixture)


# ---------------------------------------------------------------- get ready


def test_get_ready_countdown_defaults_to_five_seconds(engine, make_event, clock):
    eid, (alex, *_) = make_event()
    assert engine.get_event(eid)["config"]["ready_seconds"] == 5
    add(engine, alex)
    engine.play_next(eid)
    snap = engine.snapshot(eid)
    assert snap["now_playing"]["starts_at"] == pytest.approx(clock.now + 5, abs=0.01)
    engine.start_now(eid)
    snap = engine.snapshot(eid)
    assert snap["now_playing"]["starts_at"] == snap["now_playing"]["started_at"]
    assert any(m["message"]["type"] == "ready_skipped" for m in engine.drain())


def test_get_ready_can_be_turned_off(engine, make_event):
    eid, (alex, *_) = make_event(ready_seconds=0)
    add(engine, alex)
    engine.play_next(eid)
    assert engine.get_event(eid)["ready_until"] is None
    engine.update_event(eid, None, {"ready_seconds": 500})
    assert engine.get_event(eid)["config"]["ready_seconds"] == 60  # clamped


def test_video_commands_reach_the_tv(engine, make_event):
    eid, _ = make_event()
    engine.video_command(eid, "volume_up")
    assert engine.drain()[-1]["message"] == {"type": "video_command", "data": {"command": "volume_up"}}
    with pytest.raises(EngineError):
        engine.video_command(eid, "self_destruct")


# ---------------------------------------------------------------- song limit


def test_songs_per_singer_limit(engine, make_event):
    eid, (alex, blake, _) = make_event(max_songs_per_singer=2)
    add(engine, alex)
    add(engine, alex)
    with pytest.raises(EngineError) as err:
        add(engine, alex)
    assert err.value.status == 409 and "limit is 2" in err.value.message
    add(engine, blake)  # other singers are unaffected
    engine.play_next(eid)  # Alex's first song is now playing, not waiting
    add(engine, alex)


# ---------------------------------------------------------------- duets


def test_duet_shows_both_names_and_notifies_partner(engine, make_event):
    eid, (alex, blake, casey) = make_event()
    engine.queue_song(alex["id"], video(), duet_guest_id=blake["id"])
    assert any(m["message"]["type"] == "duet_invite" and m["guest_id"] == blake["id"] for m in engine.drain())
    item = engine.snapshot(eid)["queue"][0]
    assert (item["guest_name"], item["duet_name"]) == ("Alex", "Blake")
    engine.play_next(eid)
    singing = {m["guest_id"] for m in engine.drain() if m["message"]["type"] == "you_are_singing"}
    assert singing == {alex["id"], blake["id"]}


def test_duet_partner_rules(engine, make_event):
    eid, (alex, blake, casey) = make_event()
    with pytest.raises(EngineError):
        engine.queue_song(alex["id"], video(), duet_guest_id=alex["id"])
    other = engine.create_event("Other night")
    stranger, _ = engine.join(other["id"], "Zed")
    with pytest.raises(EngineError):
        engine.queue_song(alex["id"], video(), duet_guest_id=stranger["id"])
    item = engine.queue_song(alex["id"], video(), duet_guest_id=blake["id"])
    with pytest.raises(EngineError):
        engine.leave_duet(casey["id"], item["id"])
    engine.leave_duet(blake["id"], item["id"])
    assert engine.snapshot(eid)["queue"][0]["duet_name"] is None
    # A partner who leaves the event drops off the duet; the song stays.
    item2 = engine.queue_song(alex["id"], video(), duet_guest_id=casey["id"])
    engine.leave(casey["id"])
    q = [i for i in engine.snapshot(eid)["queue"] if i["id"] == item2["id"]]
    assert q and q[0]["duet_name"] is None


# ---------------------------------------------------------------- rejoin codes


def test_rejoin_moves_the_singer_to_a_new_phone(engine, make_event):
    eid, (alex, *_) = make_event()
    code = engine.rejoin_code(alex["id"])
    assert len(code) == 6 and code == engine._guest(alex["id"])["rejoin_code"]
    old_token_hash = engine._guest(alex["id"])["token_hash"]
    guest, token = engine.rejoin(eid, code.lower())
    assert guest["id"] == alex["id"] and engine.guest_by_token(token)["id"] == alex["id"]
    assert engine._guest(alex["id"])["token_hash"] != old_token_hash
    assert any(m["message"]["type"] == "session_replaced" for m in engine.drain())
    with pytest.raises(EngineError):
        engine.rejoin(eid, "ZZZZZZ")


def test_rejoin_after_leaving_but_not_after_removal(engine, make_event):
    eid, (alex, blake, _) = make_event()
    engine.leave(alex["id"])
    guest, _ = engine.rejoin(eid, engine.rejoin_code(alex["id"]))
    assert guest["status"] == "active"
    engine.remove_guest(blake["id"])
    with pytest.raises(EngineError):
        engine.rejoin(eid, engine.rejoin_code(blake["id"]))


def test_rejoin_codes_stay_out_of_the_shared_snapshot(engine, make_event):
    eid, (alex, *_) = make_event()
    code = engine.rejoin_code(alex["id"])
    assert code not in str(engine.snapshot(eid))
    assert {g["name"]: g["rejoin_code"] for g in engine.guest_codes(eid)}["Alex"] == code


# ---------------------------------------------------------------- recap


def test_recap_after_the_event(engine, make_event):
    eid, (alex, blake, casey) = make_event()
    add(engine, alex)
    engine.queue_song(blake["id"], video(), duet_guest_id=casey["id"])
    add(engine, alex)
    play_all(engine, eid)
    assert engine.snapshot(eid)["recap"] is None
    engine.end_event(eid)
    recap = engine.snapshot(eid)["recap"]
    assert recap["songs"] == 3 and recap["singers"] == 3 and recap["duets"] == 1
    assert recap["top_singers"] == ["Alex"] and recap["top_count"] == 2
    assert recap["minutes"] == 10  # 3 x 200 s
    assert recap["first_song"]["singer"] == "Alex" and recap["last_song"]["singer"] == "Alex"
    assert recap["per_singer"] == {"Alex": 2, "Blake": 1, "Casey": 1}


# ---------------------------------------------------------------- API


def test_feature_endpoints(client):  # noqa: F811
    login(client)
    ev = client.post("/api/host/events", json={"name": "Remote night"}).json()
    code, eid = ev["join_code"], ev["id"]
    alex = client.post("/api/guest/join", json={"code": code, "name": "Alex"}).json()
    blake = client.post("/api/guest/join", json={"code": code, "name": "Blake"}).json()
    ha = {"Authorization": f"Bearer {alex['token']}"}
    assert len(alex["guest"]["rejoin_code"]) == 6
    assert client.get("/api/guest/me", headers=ha).json()["guest"]["rejoin_code"] == alex["guest"]["rejoin_code"]

    # duet
    res = client.post("/api/guest/queue", json={"video_id": "abcdefghijk", "duet_guest_id": blake["guest"]["id"]},
                      headers=ha)
    assert res.status_code == 200, res.text
    state = client.get("/api/guest/state", headers=ha).json()
    assert state["queue"][0]["duet_name"] == "Blake" and "rejoin_code" not in str(state)

    # reactions: only the listed emoji, and rate limited
    assert client.post("/api/guest/react", json={"emoji": "💩"}, headers=ha).status_code == 422
    assert client.post("/api/guest/react", json={"emoji": "🔥"}, headers=ha).status_code == 200
    codes = [client.post("/api/guest/react", json={"emoji": "👏"}, headers=ha).status_code for _ in range(25)]
    assert 429 in codes

    # host remote
    for action in ("start", "start-now", "video-toggle", "volume-up", "volume-down", "skip-song"):
        assert client.post(f"/api/host/events/{eid}/actions/{action}").status_code == 200, action
    assert client.get(f"/api/host/events/{eid}/remote-qr.svg").headers["content-type"].startswith("image/svg")
    guests = client.get(f"/api/host/events/{eid}/guests").json()
    assert {g["name"] for g in guests} == {"Alex", "Blake"}

    # rejoin on a new phone signs the old one out
    again = client.post("/api/guest/rejoin", json={"code": code, "rejoin_code": alex["guest"]["rejoin_code"]})
    assert again.status_code == 200 and again.json()["guest"]["id"] == alex["guest"]["id"]
    assert client.get("/api/guest/me", headers=ha).status_code == 401
    assert client.post("/api/guest/rejoin", json={"code": code, "rejoin_code": "NOPE00"}).status_code == 404

    client.post("/api/host/logout")
    assert client.get(f"/api/host/events/{eid}/guests").status_code == 401
    assert client.get(f"/api/host/events/{eid}/remote-qr.svg").status_code == 401
