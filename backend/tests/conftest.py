import random
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.db import Database  # noqa: E402
from app.engine import Engine  # noqa: E402


class FakeClock:
    def __init__(self, start: float = 1_000_000.0):
        self.now = start

    def __call__(self) -> float:
        self.now += 0.001  # strictly increasing, so "most recent" queries are deterministic
        return self.now

    def advance(self, seconds: float) -> float:
        self.now += seconds
        return self.now


@pytest.fixture
def clock():
    return FakeClock()


@pytest.fixture
def engine(clock):
    db = Database(":memory:")
    eng = Engine(db, clock=clock, rng=random.Random(42))
    eng.seed_themes()
    return eng


_ids = iter(range(1, 100_000))


def video(n: int | None = None) -> dict:
    n = next(_ids) if n is None else n
    vid = f"v{n:010d}"[:11]
    return {"video_id": vid, "title": f"Song {n}", "channel": "Karaoke Co", "duration_s": 200, "thumbnail": ""}


def add(engine, guest, n: int | None = None) -> dict:
    return engine.queue_song(guest["id"], video(n))


def singer_order(engine, event_id) -> list[str]:
    """Singer names in play order: now playing first, then the queue."""
    snap = engine.snapshot(event_id)
    names = [snap["now_playing"]["guest_name"]] if snap["now_playing"] else []
    return names + [q["guest_name"] for q in snap["queue"]]


def play_all(engine, event_id) -> list[str]:
    """Play the whole queue through; returns who sang, in order."""
    sung = []
    while True:
        ev = engine.get_event(event_id)
        if not ev["now_playing_item_id"]:
            if not engine.play_next(event_id):
                return sung
            ev = engine.get_event(event_id)
        item = engine.db.one("SELECT * FROM queue_items WHERE id = ?", (ev["now_playing_item_id"],))
        sung.append(engine._guest(item["guest_id"])["display_name"])
        engine.player_ended(event_id, item["id"])
        if not engine.get_event(event_id)["now_playing_item_id"]:
            return sung


@pytest.fixture
def make_event(engine):
    def _make(names=("Alex", "Blake", "Casey"), start=True, **config):
        cfg = {"superset_chance": 0.0, "autoplay": False, **config}
        ev = engine.create_event("Test Night", cfg)
        guests = [engine.join(ev["id"], n)[0] for n in names]
        if start:
            engine.start_event(ev["id"])
        engine.drain()
        return ev["id"], guests
    return _make
