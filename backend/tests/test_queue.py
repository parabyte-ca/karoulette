import pytest

from app import logic
from app.engine import EngineError
from tests.conftest import to_choosing, video


def items(*ids_positions, status="queued"):
    return [{"id": i, "position": p, "status": status, "video_id": f"v{i}"} for i, p in ids_positions]


def test_play_order_by_position_then_id():
    order = logic.play_order(items((3, 1.0), (1, 2.0), (2, 1.0)) + items((9, 0.0), status="played"))
    assert [i["id"] for i in order] == [2, 3, 1]


def test_move_item():
    assert logic.move_item([1, 2, 3, 4], 4, 0) == [4, 1, 2, 3]
    assert logic.move_item([1, 2, 3, 4], 1, 99) == [2, 3, 4, 1]
    with pytest.raises(ValueError):
        logic.move_item([1, 2], 7, 0)


def test_duplicate_detection():
    data = items((1, 1.0)) + [{"id": 2, "position": 0, "status": "removed", "video_id": "dupe"}]
    assert logic.is_duplicate(data, "v1")
    assert not logic.is_duplicate(data, "dupe")


def _fill(engine, clock, n, start=1):
    out = []
    for i in range(n):
        ev = to_choosing(engine, clock)
        gid = engine._turn(ev["current_turn_id"])["guest_id"]
        out.append(engine.queue_song(gid, video(start + i)))
    return out


def test_queue_is_fifo_and_autoplays(engine, clock, make_event):
    eid, guests = make_event()
    queued = _fill(engine, clock, 3)
    snap = engine.snapshot(eid)
    assert snap["now_playing"]["id"] == queued[0]["id"]
    assert [q["id"] for q in snap["queue"]] == [queued[1]["id"], queued[2]["id"]]


def test_player_ended_advances_and_ignores_stale(engine, clock, make_event):
    eid, guests = make_event()
    queued = _fill(engine, clock, 3)
    engine.player_ended(eid, queued[0]["id"])
    engine.player_ended(eid, queued[0]["id"])  # duplicate report from a second tab
    assert engine.get_event(eid)["now_playing_item_id"] == queued[1]["id"]
    assert engine.db.one("SELECT status FROM queue_items WHERE id = ?", (queued[0]["id"],))["status"] == "played"


def test_reorder_and_move(engine, clock, make_event):
    eid, guests = make_event(autoplay=False)
    queued = _fill(engine, clock, 3)
    ids = [q["id"] for q in queued]
    engine.move_item(eid, ids[2], 0)
    assert [q["id"] for q in engine.snapshot(eid)["queue"]] == [ids[2], ids[0], ids[1]]
    engine.reorder(eid, [ids[1], ids[0], ids[2]])
    assert [q["id"] for q in engine.snapshot(eid)["queue"]] == [ids[1], ids[0], ids[2]]
    with pytest.raises(EngineError):
        engine.reorder(eid, [ids[0]])


def test_remove_item(engine, clock, make_event):
    eid, guests = make_event(autoplay=False)
    queued = _fill(engine, clock, 2)
    engine.remove_item(eid, queued[0]["id"])
    assert [q["id"] for q in engine.snapshot(eid)["queue"]] == [queued[1]["id"]]
    with pytest.raises(EngineError):
        engine.remove_item(eid, queued[1]["id"], by_guest_id=guests[0]["id"])


def test_duplicates_blocked_when_enabled(engine, clock, make_event):
    eid, guests = make_event(prevent_duplicates=True)
    _fill(engine, clock, 1)
    to_choosing(engine, clock)
    with pytest.raises(EngineError):
        engine.queue_song(guests[1]["id"], video(1))


def test_duplicates_allowed_when_disabled(engine, clock, make_event):
    eid, guests = make_event(prevent_duplicates=False)
    _fill(engine, clock, 1)
    to_choosing(engine, clock)
    engine.queue_song(guests[1]["id"], video(1))


