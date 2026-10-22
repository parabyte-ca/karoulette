"""Playback, queue housekeeping and persistence."""
import random

import pytest

from app.db import Database
from app.engine import Engine, EngineError
from tests.conftest import add, play_all, singer_order, video


def test_autoplay_starts_when_first_song_added(engine, make_event):
    eid, (a, b) = make_event(names=("Alex", "Blake"), autoplay=True)
    item = add(engine, a)
    assert engine.get_event(eid)["now_playing_item_id"] == item["id"]


def test_songs_can_be_queued_before_start(engine, make_event):
    eid, (a, b) = make_event(names=("Alex", "Blake"), start=False, autoplay=True)
    add(engine, b)
    add(engine, a)
    assert not engine.get_event(eid)["now_playing_item_id"]
    engine.start_event(eid)
    assert singer_order(engine, eid) == ["Alex", "Blake"]


def test_player_ended_ignores_stale_reports(engine, make_event):
    eid, (a, b) = make_event(names=("Alex", "Blake"))
    first = add(engine, a)
    second = add(engine, b)
    engine.play_next(eid)
    engine.player_ended(eid, first["id"])
    engine.player_ended(eid, first["id"])
    assert engine.get_event(eid)["now_playing_item_id"] == second["id"]


def test_host_play_next(engine, make_event):
    eid, (a, b, c) = make_event()
    for p in (a, b, c):
        add(engine, p)
    last = engine.snapshot(eid)["queue"][-1]
    engine.play_item_next(eid, last["id"])
    assert singer_order(engine, eid) == ["Casey", "Alex", "Blake"]


def test_embed_error_gives_singer_a_front_of_queue_repick(engine, make_event):
    eid, (a, b, c) = make_event()
    bad = add(engine, a)
    for p in (b, c):
        add(engine, p)
    engine.play_next(eid)
    engine.drain()
    engine.player_error(eid, bad["id"], 150)
    msgs = engine.drain()
    assert any(m["message"]["type"] == "song_error" and m["guest_id"] == a["id"] for m in msgs)
    assert singer_order(engine, eid) == ["Blake", "Casey"]
    add(engine, a)
    assert singer_order(engine, eid) == ["Blake", "Alex", "Casey"]
    assert not engine._guest(a["id"])["repick_credit"]


def test_duplicates_and_duration(engine, make_event):
    eid, (a, b) = make_event(names=("Alex", "Blake"), max_duration_s=120)
    with pytest.raises(EngineError):
        add(engine, a)  # 200 s > 120 s limit
    engine.update_event(eid, None, {"max_duration_s": 0})
    add(engine, a, 7)
    with pytest.raises(EngineError):
        add(engine, b, 7)
    engine.update_event(eid, None, {"prevent_duplicates": False})
    add(engine, b, 7)


def test_ended_event_rejects_songs(engine, make_event):
    eid, (a, b) = make_event(names=("Alex", "Blake"))
    add(engine, a)
    engine.end_event(eid)
    ev = engine.get_event(eid)
    assert ev["status"] == "ended" and not ev["now_playing_item_id"]
    with pytest.raises(EngineError):
        add(engine, b)
    with pytest.raises(EngineError):
        engine.join(eid, "Late")


def test_history_csv(engine, make_event):
    eid, (a, b) = make_event(names=("Alex", "Blake"))
    add(engine, a)
    add(engine, b)
    play_all(engine, eid)
    lines = engine.history_csv(eid).strip().splitlines()
    assert lines[0].startswith("event,played_at_utc,round")
    assert "Alex" in lines[1] and lines[1].split(",")[2] == "1"


def test_restart_resumes_state(tmp_path, clock):
    path = tmp_path / "kq.db"
    e1 = Engine(Database(path), clock=clock, rng=random.Random(1))
    e1.seed_themes()
    ev = e1.create_event("Persist", {"superset_chance": 0, "autoplay": False})
    a, _ = e1.join(ev["id"], "A")
    b, _ = e1.join(ev["id"], "B")
    e1.start_event(ev["id"])
    for p in (a, b, a):
        e1.queue_song(p["id"], video())
    e1.play_next(ev["id"])
    e1.db.close()
    e2 = Engine(Database(path), clock=clock, rng=random.Random(1))
    snap = e2.snapshot(ev["id"])
    assert snap["now_playing"]["guest_name"] == "A"
    assert [q["guest_name"] for q in snap["queue"]] == ["B", "A"]


def test_old_database_gets_new_columns(tmp_path):
    from app.db import ADDED_COLUMNS
    path = tmp_path / "old.db"
    old = Database(path)
    for table, column, _ in ADDED_COLUMNS:  # turn it into a pre-0.6.0 database
        old.execute(f"ALTER TABLE {table} DROP COLUMN {column}")
    assert "round_no" not in {r["name"] for r in old.all("PRAGMA table_info(queue_items)")}
    old.close()
    db = Database(path)
    for table, column, _ in ADDED_COLUMNS:
        assert column in {r["name"] for r in db.all(f"PRAGMA table_info({table})")}
