"""Fair singer order: free submission, one song per singer per round, newcomers at the end of the order."""
import pytest

from app import logic
from app.engine import EngineError
from tests.conftest import add, play_all, singer_order


def g(id_, pos, **kw):
    return {"id": id_, "rotation_pos": pos, "status": "active", **kw}


# ---- pure logic

def test_assign_round():
    # Nobody has sung yet this round: everyone's first song goes in it.
    assert logic.assign_round(1, None, 3, None) == 1
    # Slot still ahead of the singer on the mic (pos 2): this round.
    assert logic.assign_round(4, 2, 3, None) == 4
    # Slot already passed (or it's them singing): next round.
    assert logic.assign_round(4, 3, 3, None) == 5
    assert logic.assign_round(4, 3, 1, 2) == 5
    # Already have a song this round or later: one round after their last.
    assert logic.assign_round(4, 2, 3, 4) == 5
    assert logic.assign_round(4, 2, 3, 7) == 8
    assert logic.assign_round(0, None, 1, None) == 1


def test_play_order_round_then_singer_order():
    items = [
        {"id": 1, "guest_id": 10, "round_no": 2, "status": "queued"},
        {"id": 2, "guest_id": 20, "round_no": 1, "status": "queued"},
        {"id": 3, "guest_id": 10, "round_no": 1, "status": "queued"},
        {"id": 4, "guest_id": 30, "round_no": 1, "status": "queued", "priority": 5.0},
        {"id": 5, "guest_id": 30, "round_no": 1, "status": "played"},
    ]
    order = logic.play_order(items, {10: 1, 20: 2, 30: 3})
    assert [i["id"] for i in order] == [4, 3, 2, 1]


# ---- engine

def test_singers_add_many_songs_without_waiting(engine, make_event):
    eid, (a, b, c) = make_event()
    for _ in range(3):
        add(engine, a)
    add(engine, b)
    add(engine, c)
    add(engine, b)
    # Interleaved by round, singer order kept within each round.
    assert singer_order(engine, eid) == ["Alex", "Blake", "Casey", "Alex", "Blake", "Alex"]
    assert play_all(engine, eid) == ["Alex", "Blake", "Casey", "Alex", "Blake", "Alex"]
    assert engine.get_event(eid)["current_round"] == 3


def test_songs_added_mid_round_respect_the_order(engine, make_event):
    eid, (a, b, c) = make_event()
    add(engine, a)
    add(engine, b)
    engine.play_next(eid)                # Alex singing
    add(engine, c)                       # Casey's slot is still ahead this round
    add(engine, a)                       # Alex already sang this round: next round
    assert singer_order(engine, eid) == ["Alex", "Blake", "Casey", "Alex"]
    engine.player_ended(eid, engine.get_event(eid)["now_playing_item_id"])  # Blake singing
    add(engine, b)                       # Blake's next goes after Alex's round-2 song
    assert singer_order(engine, eid) == ["Blake", "Casey", "Alex", "Blake"]


def test_new_singer_joins_the_end_of_the_order_and_is_announced(engine, make_event):
    eid, (a, b, c) = make_event()
    for p in (a, b, c, a):
        add(engine, p)
    engine.play_next(eid)                # Alex singing; Blake and Casey waiting
    engine.drain()
    dana, _ = engine.join(eid, "Dana")
    msgs = engine.drain()
    assert any(m["message"]["type"] == "guest_joined" and m["message"]["data"]["new_singer"] for m in msgs)
    assert any("end of the line-up" in m["message"]["data"].get("text", "") for m in msgs)
    add(engine, dana)
    # No jumping the line: Dana sings last in this round, before anyone's second song.
    assert singer_order(engine, eid) == ["Alex", "Blake", "Casey", "Dana", "Alex"]
    assert [g["name"] for g in engine.snapshot(eid)["guests"]] == ["Alex", "Blake", "Casey", "Dana"]
    for _ in range(3):
        engine.player_ended(eid, engine.get_event(eid)["now_playing_item_id"])
    msgs = engine.drain()
    assert any(m["message"]["type"] == "new_singer" and m["message"]["data"]["name"] == "Dana" for m in msgs)
    assert not engine._guest(dana["id"])["debut_pending"]


