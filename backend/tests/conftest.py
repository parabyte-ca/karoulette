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


def video(n: int) -> dict:
    vid = f"vid{n:08d}"[:11].ljust(11, "x")
    return {"video_id": vid, "title": f"Song {n}", "channel": "Karaoke Co", "duration_s": 200, "thumbnail": ""}


def to_choosing(engine, clock):
    """Run the ticker until the current turn reaches the choosing phase."""
    for _ in range(10):
        ev = engine.get_event(engine.db.one("SELECT id FROM events")["id"])
        if ev["turn_state"] == "choosing":
            return ev
        if ev["phase_deadline"] is None:
            return ev
        clock.now = ev["phase_deadline"]
        engine.tick()
    return ev


@pytest.fixture
def make_event(engine):
    def _make(names=("Alex", "Blake", "Casey"), start=True, **config):
        cfg = {"superset_chance": 0.0, **config}
        ev = engine.create_event("Test Night", cfg)
        guests = [engine.join(ev["id"], n)[0] for n in names]
        if start:
            engine.start_event(ev["id"])
        engine.drain()
        return ev["id"], guests
    return _make
