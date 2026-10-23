"""Superset sets: one bonus song per singer on one theme, once round the singer order, then back to the queue."""
import pytest

from app import logic
from app.engine import EngineError
from tests.conftest import add, video

NAMES = ("Alex", "Blake", "Casey", "Dana")


def now_name(engine, eid):
    snap = engine.snapshot(eid)
    return snap["now_playing"]["guest_name"] if snap["now_playing"] else None


def finish(engine, eid):
    engine.player_ended(eid, engine.get_event(eid)["now_playing_item_id"])


def slots(engine, eid):
    return [(s["name"], s["status"]) for s in engine.snapshot(eid)["superset"]["slots"]]


def test_set_order_carries_on_the_rotation():
    guests = [{"id": i, "rotation_pos": i, "status": "active"} for i in (1, 2, 3, 4)]
    ids = lambda order: [g["id"] for g in order]  # noqa: E731
    assert ids(logic.set_order(guests, 2, include_anchor=False)) == [3, 4, 1, 2]
    assert ids(logic.set_order(guests, 2, include_anchor=True)) == [2, 3, 4, 1]
    assert ids(logic.set_order(guests, None, include_anchor=False)) == [1, 2, 3, 4]


def test_song_name_drops_karaoke_words():
    assert logic.song_name("Africa (Karaoke Version)") == "Africa"
    assert logic.song_name("Take On Me - Karaoke with lyrics") == "Take On Me"
    assert logic.song_name("Bohemian Rhapsody") == "Bohemian Rhapsody"


def test_vote_starting_now_uses_the_current_song_and_waits_for_picks(engine, make_event):
    eid, (alex, blake, casey, dana) = make_event(names=NAMES)
    for p in (alex, blake, casey, dana, alex):
        add(engine, p)
    engine.play_next(eid)                                   # Alex singing "Song n"
    title = engine.snapshot(eid)["now_playing"]["title"]
    regular_before = [q["id"] for q in engine.snapshot(eid)["queue"]]
    engine.call_superset_vote(blake["id"], "now")
    engine.vote_superset(casey["id"], True)
    engine.vote_superset(dana["id"], True)                  # 2 of 3 others: passed
    snap = engine.snapshot(eid)
    sup = snap["superset"]
    assert sup["mode"] == "now" and sup["theme"] == f"Songs like “{title}”" and sup["inspired_by"] == title
    assert slots(engine, eid) == [("Alex", "singing"), ("Blake", "pending"), ("Casey", "pending"),
                                  ("Dana", "pending")]
    assert snap["round"]["is_superset"] and snap["now_playing"]["is_superset"]
    assert [q["id"] for q in snap["queue"]] == regular_before  # the regular queue is untouched

    finish(engine, eid)                                     # Alex's song done: the set waits for Blake
    assert now_name(engine, eid) is None and engine.snapshot(eid)["superset"]["waiting_for"] == blake["id"]
    assert any(m["message"]["type"] == "superset_your_turn" and m["guest_id"] == blake["id"] for m in engine.drain())
    add(engine, casey)                                      # Casey picks early: waits her turn
    assert now_name(engine, eid) is None
    add(engine, blake)                                      # Blake picks: straight on
    assert now_name(engine, eid) == "Blake" and engine.snapshot(eid)["now_playing"]["is_superset"]
    engine.pass_superset(dana["id"])                        # Dana sits it out
    finish(engine, eid)
    assert now_name(engine, eid) == "Casey"
    finish(engine, eid)                                     # set complete: the queue carries on
    snap = engine.snapshot(eid)
    assert snap["superset"] is None and snap["now_playing"]["guest_name"] == "Blake"
    assert snap["now_playing"]["id"] == regular_before[0] and not snap["now_playing"]["is_superset"]
    assert engine.db.one("SELECT status FROM superset_sets")["status"] == "done"


def test_host_superset_after_this_song_spins_a_theme(engine, make_event):
    eid, (alex, blake, casey, _) = make_event(names=NAMES)
    for p in (alex, blake):
        add(engine, p)
    engine.play_next(eid)                                   # Alex singing
    engine.force_superset(eid, "after")
    sup = engine.snapshot(eid)["superset"]
    assert sup["mode"] == "after" and sup["spun_at"] and sup["theme"] in [t["name"] for t in engine.list_themes()]
    assert slots(engine, eid) == [("Blake", "pending"), ("Casey", "pending"), ("Dana", "pending"),
                                  ("Alex", "pending")]      # carries on after Alex, wrapping round
    assert not engine.snapshot(eid)["now_playing"]["is_superset"]  # Alex's song isn't part of it


def test_set_waits_and_host_can_skip_a_turn(engine, make_event):
    eid, (alex, blake, casey, dana) = make_event(names=NAMES)
    add(engine, alex)
    engine.play_next(eid)
    engine.force_superset(eid, "now")
    finish(engine, eid)
    assert engine.snapshot(eid)["superset"]["waiting_for"] == blake["id"]
    engine.skip_superset_turn(eid)
    assert engine.snapshot(eid)["superset"]["waiting_for"] == casey["id"]
    with pytest.raises(EngineError):
        engine.pass_superset(blake["id"])                   # already skipped


