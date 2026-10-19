import random

from app import logic
from tests.conftest import to_choosing, video


def g(id_, pos, **kw):
    return {"id": id_, "rotation_pos": pos, "status": "active", **kw}


# ---- pure logic

def test_first_turn_starts_new_round():
    guest, wrapped, skipped = logic.next_in_rotation([g(1, 1), g(2, 2)], None)
    assert guest["id"] == 1 and wrapped and skipped == []


def test_rotation_follows_join_order_and_wraps():
    guests = [g(3, 3), g(1, 1), g(2, 2)]
    assert logic.next_in_rotation(guests, 1)[0]["id"] == 2
    assert logic.next_in_rotation(guests, 2)[0]["id"] == 3
    guest, wrapped, _ = logic.next_in_rotation(guests, 3)
    assert guest["id"] == 1 and wrapped


def test_rotation_skips_inactive_and_flagged_guests():
    guests = [g(1, 1), g(2, 2, status="left"), g(3, 3, skip_next=1), g(4, 4)]
    guest, wrapped, skipped = logic.next_in_rotation(guests, 1)
    assert guest["id"] == 4 and not wrapped and skipped == [3]


def test_all_skipped_still_returns_someone():
    guests = [g(1, 1, skip_next=1), g(2, 2, skip_next=1)]
    guest, _, skipped = logic.next_in_rotation(guests, 1)
    assert guest["id"] == 2 and skipped == [2, 1]


def test_upcoming_order():
    guests = [g(1, 1), g(2, 2), g(3, 3), g(4, 4)]
    assert logic.upcoming_order(guests, 2, exclude_id=2) == [3, 4, 1]


def test_theme_never_repeats_back_to_back():
    themes = [{"id": i, "name": str(i), "weight": 1, "enabled": True} for i in (1, 2)]
    rng = random.Random(1)
    history = [1]
    for _ in range(50):
        t = logic.pick_theme(themes, history, window=0, rng=rng)
        assert t["id"] != history[-1]
        history.append(t["id"])


def test_theme_avoids_recent_window_and_relaxes():
    themes = [{"id": i, "name": str(i), "weight": 1, "enabled": True} for i in (1, 2, 3, 4)]
    rng = random.Random(3)
    for _ in range(30):
        assert logic.pick_theme(themes, [1, 2, 3], window=3, rng=rng)["id"] == 4
    # window larger than list: still never the immediate previous one
    for _ in range(30):
        assert logic.pick_theme(themes, [1, 2, 3, 4], window=10, rng=rng)["id"] != 4


def test_theme_respects_enabled_and_weight():
    themes = [{"id": 1, "name": "a", "weight": 1, "enabled": False},
              {"id": 2, "name": "b", "weight": 0, "enabled": True},
              {"id": 3, "name": "c", "weight": 1, "enabled": True}]
    assert logic.pick_theme(themes, [], 0, random.Random()) ["id"] == 3
    assert logic.pick_theme([themes[0]], [], 0, random.Random()) is None


# ---- engine

def test_engine_rotation_in_join_order(engine, clock, make_event):
    eid, guests = make_event()
    order = []
    for _ in range(6):
        ev = to_choosing(engine, clock)
        turn = engine._turn(ev["current_turn_id"])
        order.append(turn["guest_id"])
        engine.skip_turn(eid)
    ids = [x["id"] for x in guests]
    assert order == ids + ids
    assert engine.get_event(eid)["current_round"] == 3


def test_late_joiner_goes_to_end(engine, clock, make_event):
    eid, guests = make_event(names=("Alex", "Blake"))
    late, _ = engine.join(eid, "Drew")
    ev = to_choosing(engine, clock)
    assert engine._turn(ev["current_turn_id"])["guest_id"] == guests[0]["id"]
    seen = []
    for _ in range(3):
        engine.skip_turn(eid)
        ev = to_choosing(engine, clock)
        seen.append(engine._turn(ev["current_turn_id"])["guest_id"])
    assert seen == [guests[1]["id"], late["id"], guests[0]["id"]]


def test_queueing_a_song_advances_turn(engine, clock, make_event):
    eid, guests = make_event()
    to_choosing(engine, clock)
    engine.queue_song(guests[0]["id"], video(1))
    ev = engine.get_event(eid)
    assert engine._turn(ev["current_turn_id"])["guest_id"] == guests[1]["id"]
    assert ev["turn_state"] == "announcing"


def test_default_turn_timer_is_three_minutes():
    assert logic.DEFAULT_EVENT_CONFIG["turn_seconds"] == 180


def test_timer_expiry_does_not_skip(engine, clock, make_event):
    eid, guests = make_event(turn_seconds=180)
    to_choosing(engine, clock)
    clock.advance(181)
    engine.tick()
    msgs = engine.drain()
    assert any(m["message"]["type"] == "turn_overtime" for m in msgs)
    ev = engine.get_event(eid)
    assert ev["turn_state"] == "overtime" and ev["phase_deadline"] is None
    clock.advance(3600)
    engine.tick()
    assert engine._turn(engine.get_event(eid)["current_turn_id"])["guest_id"] == guests[0]["id"]
    # They can still queue in overtime, and that moves things on.
    engine.queue_song(guests[0]["id"], video(1))
    assert engine._turn(engine.get_event(eid)["current_turn_id"])["guest_id"] == guests[1]["id"]


