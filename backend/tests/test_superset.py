import random

import pytest

from app import logic
from app.engine import EngineError
from tests.conftest import to_choosing, video


def test_roll_superset_chance_and_overrides():
    rng = random.Random(0)
    hits = sum(logic.roll_superset(0.15, None, rng) for _ in range(10_000))
    assert 1200 < hits < 1800
    assert logic.roll_superset(0.0, "force", rng) is True
    assert logic.roll_superset(1.0, "cancel", rng) is False


def _turn_themes(engine, clock, eid, guests, turns):
    themes = []
    for i in range(turns):
        ev = to_choosing(engine, clock)
        turn = engine._turn(ev["current_turn_id"])
        themes.append((turn["guest_id"], turn["theme_id"], ev["current_round"]))
        engine.queue_song(turn["guest_id"], video(i + 1))
    return themes


def test_superset_round_locks_one_theme(engine, clock, make_event):
    eid, guests = make_event(superset_chance=1.0)
    themes = _turn_themes(engine, clock, eid, guests, 3)
    assert len({t[1] for t in themes}) == 1
    rnd = engine.db.one("SELECT * FROM rounds WHERE event_id = ? AND number = 1", (eid,))
    assert rnd["is_superset"] and rnd["superset_theme_id"] == themes[0][1]


def test_superset_only_spins_once_per_round(engine, clock, make_event):
    eid, guests = make_event(superset_chance=1.0)
    spins = 0
    for i in range(3):
        ev = to_choosing(engine, clock)
        spins += sum(1 for m in engine.drain() if m["message"]["type"] == "theme_spun")
        engine.queue_song(engine._turn(ev["current_turn_id"])["guest_id"], video(i))
    assert spins == 1


def test_normal_round_spins_per_turn_without_back_to_back_repeat(engine, clock, make_event):
    eid, guests = make_event(superset_chance=0.0)
    themes = _turn_themes(engine, clock, eid, guests, 9)
    ids = [t[1] for t in themes]
    assert all(a != b for a, b in zip(ids, ids[1:]))
    assert not any(engine.db.one("SELECT MAX(is_superset) AS m FROM rounds")["m"] for _ in [0])


def test_force_superset_applies_next_round(engine, clock, make_event):
    eid, guests = make_event(superset_chance=0.0)
    engine.force_superset(eid)
    themes = _turn_themes(engine, clock, eid, guests, 6)
    round1 = [t for t in themes if t[2] == 1]
    round2 = [t for t in themes if t[2] == 2]
    # Round 1 had already started when forced, so round 2 is the superset.
    assert not engine.db.one("SELECT is_superset FROM rounds WHERE number = 1")["is_superset"]
    assert engine.db.one("SELECT is_superset FROM rounds WHERE number = 2")["is_superset"]
    assert len({t[1] for t in round2}) == 1
    assert len(round1) == 3


def test_cancel_pending_superset(engine, clock, make_event):
    eid, guests = make_event(superset_chance=0.0)
    engine.force_superset(eid)
    engine.cancel_superset(eid)
    _turn_themes(engine, clock, eid, guests, 4)
    assert engine.db.one("SELECT MAX(is_superset) AS m FROM rounds")["m"] == 0


def test_cancel_running_superset_reverts_to_per_turn(engine, clock, make_event):
    eid, guests = make_event(superset_chance=1.0)
    _turn_themes(engine, clock, eid, guests, 1)
    engine.cancel_superset(eid)
    assert not engine._round(engine.get_event(eid)["current_round_id"])["is_superset"]


def test_cancel_with_nothing_pending_blocks_next_roll(engine, clock, make_event):
    eid, guests = make_event(superset_chance=1.0)
    engine.update_event(eid, None, {"superset_chance": 0.0})
    engine.update_event(eid, None, {"superset_chance": 1.0})
    # round 1 is already a superset (chance was 1.0 at start); cancel ends it
    engine.cancel_superset(eid)
    engine.cancel_superset(eid)  # nothing running now -> blocks the next roll
    _turn_themes(engine, clock, eid, guests, 4)
    assert not engine.db.one("SELECT is_superset FROM rounds WHERE number = 2")["is_superset"]


def test_flagging_only_in_superset(engine, clock, make_event):
    eid, guests = make_event(superset_chance=1.0)
    to_choosing(engine, clock)
    item = engine.queue_song(guests[0]["id"], video(1))
    assert engine.flag_item(eid, item["id"], f"guest:{guests[1]['id']}") == 1
    assert engine.flag_item(eid, item["id"], f"guest:{guests[1]['id']}") == 1  # idempotent
    assert engine.flag_item(eid, item["id"], "host") == 2
    with pytest.raises(EngineError):
        engine.flag_item(eid, item["id"], f"guest:{guests[0]['id']}")


def test_flagging_rejected_outside_superset(engine, clock, make_event):
    eid, guests = make_event(superset_chance=0.0)
    to_choosing(engine, clock)
    item = engine.queue_song(guests[0]["id"], video(1))
    with pytest.raises(EngineError):
        engine.flag_item(eid, item["id"], "host")


def test_superset_snapshot_shows_banner_theme(engine, clock, make_event):
    eid, guests = make_event(superset_chance=1.0)
    to_choosing(engine, clock)
    snap = engine.snapshot(eid)
    assert snap["round"]["is_superset"] and snap["round"]["theme"]["name"]