def test_superset_song_is_a_bonus_and_can_be_changed(engine, make_event):
    eid, (alex, blake, casey, _) = make_event(names=NAMES, max_songs_per_singer=1)
    add(engine, alex)
    add(engine, blake)                                      # Blake is at the limit
    engine.play_next(eid)
    engine.force_superset(eid, "after")
    pick = add(engine, blake)                               # still allowed: it's the Superset song
    assert pick["set_id"]
    with pytest.raises(EngineError):
        add(engine, blake)                                  # back to the regular limit
    engine.remove_item(eid, pick["id"], blake["id"])        # change of heart: pick again
    assert dict(slots(engine, eid))["Blake"] == "pending"
    add(engine, blake)
    assert dict(slots(engine, eid))["Blake"] == "picked"


def test_embed_error_on_a_superset_song_means_a_new_pick(engine, make_event):
    eid, (alex, blake, _, _) = make_event(names=NAMES)
    add(engine, alex)
    engine.play_next(eid)
    engine.force_superset(eid, "now")
    finish(engine, eid)
    add(engine, blake)
    item = engine.get_event(eid)["now_playing_item_id"]
    engine.player_error(eid, item, 150)
    snap = engine.snapshot(eid)
    assert snap["superset"]["waiting_for"] == blake["id"] and not engine._guest(blake["id"])["repick_credit"]


def test_leavers_are_skipped_and_newcomers_join_the_end(engine, make_event):
    eid, (alex, blake, casey, _) = make_event(names=NAMES)
    add(engine, alex)
    engine.play_next(eid)
    engine.force_superset(eid, "now")
    finish(engine, eid)                                     # waiting for Blake
    engine.leave(blake["id"])                               # moves straight on to Casey
    assert engine.snapshot(eid)["superset"]["waiting_for"] == casey["id"]
    eli, _ = engine.join(eid, "Eli")
    assert slots(engine, eid)[-1] == ("Eli", "pending")
    assert dict(slots(engine, eid))["Blake"] == "skipped"


def test_cancel_drops_the_picks_and_resumes_the_queue(engine, make_event):
    eid, (alex, blake, casey, _) = make_event(names=NAMES)
    for p in (alex, blake):
        add(engine, p)
    engine.play_next(eid)
    engine.force_superset(eid, "after")
    pick = add(engine, casey)
    finish(engine, eid)                                     # set waiting for Blake
    engine.cancel_superset(eid)
    snap = engine.snapshot(eid)
    assert snap["superset"] is None and snap["now_playing"]["guest_name"] == "Blake"
    assert engine.db.one("SELECT status FROM queue_items WHERE id = ?", (pick["id"],))["status"] == "removed"


def test_flags_only_for_superset_songs_while_the_set_runs(engine, make_event):
    eid, (alex, blake, casey, _) = make_event(names=NAMES)
    regular = add(engine, alex)
    later = add(engine, alex)
    engine.play_next(eid)
    with pytest.raises(EngineError):
        engine.flag_item(eid, regular["id"], f"guest:{blake['id']}")
    engine.force_superset(eid, "now")
    assert engine.flag_item(eid, regular["id"], f"guest:{blake['id']}") == 1   # it kicked the set off
    with pytest.raises(EngineError):
        engine.flag_item(eid, later["id"], "host")                              # a regular song
    with pytest.raises(EngineError):
        engine.flag_item(eid, regular["id"], f"guest:{alex['id']}")              # your own


def test_random_superset_opens_a_round_once(engine, make_event):
    eid, (alex, blake, _, _) = make_event(names=NAMES, superset_chance=1.0)
    add(engine, alex)
    add(engine, alex)                                       # round 2
    engine.play_next(eid)
    assert engine.snapshot(eid)["superset"] is None         # round 1 was already under way
    finish(engine, eid)                                     # round 2 would start: a Superset first
    sup = engine.snapshot(eid)["superset"]
    assert sup and sup["source"] == "random" and sup["mode"] == "after"
    for g in engine._guests(eid):                           # everyone sits it out
        engine.pass_superset(g["id"])
    snap = engine.snapshot(eid)                             # set over; round 2 starts without another roll
    assert snap["superset"] is None and snap["round"]["number"] == 2 and snap["now_playing"]["guest_name"] == "Alex"
    assert engine.db.one("SELECT COUNT(*) AS n FROM superset_sets")["n"] == 1


def test_only_one_set_at_a_time_and_needs_a_song_for_now(engine, make_event):
    eid, (alex, *_) = make_event(names=NAMES)
    with pytest.raises(EngineError):
        engine.call_superset_vote(alex["id"], "now")        # nothing playing
    engine.force_superset(eid, "after")
    with pytest.raises(EngineError):
        engine.force_superset(eid, "after")
    with pytest.raises(EngineError):
        engine.call_superset_vote(alex["id"], "after")


def test_recap_counts_completed_supersets(engine, make_event):
    eid, (alex, blake) = make_event(names=("Alex", "Blake"))
    add(engine, alex)
    engine.play_next(eid)
    engine.force_superset(eid, "now")
    finish(engine, eid)
    engine.queue_song(blake["id"], video())
    finish(engine, eid)
    engine.end_event(eid)
    recap = engine.snapshot(eid)["recap"]
    assert recap["superset_rounds"] == 1 and recap["superset_stars"] == ["Alex", "Blake"]