def test_two_newcomers_keep_their_join_order(engine, make_event):
    eid, (a, b) = make_event(names=("Alex", "Blake"))
    add(engine, a)
    add(engine, b)
    engine.play_next(eid)
    dana, _ = engine.join(eid, "Dana")
    eli, _ = engine.join(eid, "Eli")
    add(engine, eli)
    add(engine, dana)
    assert singer_order(engine, eid) == ["Alex", "Blake", "Dana", "Eli"]


def test_newcomer_who_picks_later_still_waits_their_turn(engine, make_event):
    eid, (a, b, c) = make_event()
    for p in (a, b, c, a, b, c):
        add(engine, p)
    engine.play_next(eid)                            # Alex
    dana, _ = engine.join(eid, "Dana")
    engine.player_ended(eid, engine.get_event(eid)["now_playing_item_id"])  # Blake now
    add(engine, dana)                                # end of this round, after Casey
    assert singer_order(engine, eid) == ["Blake", "Casey", "Dana", "Alex", "Blake", "Casey"]


def test_join_before_anyone_sings_appends(engine, make_event):
    eid, (a, b) = make_event(names=("Alex", "Blake"), start=False)
    dana, _ = engine.join(eid, "Dana")
    assert not dana["debut_pending"]
    for p in (dana, a, b):
        add(engine, p)
    assert singer_order(engine, eid) == ["Alex", "Blake", "Dana"]


def test_let_next_singer_go_first(engine, make_event):
    eid, (a, b, c) = make_event()
    for p in (a, b, c, a):
        add(engine, p)
    queue = engine.snapshot(eid)["queue"]
    with pytest.raises(EngineError):
        engine.let_next_go_first(b["id"], queue[1]["id"])   # not up next
    engine.let_next_go_first(a["id"], queue[0]["id"])
    assert singer_order(engine, eid) == ["Blake", "Alex", "Casey", "Alex"]
    # Passing again moves them down exactly one more.
    queue = engine.snapshot(eid)["queue"]
    engine.play_next(eid)                                 # Blake sings
    engine.let_next_go_first(a["id"], engine.snapshot(eid)["queue"][0]["id"])
    assert singer_order(engine, eid) == ["Blake", "Casey", "Alex", "Alex"]


def test_let_next_go_first_into_next_round_keeps_own_order(engine, make_event):
    eid, (a, b) = make_event(names=("Alex", "Blake"))
    first = add(engine, a)
    add(engine, b)
    second = add(engine, a)
    engine.play_next(eid)                                 # Alex's first song now playing
    engine.player_ended(eid, first["id"])                 # Blake singing; queue: Alex (r2)
    add(engine, b)                                        # Blake r2
    third = add(engine, a)                                # Alex r3
    engine.let_next_go_first(a["id"], second["id"])
    order = engine.snapshot(eid)["queue"]
    assert [q["guest_name"] for q in order] == ["Blake", "Alex", "Alex"]
    assert [q["id"] for q in order if q["guest_name"] == "Alex"] == [second["id"], third["id"]]


def test_singer_reorders_own_songs(engine, make_event):
    eid, (a, b) = make_event(names=("Alex", "Blake"))
    s1, s2 = add(engine, a, 1), add(engine, a, 2)
    add(engine, b)
    engine.move_my_song_up(a["id"], s2["id"])
    queue = engine.snapshot(eid)["queue"]
    assert [q["guest_name"] for q in queue] == ["Alex", "Blake", "Alex"]
    assert [q["id"] for q in queue if q["guest_id"] == a["id"]] == [s2["id"], s1["id"]]
    engine.move_my_song_up(a["id"], s2["id"])  # already first: no-op
    assert engine.snapshot(eid)["queue"][0]["id"] == s2["id"]


