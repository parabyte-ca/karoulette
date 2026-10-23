"""Seed demo data: themes, a running event with guests, queued songs and some history.

Usage (inside the container):  python -m scripts.seed_demo
Locally:                         DATA_PATH=./data python -m scripts.seed_demo
"""
from __future__ import annotations

import os
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import Settings  # noqa: E402
from app.db import Database  # noqa: E402
from app.engine import Engine  # noqa: E402

DEMO_GUESTS = ["Alex", "Blake", "Casey", "Devon", "Emerson", "Frankie"]
DEMO_SONGS = [
    ("fJ9rUzIMcZQ", "Queen - Bohemian Rhapsody (Karaoke Version)", "Sing King", 359),
    ("9jK-NcRmVcw", "Europe - The Final Countdown (Karaoke)", "Sing King", 310),
    ("1w7OgIMMRc4", "Guns N' Roses - Sweet Child O' Mine (Karaoke)", "Sing King", 356),
    ("hTWKbfoikeg", "Nirvana - Smells Like Teen Spirit (Karaoke)", "Sing King", 301),
    ("btPJPFnesV4", "Survivor - Eye of the Tiger (Karaoke)", "Sing King", 245),
    ("lDK9QqIzhwk", "Bon Jovi - Livin' On A Prayer (Karaoke)", "Sing King", 250),
]


def main() -> None:
    settings = Settings()
    settings.ensure()
    db = Database(settings.db_path)
    engine = Engine(db, rng=random.Random(7))
    engine.seed_themes()
    ev = engine.create_event(os.getenv("DEMO_EVENT_NAME", "Demo Night"),
                             {"themes_enabled": True, "superset_chance": 0.15})
    tokens = {}
    for name in DEMO_GUESTS:
        guest, token = engine.join(ev["id"], name)
        tokens[name] = token
    engine.start_event(ev["id"])
    # Singers add songs whenever they like; the queue interleaves them fairly in singer order.
    guests = engine.db.all("SELECT * FROM guests WHERE event_id = ? ORDER BY rotation_pos", (ev["id"],))
    for guest, (vid, title, channel, dur) in zip(guests, DEMO_SONGS[:4]):
        engine.queue_song(guest["id"], {"video_id": vid, "title": title, "channel": channel,
                                        "duration_s": dur, "thumbnail": f"https://i.ytimg.com/vi/{vid}/mqdefault.jpg"})
    if not engine.get_event(ev["id"])["now_playing_item_id"]:
        engine.play_next(ev["id"])
    first = engine.get_event(ev["id"])["now_playing_item_id"]
    engine.player_ended(ev["id"], first)  # one song in history
    engine.drain()
    print(f"Demo event created: {ev['name']} (join code {ev['join_code']}, id {ev['id']})")
    print("Guest tokens (paste into localStorage 'kq_token' to impersonate):")
    for name, token in tokens.items():
        print(f"  {name:10s} {token}")


if __name__ == "__main__":
    main()
