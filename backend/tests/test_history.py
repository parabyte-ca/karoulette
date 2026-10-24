"""Song history across events: the list, singer name merging and the public page switch."""
from tests.conftest import add
from tests.test_api import login


def sing(engine, eid, guests):
    for gst in guests:
        add(engine, gst)
    engine.play_next(eid)
    while engine.get_event(eid)["now_playing_item_id"]:
        engine.player_ended(eid, engine.get_event(eid)["now_playing_item_id"])


def test_history_lists_sung_songs_from_every_event(engine, make_event, clock):
    eid, (alan, beth) = make_event(("Alan", "Beth"))
    sing(engine, eid, (alan, beth))
    engine.end_event(eid)
    clock.advance(86400)
    eid2, (alan2, al) = make_event(("alan ", "Al"))
    add(engine, alan2)
    engine.play_next(eid2)
    engine.skip_song(eid2)                       # skipped songs are listed, marked as skipped
    queued = add(engine, al)                     # still waiting: not in the history
    songs = engine.history()["songs"]
    assert [s["status"] for s in songs] == ["skipped", "played", "played"]
    assert all(s["id"] != queued["id"] for s in songs)
    assert {s["singer_group"] for s in songs} == {"Alan", "Beth"}   # "alan " is Alan
    assert {s["event"] for s in songs} == {"Test Night"}
    assert songs[0]["at"] > songs[-1]["at"]      # newest first


def test_merging_and_unmerging_singer_names(engine, make_event):
    eid, (alan, al, beth) = make_event(("Alan", "Al", "Beth"))
    sing(engine, eid, (alan, al, beth))
    names = engine.merge_singers(["Al"], "Alan")
    assert {n["name"]: n["group"] for n in names} == {"Al": "Alan", "Alan": "Alan", "Beth": "Beth"}
    assert {s["singer_group"] for s in engine.history()["songs"]} == {"Alan", "Beth"}
    engine.merge_singers(["Alan", "Beth"], "The Duo")          # merging a group takes its members along
    assert {n["group"] for n in engine.singer_names()} == {"The Duo"}
    engine.unmerge_singer("Beth")
    assert {n["name"]: n["group"] for n in engine.singer_names()} == {"Al": "The Duo", "Alan": "The Duo",
                                                                       "Beth": "Beth"}


def test_history_endpoints(client):
    assert client.get("/api/host/history").status_code == 401
    assert client.get("/api/public/history").json()["songs"] == []      # shared by default
    login(client)
    data = client.get("/api/host/history").json()
    assert data["public"] is True and data["names"] == []
    assert client.post("/api/host/history/merge", json={"names": ["Solo"], "into": "Solo"}).status_code == 400
    client.put("/api/host/history/public", json={"on": False})
    got = client.get("/api/public/history")
    assert got.status_code == 404 and "hasn't shared" in got.json()["detail"]