def test_cannot_queue_out_of_turn(engine, clock, make_event):
    eid, guests = make_event()
    to_choosing(engine, clock)
    with pytest.raises(EngineError):
        engine.queue_song(guests[1]["id"], video(1))


def test_max_duration(engine, clock, make_event):
    eid, guests = make_event(max_duration_s=120)
    to_choosing(engine, clock)
    with pytest.raises(EngineError):
        engine.queue_song(guests[0]["id"], video(1))


def test_embed_error_skips_and_grants_bonus_repick(engine, clock, make_event):
    eid, guests = make_event()
    queued = _fill(engine, clock, 2)  # Alex playing, Blake queued; Casey is up
    engine.drain()
    engine.player_error(eid, queued[0]["id"], 150)
    msgs = engine.drain()
    assert any(m["message"]["type"] == "song_error" and m["guest_id"] == guests[0]["id"] for m in msgs)
    assert engine.get_event(eid)["now_playing_item_id"] == queued[1]["id"]
    # Casey finishes the current turn, then Alex gets the bonus turn before rotation resumes.
    ev = to_choosing(engine, clock)
    assert engine._turn(ev["current_turn_id"])["guest_id"] == guests[2]["id"]
    engine.queue_song(guests[2]["id"], video(3))
    ev = engine.get_event(eid)
    turn = engine._turn(ev["current_turn_id"])
    assert turn["guest_id"] == guests[0]["id"] and turn["is_bonus"]
    assert turn["theme_id"] == engine.db.one("SELECT theme_id FROM turns WHERE id = ?",
                                              (queued[0]["turn_id"],))["theme_id"]
    to_choosing(engine, clock)
    engine.queue_song(guests[0]["id"], video(4))
    # After the bonus, the rotation carries on: Alex's regular turn opens round 2.
    ev = engine.get_event(eid)
    turn = engine._turn(ev["current_turn_id"])
    assert turn["guest_id"] == guests[0]["id"] and not turn["is_bonus"]
    assert ev["current_round"] == 2


def test_leaving_removes_queued_songs(engine, clock, make_event):
    eid, guests = make_event(autoplay=False)
    queued = _fill(engine, clock, 2)
    engine.leave(guests[1]["id"])
    assert [q["id"] for q in engine.snapshot(eid)["queue"]] == [queued[0]["id"]]


def test_history_csv(engine, clock, make_event):
    eid, guests = make_event()
    queued = _fill(engine, clock, 2)
    engine.player_ended(eid, queued[0]["id"])
    csv_text = engine.history_csv(eid)
    lines = csv_text.strip().splitlines()
    assert lines[0].startswith("event,played_at_utc")
    assert "Song 1" in lines[1] and "Alex" in lines[1]


def test_end_event_stops_everything(engine, clock, make_event):
    eid, guests = make_event()
    _fill(engine, clock, 2)
    engine.end_event(eid)
    ev = engine.get_event(eid)
    assert ev["status"] == "ended" and ev["turn_state"] == "idle" and not ev["now_playing_item_id"]
    with pytest.raises(EngineError):
        engine.join(eid, "Late")


def test_restart_resumes_state(tmp_path, clock):
    import random
    from app.db import Database
    from app.engine import Engine
    path = tmp_path / "kq.db"
    e1 = Engine(Database(path), clock=clock, rng=random.Random(1))
    e1.seed_themes()
    ev = e1.create_event("Persist", {"superset_chance": 0})
    a, _ = e1.join(ev["id"], "A")
    e1.join(ev["id"], "B")
    e1.start_event(ev["id"])
    e1.db.close()
    e2 = Engine(Database(path), clock=clock, rng=random.Random(1))
    snap = e2.snapshot(ev["id"])
    assert snap["turn"]["guest_id"] == a["id"] and snap["event"]["status"] == "active"
    clock.advance(100)
    e2.tick()
    assert e2.get_event(ev["id"])["turn_state"] in ("spinning", "choosing")
