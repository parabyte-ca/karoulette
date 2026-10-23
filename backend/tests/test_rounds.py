"""Rounds: one theme spin per pass through the singer order, with Supersets."""
import random

import pytest

from app import logic
from app.engine import EngineError
from tests.conftest import add, play_all


def test_roll_superset_chance():
    rng = random.Random(0)
    hits = sum(logic.roll_superset(0.15, rng) for _ in range(10_000))
    assert 1200 < hits < 1800
    assert not any(logic.roll_superset(0.0, rng) for _ in range(1000))


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


def test_themes_are_off_by_default_and_can_be_switched_on(engine):
    ev = engine.create_event("Free night")
    assert ev["config"]["themes_enabled"] is False and ev["config"]["superset_chance"] == 0
    engine.join(ev["id"], "Alex")
    engine.start_event(ev["id"])
    snap = engine.snapshot(ev["id"])
    assert snap["round"]["number"] == 1 and snap["round"]["theme"] is None
    assert not [m for m in engine.drain() if m["message"]["type"] == "theme_spun"]
    with pytest.raises(EngineError):
        engine.force_spin(ev["id"])
    engine.update_event(ev["id"], None, {"themes_enabled": True})  # on mid-event: this round spins now
    assert engine.snapshot(ev["id"])["round"]["theme"]["name"]
    assert any(m["message"]["type"] == "theme_spun" for m in engine.drain())


def test_events_from_before_the_switch_keep_their_themes(engine):
    eid = engine.db.insert("INSERT INTO events(name, join_code, config, created_at) VALUES ('Old', 'OLD01', ?, 0)",
                           ('{"superset_chance": 0.15}',))
    engine.upgrade_event_configs()
    assert engine.get_event(eid)["config"]["themes_enabled"] is True
    assert engine.create_event("New")["config"]["themes_enabled"] is False
