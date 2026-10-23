"""v0.7.0: get-ready countdown, song limit, duets, rejoin codes, recap, reactions and the host remote."""
import pytest

from app.engine import EngineError

from .conftest import add, play_all, video
from .test_api import login


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


def test_feature_endpoints(client):
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


# ---------------------------------------------------------------- Superset votes


def test_vote_outcome_rules():
    from app.logic import vote_outcome
    assert vote_outcome(3, 0, 5) == "passed"          # more than half of everyone: done early
    assert vote_outcome(1, 2, 4) == "failed"          # half said no: yes can't win any more
    assert vote_outcome(1, 1, 4) is None              # still open
    assert vote_outcome(1, 1, 4, closing=True) == "failed"   # a tie fails
    assert vote_outcome(2, 1, 6, closing=True) == "passed"   # majority of the votes cast
    assert vote_outcome(0, 0, 3, closing=True) == "failed"   # nobody voted


def test_superset_vote_fails_on_time_and_each_singer_calls_once(engine, make_event, clock):
    eid, (alex, blake, casey, dana) = make_event(names=("Alex", "Blake", "Casey", "Dana"))
    add(engine, alex)
    engine.play_next(eid)
    engine.call_superset_vote(alex["id"])
    assert engine.snapshot(eid)["superset_vote"]["eligible"] == 3
    with pytest.raises(EngineError):
        engine.vote_superset(alex["id"], True)         # the caller doesn't vote
    with pytest.raises(EngineError):
        engine.call_superset_vote(casey["id"])         # one vote at a time
    engine.vote_superset(blake["id"], True)
    engine.vote_superset(blake["id"], False)           # changing your mind is allowed
    engine.tick()
    assert engine.snapshot(eid)["superset_vote"] is not None
    clock.advance(61)
    engine.tick()                                      # time's up: 0 yes, 1 no
    snap = engine.snapshot(eid)
    assert snap["superset_vote"] is None and snap["superset"] is None
    assert snap["vote_callers"] == [alex["id"]]
    with pytest.raises(EngineError):
        engine.call_superset_vote(alex["id"])


def test_host_cancels_a_vote(engine, make_event):
    eid, (alex, blake, casey) = make_event()
    add(engine, alex)
    engine.play_next(eid)
    engine.call_superset_vote(blake["id"])
    engine.cancel_superset(eid)
    assert engine.snapshot(eid)["superset_vote"] is None
    with pytest.raises(EngineError):
        engine.cancel_superset(eid)                    # nothing left to cancel


def test_superset_vote_needs_the_event_running_and_others(engine, make_event):
    eid, (alex,) = make_event(names=("Alex",), start=False)
    with pytest.raises(EngineError):
        engine.call_superset_vote(alex["id"])
    engine.start_event(eid)
    with pytest.raises(EngineError):
        engine.call_superset_vote(alex["id"])          # nobody else to vote


# ---------------------------------------------------------------- Bouche! and smoke breaks


def test_bouche_announces_on_the_tv(engine, make_event):
    eid, (alex, blake, _) = make_event()
    add(engine, blake)
    engine.remove_guest(blake["id"])
    msgs = [m["message"] for m in engine.drain()]
    assert {"type": "bouched", "data": {"guest_id": blake["id"], "name": "Blake"}} in msgs
    assert any("Blake has been BOUCHED!" in m["data"].get("text", "") for m in msgs)
    assert engine.snapshot(eid)["queue"] == []
    engine.remove_guest(blake["id"])                   # twice does nothing
    assert not engine.drain()


def test_smoke_break_holds_the_queue(engine, make_event):
    eid, (alex, blake, _) = make_event(autoplay=True)
    add(engine, alex)
    add(engine, blake)
    first = engine.get_event(eid)["now_playing_item_id"]
    engine.pause_queue(eid)
    snap = engine.snapshot(eid)
    assert snap["event"]["paused"] and snap["now_playing"] is None
    assert snap["queue"][0]["id"] == first             # the song goes back to the front
    add(engine, alex)                                  # adding songs doesn't start playback
    engine.skip_song(eid)
    assert engine.snapshot(eid)["now_playing"] is None
    engine.resume_queue(eid)
    snap = engine.snapshot(eid)
    assert not snap["event"]["paused"] and snap["now_playing"]["id"] == first


