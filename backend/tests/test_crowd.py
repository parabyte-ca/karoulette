"""Likes, song suggestions and awards."""
import pytest

from app.engine import EngineError

from .conftest import add, play_all, singer_order, video


def test_likes_show_but_never_reorder(engine, make_event):
    ev, (alex, blake, casey) = make_event()
    items = [add(engine, g) for g in (alex, blake, casey)]
    before = singer_order(engine, ev)
    assert engine.toggle_like(alex["id"], items[2]["id"]) == {"liked": True, "likes": 1}
    engine.toggle_like(blake["id"], items[2]["id"])
    snap = engine.snapshot(ev)
    casey_item = next(q for q in snap["queue"] if q["id"] == items[2]["id"])
    assert casey_item["likes"] == 2 and casey_item["liked_by"] == [alex["id"], blake["id"]]
    assert singer_order(engine, ev) == before
    assert engine.toggle_like(alex["id"], items[2]["id"]) == {"liked": False, "likes": 1}
    with pytest.raises(EngineError, match="your own"):
        engine.toggle_like(alex["id"], items[0]["id"])


def test_most_loved_in_the_recap(engine, make_event):
    ev, (alex, blake, casey) = make_event()
    a, b = add(engine, alex), add(engine, blake)
    engine.toggle_like(casey["id"], b["id"])
    engine.toggle_like(alex["id"], b["id"])
    engine.toggle_like(blake["id"], a["id"])
    play_all(engine, ev)
    engine.end_event(ev)
    loved = engine.recap(ev)["most_loved"]
    assert loved["singer"] == "Blake" and loved["likes"] == 2


def test_suggest_a_song_then_add_or_dismiss(engine, make_event):
    ev, (alex, blake, _) = make_event()
    r = engine.suggest_song(alex["id"], blake["id"], video(901))
    msgs = engine.drain()
    assert any(m["message"]["type"] == "song_request" and m["guest_id"] == blake["id"] for m in msgs)
    with pytest.raises(EngineError, match="already suggested"):
        engine.suggest_song(alex["id"], blake["id"], video(901))
    with pytest.raises(EngineError, match="Suggestions are for someone else"):
        engine.suggest_song(alex["id"], alex["id"], video(902))
    assert [s["from"] for s in engine.song_requests_for(blake["id"])] == ["Alex"]

    item = engine.accept_request(blake["id"], r["id"])
    assert item["guest_id"] == blake["id"] and item["video_id"] == video(901)["video_id"]
    notes = [m for m in engine.drain() if m["message"]["type"] == "notice" and m["guest_id"] == alex["id"]]
    assert "added your suggestion" in notes[0]["message"]["data"]["text"]
    assert engine.song_requests_for(blake["id"]) == []
    with pytest.raises(EngineError, match="already been handled"):
        engine.accept_request(blake["id"], r["id"])

    r2 = engine.suggest_song(alex["id"], blake["id"], video(903))
    with pytest.raises(EngineError, match="already been handled"):
        engine.dismiss_request(alex["id"], r2["id"])  # only Blake can
    engine.dismiss_request(blake["id"], r2["id"])
    assert engine.song_requests_for(blake["id"]) == []


def test_suggestions_are_capped_per_pair(engine, make_event):
    ev, (alex, blake, _) = make_event()
    for n in range(3):
        engine.suggest_song(alex["id"], blake["id"], video(910 + n))
    with pytest.raises(EngineError, match="Give them a moment"):
        engine.suggest_song(alex["id"], blake["id"], video(913))


def night(engine, clock, names, songs_each=1, cheers=None):
    """Run a whole event: everyone in ``names`` sings ``songs_each`` songs; returns (event id, guests)."""
    ev = engine.create_event(f"Night {clock.now:.0f}", {"superset_chance": 0.0, "autoplay": False})
    guests = [engine.join(ev["id"], n)[0] for n in names]
    engine.start_event(ev["id"])
    for _ in range(songs_each):
        for g in guests:
            add(engine, g)
    for name, n in (cheers or {}).items():
        g = next(g for g in guests if g["display_name"] == name)
        item = engine.db.one("SELECT id FROM queue_items WHERE guest_id = ? LIMIT 1", (g["id"],))
        engine.db.execute("UPDATE queue_items SET cheers = ? WHERE id = ?", (n, item["id"]))
    play_all(engine, ev["id"])
    engine.end_event(ev["id"])
    engine.drain()
    clock.advance(7 * 86400)
    return ev["id"], guests


