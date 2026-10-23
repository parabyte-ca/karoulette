import random
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.db import Database  # noqa: E402
from app.config import Settings  # noqa: E402
from app.engine import Engine  # noqa: E402
from app.main import create_app  # noqa: E402
from app.youtube import YouTubeService  # noqa: E402


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
        cfg = {"superset_chance": 0.0, "autoplay": False, "themes_enabled": True, **config}
        ev = engine.create_event("Test Night", cfg)
        guests = [engine.join(ev["id"], n)[0] for n in names]
        if start:
            engine.start_event(ev["id"])
        engine.drain()
        return ev["id"], guests
    return _make


class StubYouTube(YouTubeService):
    def __init__(self, db):
        super().__init__(db, api_key="SECRET-KEY-DO-NOT-LEAK", enable_ytdlp=False)
        self.searches = 0

    async def search(self, raw_query, safe_search="moderate"):
        self.searches += 1
        return {"query": raw_query + " karaoke", "source": "api", "cached": False,
                "results": [{"video_id": "abcdefghijk", "title": "Test Song", "channel": "Ch",
                             "duration_s": 180, "thumbnail": "", "embeddable": True}]}

    async def verify(self, video_id):
        if video_id == "blockedvid0":
            return {"video_id": video_id, "embeddable": False}
        return {"video_id": video_id, "title": "Test Song", "channel": "Ch", "duration_s": 180,
                "embeddable": True, "thumbnail": ""}


@pytest.fixture
def client(tmp_path):
    settings = Settings(data_path=tmp_path, host_pin="4321", static_dir=tmp_path / "static",
                        youtube_api_key="SECRET-KEY-DO-NOT-LEAK")
    holder = {}

    def make():
        from app.db import Database
        return StubYouTube(Database(tmp_path / "karoulette.db"))

    app = create_app(settings, start_ticker=False, youtube=make())
    with TestClient(app) as c:
        holder["app"] = app
        yield c