def test_host_moves_singer_in_order(engine, make_event):
    eid, (a, b, c) = make_event()
    for p in (a, b, c):
        add(engine, p)
    engine.move_guest(c["id"], -1)
    assert singer_order(engine, eid) == ["Alex", "Casey", "Blake"]


def test_leaving_removes_songs_and_keeps_order(engine, make_event):
    eid, (a, b, c) = make_event()
    for p in (a, b, c, a):
        add(engine, p)
    engine.leave(b["id"])
    assert singer_order(engine, eid) == ["Alex", "Casey", "Alex"]


def test_removing_a_song_moves_later_ones_up_a_round(engine, make_event):
    eid, (a, b) = make_event(names=("Alex", "Blake"))
    s1 = add(engine, a)
    add(engine, a)
    add(engine, b)
    add(engine, b)
    engine.remove_item(eid, s1["id"], by_guest_id=a["id"])
    assert singer_order(engine, eid) == ["Alex", "Blake", "Blake"]


def test_duplicate_names_rejected(engine, make_event):
    eid, _ = make_event()
    with pytest.raises(EngineError):
        engine.join(eid, "alex")


# ---- a singer must not lose their turn (fixed in 0.9.2)

def test_repick_after_error_keeps_the_singers_turn(make_event, engine):
    eid, (a, b, c, d) = make_event(("Alex", "Blake", "Casey", "Dana"))
    for gst in (a, b, c, d):
        add(engine, gst)
    engine.play_next(eid)                                                    # Alex
    engine.player_ended(eid, engine.get_event(eid)["now_playing_item_id"])   # Blake's song starts...
    engine.player_error(eid, engine.get_event(eid)["now_playing_item_id"], 150)  # ...and can't play
    repick = add(engine, b)
    assert repick["round_no"] == 1   # the re-pick takes the failed song's turn
    for gst in (a, c, d, b):
        add(engine, gst)
    # Blake sings in round 2 like everyone else, not after it.
    assert singer_order(engine, eid) == ["Casey", "Blake", "Dana", "Alex", "Blake", "Casey", "Dana"]


def test_play_next_does_not_cost_later_singers_their_turn(make_event, engine):
    eid, (a, b, c, d) = make_event(("Alex", "Blake", "Casey", "Dana"))
    for gst in (a, b, d):
        add(engine, gst)
    early = add(engine, d)              # Dana's round-2 song
    engine.play_next(eid)               # Alex
    engine.play_item_next(eid, early["id"])
    engine.player_ended(eid, engine.get_event(eid)["now_playing_item_id"])  # the host's pick plays now
    late = add(engine, c)               # Casey picks while Dana sings out of turn
    assert late["round_no"] == 1        # Casey's slot in round 1 hasn't come up yet
    assert singer_order(engine, eid) == ["Dana", "Blake", "Casey", "Dana"]


def test_superset_turn_does_not_cost_later_singers_their_turn(make_event, engine):
    eid, (a, b, c, d) = make_event(("Alex", "Blake", "Casey", "Dana"))
    add(engine, a)
    engine.play_next(eid)                                   # Alex, round 1
    engine.force_superset(eid, "after")                     # Blake, Casey, Dana, Alex each pick a bonus song
    for gst in (b, c, d, a):
        assert add(engine, gst)["set_id"]
    for _ in range(3):                                      # Alex's song, then Blake's and Casey's set songs
        engine.player_ended(eid, engine.get_event(eid)["now_playing_item_id"])
    assert singer_order(engine, eid)[0] == "Dana"           # Dana's Superset turn
    regular = add(engine, c)                                # Casey queues her round song meanwhile
    assert regular["round_no"] == engine.get_event(eid)["current_round"]