def test_awards_regulars_streaks_records_and_firsts(engine, clock):
    night(engine, clock, ["Alex", "Blake"])
    night(engine, clock, ["Alex", "Blake", "Casey"], cheers={"Casey": 9})
    last, guests = night(engine, clock, ["alex ", "Casey", "Dana"], songs_each=2)
    a = engine.awards()
    assert a["nights"] == 3
    assert a["regulars"][0] == {"name": "Alex", "nights": 3}
    assert a["perfect_attendance"] == ["Alex"]
    assert a["streaks"] == [{"name": "Alex", "nights": 3}]
    rec = {r["award"]: r for r in a["records"]}
    assert rec["Most songs ever"]["holder"] == "Alex" and rec["Most cheers ever"]["holder"] == "Casey"
    assert rec["Most songs in one night"]["value"].startswith("2 songs")
    assert any(r["award"].startswith("Crowd favourite of") for r in a["records"])
    assert a["newcomers"][0]["name"] == "Dana"

    badges = engine.event_awards(last)
    assert badges["first_nights"] == ["Dana"]
    assert "Alex: 3 nights in a row" in badges["milestones"]
    assert engine.recap(last)["awards"] == badges

    alex = next(g for g in guests if g["display_name"] == "alex")
    mine = engine.personal_awards(alex["id"])
    assert mine["name"] == "Alex" and mine["nights"] == 3 and mine["songs"] == 4 and mine["streak"] == 3
    assert "New personal best: 2 songs in one night!" in mine["tonight"]
    dana = next(g for g in guests if g["display_name"] == "Dana")
    assert engine.personal_awards(dana["id"])["tonight"][0].startswith("First night!")


def test_awards_with_no_history(engine):
    assert engine.awards() == {"nights": 0, "regulars": [], "perfect_attendance": [], "streaks": [],
                               "records": [], "newcomers": []}


def test_like_suggest_and_awards_endpoints(client):
    assert client.post("/api/host/login", json={"pin": "4321"}).status_code == 200
    ev = client.post("/api/host/events", json={"name": "Fri", "config": {"superset_chance": 0, "autoplay": False}}).json()
    a = client.post("/api/guest/join", json={"code": ev["join_code"], "name": "Alex"}).json()
    b = client.post("/api/guest/join", json={"code": ev["join_code"], "name": "Blake"}).json()
    ha, hb = ({"Authorization": f"Bearer {g['token']}"} for g in (a, b))
    blake_id = b["guest"]["id"]
    assert client.post("/api/guest/suggest", json={"to_guest_id": blake_id, "video_id": "blockedvid0"},
                       headers=ha).status_code == 422
    assert client.post("/api/guest/suggest", json={"to_guest_id": blake_id, "video_id": "abcdefghij2"},
                       headers=ha).json()["to"] == "Blake"
    [req] = client.get("/api/guest/suggestions", headers=hb).json()
    assert req["from"] == "Alex" and req["title"] == "Test Song"
    item = client.post(f"/api/guest/suggestions/{req['id']}/add", headers=hb).json()["item_id"]
    assert client.get("/api/guest/suggestions", headers=hb).json() == []

    assert client.post(f"/api/guest/like/{item}", headers=ha).json() == {"liked": True, "likes": 1}
    assert client.post(f"/api/guest/like/{item}", headers=hb).status_code == 400  # your own song
    assert client.get("/api/guest/awards", headers=ha).json() == {"awards": None}  # nothing sung yet
    assert client.get("/api/public/history").json()["awards"]["nights"] == 0