_song_ids = iter(range(100, 10_000))


def _who_picks(engine, clock, eid, n):
    order = []
    for _ in range(n):
        ev = to_choosing(engine, clock)
        gid = engine._turn(ev["current_turn_id"])["guest_id"]
        order.append(gid)
        engine.queue_song(gid, video(next(_song_ids)))
    return order


def test_pass_lets_exactly_one_singer_ahead(engine, clock, make_event):
    eid, guests = make_event(names=("Alex", "Blake", "Casey", "Devon"))
    a, b, c, d = (g["id"] for g in guests)
    to_choosing(engine, clock)
    engine.pass_turn(a)
    snap = engine.snapshot(eid)
    assert snap["turn"]["guest_id"] == b
    assert snap["upcoming"][:3] == [a, c, d]
    assert _who_picks(engine, clock, eid, 6) == [b, a, c, d, a, b]
    assert engine.get_event(eid)["current_round"] == 2


def test_pass_in_overtime(engine, clock, make_event):
    eid, guests = make_event()
    a, b, c = (g["id"] for g in guests)
    to_choosing(engine, clock)
    clock.advance(500)
    engine.tick()
    engine.pass_turn(a)
    assert _who_picks(engine, clock, eid, 3) == [b, a, c]


def test_passing_again_moves_down_one_more(engine, clock, make_event):
    eid, guests = make_event(names=("Alex", "Blake", "Casey", "Devon"))
    a, b, c, d = (g["id"] for g in guests)
    to_choosing(engine, clock)
    engine.pass_turn(a)
    assert _who_picks(engine, clock, eid, 1) == [b]
    ev = to_choosing(engine, clock)
    assert engine._turn(ev["current_turn_id"])["guest_id"] == a
    engine.pass_turn(a)
    assert _who_picks(engine, clock, eid, 3) == [c, a, d]


def test_pass_when_next_singer_leaves(engine, clock, make_event):
    eid, guests = make_event()
    a, b, c = (g["id"] for g in guests)
    to_choosing(engine, clock)
    engine.pass_turn(a)
    engine.leave(b)  # B was up; A's wait is over
    assert engine._turn(engine.get_event(eid)["current_turn_id"])["guest_id"] == a


def test_pass_rejected_when_alone_or_not_your_turn(engine, clock, make_event):
    import pytest
    from app.engine import EngineError
    eid, guests = make_event(names=("Solo",))
    to_choosing(engine, clock)
    with pytest.raises(EngineError):
        engine.pass_turn(guests[0]["id"])
    eid2 = engine.create_event("Other", {})["id"]
    x, _ = engine.join(eid2, "X")
    engine.join(eid2, "Y")
    engine.start_event(eid2)
    y = engine.db.one("SELECT id FROM guests WHERE display_name = 'Y'")["id"]
    with pytest.raises(EngineError):
        engine.pass_turn(y)


def test_upcoming_with_pending_pass():
    guests = [g(1, 1), g(2, 2), g(3, 3)]
    pending = [{"guest_id": 1, "kind": "deferred", "after_guest_id": 2, "ready": False}]
    assert logic.upcoming_order(guests, 1, exclude_id=None, pending=pending) == [2, 1, 3, 1]


def test_current_guest_leaving_advances(engine, clock, make_event):
    eid, guests = make_event()
    to_choosing(engine, clock)
    engine.leave(guests[0]["id"])
    ev = engine.get_event(eid)
    assert engine._turn(ev["current_turn_id"])["guest_id"] == guests[1]["id"]


def test_host_skip_guest_later(engine, clock, make_event):
    eid, guests = make_event()
    to_choosing(engine, clock)
    engine.skip_guest(guests[1]["id"])
    engine.queue_song(guests[0]["id"], video(1))
    ev = engine.get_event(eid)
    assert engine._turn(ev["current_turn_id"])["guest_id"] == guests[2]["id"]
    assert not engine._guest(guests[1]["id"])["skip_next"]


def test_pause_freezes_timer(engine, clock, make_event):
    eid, guests = make_event(turn_seconds=60)
    to_choosing(engine, clock)
    clock.advance(20)
    engine.pause_rotation(eid)
    clock.advance(500)
    engine.tick()
    ev = engine.get_event(eid)
    assert engine._turn(ev["current_turn_id"])["guest_id"] == guests[0]["id"]
    engine.resume_rotation(eid)
    ev = engine.get_event(eid)
    assert abs(ev["phase_deadline"] - clock.now - 40) < 0.01


def test_rotation_starts_when_first_guest_joins(engine, clock):
    ev = engine.create_event("Empty", {"superset_chance": 0})
    engine.start_event(ev["id"])
    assert engine.get_event(ev["id"])["turn_state"] == "idle"
    guest, _ = engine.join(ev["id"], "Solo")
    ev = engine.get_event(ev["id"])
    assert ev["turn_state"] == "announcing"
    assert engine._turn(ev["current_turn_id"])["guest_id"] == guest["id"]


def test_duplicate_names_rejected(engine, make_event):
    import pytest
    from app.engine import EngineError
    eid, _ = make_event()
    with pytest.raises(EngineError):
        engine.join(eid, "alex")
