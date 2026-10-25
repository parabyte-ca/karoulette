"""Returning singers: singer codes, same-phone claims, honour claims by name, disputes and host tools (v0.13.0)."""
import pytest

from app.engine import EngineError, hash_token
from tests.conftest import add
from tests.test_api import login


def night(engine, make_event, names, end=True):
    eid, guests = make_event(names=names)
    for g in guests:
        add(engine, g)
    engine.play_next(eid)
    while engine.get_event(eid)["now_playing_item_id"]:
        engine.player_ended(eid, engine.get_event(eid)["now_playing_item_id"])
    if end:
        engine.end_event(eid)
    return eid, guests


def test_first_join_makes_a_code_and_the_phone_brings_it_back(engine, make_event):
    eid, (alan,) = make_event(names=("Alan",))
    first = engine.attach_singer(alan["id"])
    assert first["new"] and len(first["singer"]["code"]) == 6
    eid2, (alan2,) = make_event(names=("Alan G",))
    again = engine.attach_singer(alan2["id"], first["singer"]["code"])
    assert not again["new"] and again["singer"]["nights"] == 2 and again["singer"]["name"] == "Alan G"


def test_same_phone_claims_its_past_nights(engine, make_event):
    _, (old,) = night(engine, make_event, ("Al",))
    token = "old-phone-token"
    engine.db.execute("UPDATE guests SET token_hash = ? WHERE id = ?", (hash_token(token), old["id"]))
    _, (now,) = make_event(names=("Alan",))
    res = engine.attach_singer(now["id"], known_tokens=[token, "unknown"])
    assert res["claimed"] == 1 and res["singer"]["nights"] == 2


def test_honour_claim_takes_the_name_group_and_first_claim_wins(engine, make_event):
    night(engine, make_event, ("Alan", "Beth"))
    night(engine, make_event, ("alan ", "Casey"))                # same name group, another night
    _, (me,) = make_event(names=("Alan",))
    mine = engine.attach_singer(me["id"])["singer"]["code"]
    names = {g["name"]: g for g in engine.claimable_names(mine)}
    assert names["Alan"]["nights"] == 3 and names["Alan"]["free"] == 2
    assert engine.claim_names(mine, ["Alan"])["claimed"] == 3      # tonight's was already mine
    _, (other,) = make_event(names=("Other Alan",))
    theirs = engine.attach_singer(other["id"])["singer"]["code"]
    res = engine.claim_names(theirs, ["alan"])
    assert res == {**res, "claimed": 0, "disputed": 3}              # mine stay mine; the host decides
    admin = engine.singers_admin()
    assert len(admin["disputes"]) == 3 and admin["disputes"][0]["owner_code"] == mine


def test_host_decides_disputes_and_moves_nights(engine, make_event):
    _, (alan, beth) = night(engine, make_event, ("Alan", "Beth"))
    _, (a1,) = make_event(names=("A1",))
    _, (a2,) = make_event(names=("A2",))
    first = engine.attach_singer(a1["id"])["singer"]["code"]
    second = engine.attach_singer(a2["id"])["singer"]["code"]
    engine.claim_names(first, ["Alan"])
    engine.claim_names(second, ["Alan"])                            # dispute
    claim = engine.singers_admin()["disputes"][0]
    after = engine.decide_claim(claim["id"], True)
    owner = next(s for s in after["singers"] if s["code"] == second)
    assert any(n["guest_id"] == alan["id"] for n in owner["nights"]) and not after["disputes"]
    with pytest.raises(EngineError):
        engine.decide_claim(claim["id"], False)                     # already decided
    sid = next(s["id"] for s in after["singers"] if s["code"] == first)
    engine.assign_night(beth["id"], sid)                            # the host can attach any night
    engine.assign_night(alan["id"], None)                           # or unclaim one
    admin = engine.singers_admin()
    assert any(n["guest_id"] == alan["id"] for n in admin["unclaimed"])
    old_code = next(s["code"] for s in admin["singers"] if s["id"] == sid)
    engine.reset_singer_code(sid)
    assert next(s["code"] for s in engine.singers_admin()["singers"] if s["id"] == sid) != old_code
    _, (later,) = make_event(names=("A1 again",))
    assert engine.attach_singer(later["id"], old_code)["code_invalid"]


def test_history_groups_by_singer_and_past_songs(engine, make_event):
    night(engine, make_event, ("Al",))
    _, (me,) = make_event(names=("Alan",))
    code = engine.attach_singer(me["id"])["singer"]["code"]
    engine.claim_names(code, ["Al"])
    assert {s["singer_group"] for s in engine.history()["songs"]} == {"Alan"}   # Al's song counts as Alan's
    past = engine.past_songs(code)
    assert len(past) == 1 and past[0]["times"] == 1


def test_singer_endpoints(client):
    login(client)
    ev = client.post("/api/host/events", json={"name": "Code Night"}).json()
    joined = client.post("/api/guest/join", json={"code": ev["join_code"], "name": "Alex"}).json()
    code = joined["singer"]["code"]
    assert joined["new"] and len(code) == 6
    auth = {"Authorization": f"Bearer {joined['token']}"}
    assert client.get("/api/guest/me", headers=auth).json()["singer"]["code"] == code
    assert client.post("/api/public/singer-check", json={"code": code}).json()["name"] == "Alex"
    assert client.post("/api/public/singer-check", json={"code": "ZZZZZZ"}).status_code == 404
    assert client.get("/api/guest/claimable", headers=auth).json()[0]["name"] == "Alex"
    # A second phone with the code: tonight moves to the same singer.
    other = client.post("/api/guest/join", json={"code": ev["join_code"], "name": "Alex 2"}).json()
    moved = client.post("/api/guest/singer-code", headers={"Authorization": f"Bearer {other['token']}"},
                        json={"code": code}).json()
    assert moved["singer"]["code"] == code and moved["singer"]["nights"] == 2
    admin = client.get("/api/host/singers").json()
    assert [s["code"] for s in admin["singers"]] == [code]          # the spare code went
    client.cookies.clear()
    assert client.get("/api/host/singers").status_code == 401


def test_host_name_merges_still_apply_to_singers(engine, make_event):
    _, (al,) = make_event(names=("Al",))
    _, (alan,) = make_event(names=("Alan",))
    engine.attach_singer(al["id"])
    engine.attach_singer(alan["id"])                                # two phones, two codes
    add(engine, al)
    add(engine, alan)
    for eid in (al["event_id"], alan["event_id"]):
        engine.play_next(eid)
        engine.player_ended(eid, engine.get_event(eid)["now_playing_item_id"])
    engine.merge_singers(["Al"], "Alan")
    assert {s["singer_group"] for s in engine.history()["songs"]} == {"Alan"}
