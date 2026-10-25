"""Plumbing shared by every part of the engine: the outbox and common lookups."""
from __future__ import annotations

import json
import random
import time
from contextvars import ContextVar
from typing import Callable

from .. import logic
from ..db import Database
from .constants import EngineError


# Who is acting, for the timeline: ("host", None, "Host"), ("guest", id, name). Unset = Karoulette itself
# (autoplay, the vote timer). The web layer sets it per request.
ACTOR: ContextVar[tuple | None] = ContextVar("karoulette_actor", default=None)


class EngineBase:
    def __init__(self, db: Database, clock: Callable[[], float] = time.time,
                 rng: random.Random | None = None):
        self.db = db
        self.clock = clock
        self.rng = rng or random.Random()
        self.outbox: list[dict] = []

    # ------------------------------------------------------------------ plumbing

    def emit(self, event_id: int, type_: str, data: dict | None = None, guest_id: int | None = None) -> None:
        self.outbox.append({"event_id": event_id, "guest_id": guest_id,
                            "message": {"type": type_, "data": data or {}}})

    def notice(self, event_id: int, text: str, level: str = "info", guest_id: int | None = None,
               kind: str | None = None) -> None:
        """A toast for phones and the TV. ``kind`` tags notices the TV already shows as a big banner."""
        data = {"text": text, "level": level, **({"kind": kind} if kind else {})}
        self.emit(event_id, "notice", data, guest_id)

    def log(self, event_id: int, kind: str, text: str, automatic: bool = False, **data) -> None:
        """Add a line to the event's timeline (Host admin → Events → Timeline). ``automatic`` credits
        Karoulette (what plays next, new rounds) even when someone's action set it off."""
        actor_type, actor_id, actor_name = (None if automatic else ACTOR.get()) or ("system", None, "Karoulette")
        self.db.execute("INSERT INTO event_log(event_id, at, kind, actor_type, actor_id, actor_name, text, data) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                        (event_id, self.clock(), kind, actor_type, actor_id, actor_name, text, json.dumps(data)))

    def _song(self, item: dict | None) -> str:
        return f"“{logic.song_name(item['title'])}”" if item else "a song"

    def _who(self, guest_id: int | None) -> str:
        g = self.db.one("SELECT display_name FROM guests WHERE id = ?", (guest_id,)) if guest_id else None
        return g["display_name"] if g else "someone"

    def drain(self) -> list[dict]:
        out, self.outbox = self.outbox, []
        return out

    def get_event(self, event_id: int) -> dict:
        ev = self.db.one("SELECT * FROM events WHERE id = ?", (event_id,))
        if not ev:
            raise EngineError("Event not found", 404)
        ev["config"] = logic.merge_config(json.loads(ev["config"] or "{}"), None)
        return ev

    def event_by_code(self, code: str) -> dict:
        row = self.db.one("SELECT id FROM events WHERE join_code = ?", ((code or "").strip().upper(),))
        if not row:
            raise EngineError("No event with that code", 404)
        return self.get_event(row["id"])

    def _set(self, event_id: int, **fields) -> None:
        if "config" in fields:
            fields["config"] = json.dumps(fields["config"])
        cols = ", ".join(f"{k} = ?" for k in fields)
        self.db.execute(f"UPDATE events SET {cols} WHERE id = ?", (*fields.values(), event_id))

    def _guests(self, event_id: int, active_only: bool = True) -> list[dict]:
        sql = "SELECT * FROM guests WHERE event_id = ?" + (" AND status = 'active'" if active_only else "")
        return self.db.all(sql + " ORDER BY rotation_pos, id", (event_id,))

    def _guest(self, guest_id: int) -> dict:
        g = self.db.one("SELECT * FROM guests WHERE id = ?", (guest_id,))
        if not g:
            raise EngineError("Guest not found", 404)
        return g

    def _theme(self, theme_id: int | None) -> dict | None:
        if theme_id is None:
            return None
        return self.db.one("SELECT * FROM themes WHERE id = ?", (theme_id,))

    def _round(self, round_id: int | None) -> dict | None:
        if round_id is None:
            return None
        return self.db.one("SELECT * FROM rounds WHERE id = ?", (round_id,))

    def _items(self, event_id: int, statuses: tuple[str, ...] | None = None) -> list[dict]:
        if statuses:
            marks = ",".join("?" * len(statuses))
            return self.db.all(f"SELECT * FROM queue_items WHERE event_id = ? AND status IN ({marks})",
                               (event_id, *statuses))
        return self.db.all("SELECT * FROM queue_items WHERE event_id = ?", (event_id,))