def test_vote_and_break_endpoints(client):
    login(client)
    ev = client.post("/api/host/events", json={"name": "Vote night"}).json()
    tokens = {n: client.post("/api/guest/join", json={"code": ev["join_code"], "name": n}).json()["token"]
              for n in ("Alex", "Blake", "Casey")}
    h = {n: {"Authorization": f"Bearer {t}"} for n, t in tokens.items()}
    assert client.post("/api/guest/superset/call", headers=h["Alex"]).status_code == 409  # not started
    client.post("/api/guest/queue", json={"video_id": "abcdefghijk"}, headers=h["Alex"])
    assert client.post(f"/api/host/events/{ev['id']}/actions/start").status_code == 200
    assert client.post("/api/guest/superset/call", json={"mode": "now"}, headers=h["Alex"]).status_code == 200
    assert client.post("/api/guest/superset/vote", json={"yes": True}, headers=h["Blake"]).status_code == 200
    assert client.post("/api/guest/superset/vote", json={"yes": True}, headers=h["Casey"]).status_code == 200
    sup = client.get("/api/guest/state", headers=h["Alex"]).json()["superset"]
    assert sup["mode"] == "now" and sup["theme"] == "Songs like “Test Song”"
    assert client.post("/api/guest/superset/pass", headers=h["Blake"]).status_code == 200
    assert client.post(f"/api/host/events/{ev['id']}/actions/superset-cancel").status_code == 200
    assert client.post(f"/api/host/events/{ev['id']}/actions/superset-after").status_code == 200
    assert client.get("/api/guest/state", headers=h["Alex"]).json()["superset"]["mode"] == "after"
    assert client.post(f"/api/host/events/{ev['id']}/actions/superset-cancel").status_code == 200

    assert client.post(f"/api/host/events/{ev['id']}/actions/pause-queue").status_code == 200
    state = client.get("/api/guest/state", headers=h["Alex"]).json()
    assert state["event"]["paused"] and state["now_playing"] is None
    assert client.post(f"/api/host/events/{ev['id']}/actions/resume-queue").status_code == 200
    assert client.get("/api/guest/state", headers=h["Alex"]).json()["now_playing"] is not None


# ---------------------------------------------------------------- v0.8.0: cheers, ideas, last call


def test_cheers_count_for_the_song_playing_and_crown_a_favourite(engine, make_event):
    eid, (alex, blake, casey) = make_event()
    add(engine, alex)
    add(engine, blake)
    assert engine.cheer(casey["id"]) is None              # nothing playing yet
    engine.play_next(eid)
    for _ in range(3):
        item_id, count = engine.cheer(blake["id"])
    assert count == 3 and engine.snapshot(eid)["now_playing"]["cheers"] == 3
    engine.player_ended(eid, item_id)
    engine.cheer(alex["id"])                              # Blake's song gets one
    engine.end_event(eid)
    recap = engine.snapshot(eid)["recap"]
    assert recap["crowd_favourite"]["singer"] == "Alex" and recap["crowd_favourite"]["cheers"] == 3
    assert recap["most_cheered"] == {"singer": "Alex", "cheers": 3}
    assert ",cheers," in engine.history_csv(eid).splitlines()[0]


def test_themes_carry_search_ideas(engine, make_event):
    eighties = next(t for t in engine.list_themes() if t["name"] == "80s")
    assert "Bon Jovi" in eighties["ideas"]
    saved = engine.save_theme({"name": "Disco", "ideas": "ABBA, Bee Gees,, Donna Summer, ABBA"})
    assert saved["ideas"] == ["ABBA", "Bee Gees", "Donna Summer"]
    eid, (alex, *_) = make_event()
    add(engine, alex)
    engine.play_next(eid)
    engine.force_superset(eid, "now")                     # "Songs like <song>": ideas come from the title
    sup = engine.snapshot(eid)["superset"]
    assert sup["ideas"] and sup["ideas"][0] in sup["inspired_by"]


def test_last_call_refuses_songs_past_closing_time(engine, make_event, clock):
    import time as _time
    eid, (alex, blake, _) = make_event(ready_seconds=0)
    engine.db.execute("UPDATE events SET started_at = ? WHERE id = ?", (clock.now, eid))
    in_15 = _time.strftime("%H:%M", _time.localtime(clock.now + 15 * 60 + 59))
    engine.update_event(eid, None, {"last_call": in_15})  # room for about three 200-second songs
    info = engine.snapshot(eid)["last_call"]
    assert info["open"] and info["room"] >= 3 and info["closing_text"].endswith(("a.m.", "p.m."))
    for _ in range(4):
        add(engine, alex)
    with pytest.raises(EngineError) as err:
        add(engine, blake)
    assert err.value.status == 409 and "Last call" in err.value.message
    notices = [m["message"]["data"].get("text", "") for m in engine.drain() if m["message"]["type"] == "notice"]
    assert sum("Last call!" in t for t in notices) == 1   # announced once
    assert not engine.snapshot(eid)["last_call"]["open"]
    with pytest.raises(EngineError):
        engine.call_superset_vote(blake["id"], "after")   # no Supersets after last call…
    engine.force_superset(eid, "after")                   # …unless the host squeezes one in
    engine.update_event(eid, None, {"last_call": ""})
    assert engine.snapshot(eid)["last_call"] is None
    add(engine, blake)


def test_last_call_setting_is_validated(engine):
    with pytest.raises(EngineError):
        engine.create_event("Bad", {"last_call": "25:99"})
    assert engine.create_event("Ok", {"last_call": "1:30"})["config"]["last_call"] == "01:30"
