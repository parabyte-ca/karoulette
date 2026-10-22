"""Rounds: one theme spin per pass through the singer order, with Supersets."""
import random

import pytest

from app import logic
from app.engine import EngineError
from tests.conftest import add, play_all


def test_roll_superset_chance_and_overrides():
    rng = random.Random(0)
    hits = sum(logic.roll_superset(0.15, None, rng) for _ in range(10_000))
    assert 1200 < hits < 1800
    assert logic.roll_superset(0.0, "force", rng) is True
    assert logic.roll_superset(1.0, "cancel", rng) is False


def test_theme_never_repeats_back_to_back():
    themes = [{"id": i, "name": str(i), "weight": 1, "enabled": True} for i in (1, 2)]
    rng = random.Random(1)
    history = [1]
    for _ in range(50):
        t = logic.pick_theme(themes, history, window=0, rng=rng)
        assert t["id"] != history[-1]
        history.append(t["id"])


def test_theme_respects_enabled_and_weight():
    themes = [{"id": 1, "name": "a", "weight": 1, "enabled": False},
              {"id": 2, "name": "b", "weight": 0, "enabled": True},
              {"id": 3, "name": "c", "weight": 1, "enabled": True}]
    assert logic.pick_theme(themes, [], 0, random.Random())["id"] == 3
    assert logic.pick_theme([themes[0]], [], 0, random.Random()) is None


def _rounds(engine, eid):
    return engine.db.all("SELECT * FROM rounds WHERE event_id = ? ORDER BY number", (eid,))


def test_start_spins_round_one(engine, make_event):
    eid, _ = make_event(start=False)
    engine.drain()
    engine.start_event(eid)
    msgs = engine.drain()
    spun = [m for m in msgs if m["message"]["type"] == "theme_spun"]
    assert len(spun) == 1 and spun[0]["message"]["data"]["round"] == 1
    snap = engine.snapshot(eid)
    assert snap["round"]["number"] == 1 and snap["round"]["theme"]["name"] and snap["round"]["spun_at"]


def test_one_spin_per_round_and_no_repeats(engine, make_event):
    eid, (a, b, c) = make_event()
    for _ in range(4):
        for p in (a, b, c):
            add(engine, p)
    engine.drain()
    play_all(engine, eid)
    spins = [m for m in engine.drain() if m["message"]["type"] == "theme_spun"]
    assert [m["message"]["data"]["round"] for m in spins] == [2, 3, 4]
    themes = [r["theme_id"] for r in _rounds(engine, eid)]
    assert len(themes) == 4 and all(x != y for x, y in zip(themes, themes[1:]))
    # Every song is tagged with the theme of the round it was sung in.
    tagged = engine.db.all("SELECT q.theme_name, r.theme_name AS rt FROM queue_items q "
                           "JOIN rounds r ON r.id = q.round_id WHERE q.event_id = ?", (eid,))
    assert len(tagged) == 12 and all(t["theme_name"] == t["rt"] for t in tagged)


def test_force_spin_respins_current_round(engine, make_event):
    eid, _ = make_event()
    before = _rounds(engine, eid)[0]["theme_id"]
    engine.drain()
    engine.force_spin(eid)
    assert any(m["message"]["type"] == "theme_spun" for m in engine.drain())
    assert _rounds(engine, eid)[0]["theme_id"] != before


def test_force_spin_needs_a_round(engine, make_event):
    eid, _ = make_event(start=False)
    with pytest.raises(EngineError):
        engine.force_spin(eid)


def test_superset_round(engine, make_event):
    eid, (a, b) = make_event(names=("Alex", "Blake"), superset_chance=1.0)
    rnd = _rounds(engine, eid)[0]
    assert rnd["is_superset"] and rnd["superset_theme_id"] == rnd["theme_id"]
    s1 = add(engine, a)
    add(engine, b)
    later = add(engine, a)  # round 2
    snap = engine.snapshot(eid)
    assert snap["round"]["is_superset"]
    flags = {q["id"]: q["is_superset"] for q in snap["queue"]}
    assert flags[s1["id"]] and not flags[later["id"]]
    assert engine.flag_item(eid, s1["id"], f"guest:{b['id']}") == 1
    assert engine.flag_item(eid, s1["id"], f"guest:{b['id']}") == 1  # idempotent
    assert engine.flag_item(eid, s1["id"], "host") == 2
    with pytest.raises(EngineError):
        engine.flag_item(eid, s1["id"], f"guest:{a['id']}")
    with pytest.raises(EngineError):
        engine.flag_item(eid, later["id"], "host")


def test_force_and_cancel_superset(engine, make_event):
    eid, (a, b) = make_event(names=("Alex", "Blake"))
    engine.force_superset(eid)
    for _ in range(2):
        add(engine, a)
        add(engine, b)
    play_all(engine, eid)
    r = _rounds(engine, eid)
    assert not r[0]["is_superset"] and r[1]["is_superset"]
    engine.cancel_superset(eid)          # ends the running Superset
    assert not _rounds(engine, eid)[1]["is_superset"]
    engine.cancel_superset(eid)          # nothing running: blocks the next roll
    assert engine.get_event(eid)["superset_pending"] == "cancel"
