"""Events: create, configure, start and end."""
from __future__ import annotations

import json
import secrets

from .. import logic
from .constants import JOIN_CODE_ALPHABET, EngineError


class EventsMixin:
    # ------------------------------------------------------------------ events

    def create_event(self, name: str, config: dict | None = None) -> dict:
        name = logic.clean_name(name)
        if not 1 <= len(name) <= 80:
            raise EngineError("Event name must be 1 to 80 characters")
        try:
            cfg = logic.merge_config({}, config)
        except (ValueError, TypeError) as exc:
            raise EngineError(str(exc)) from exc
        for _ in range(50):
            code = "".join(secrets.choice(JOIN_CODE_ALPHABET) for _ in range(5))
            if not self.db.one("SELECT 1 FROM events WHERE join_code = ?", (code,)):
                break
        event_id = self.db.insert("INSERT INTO events(name, join_code, config, created_at) VALUES (?, ?, ?, ?)",
                                  (name, code, json.dumps(cfg), self.clock()))
        return self.get_event(event_id)

    def list_events(self) -> list[dict]:
        rows = self.db.all(
            "SELECT e.id, e.name, e.join_code, e.status, e.created_at, e.started_at, e.ended_at, e.current_round, "
            "(SELECT COUNT(*) FROM guests g WHERE g.event_id = e.id AND g.status = 'active') AS guest_count, "
            "(SELECT COUNT(*) FROM queue_items q WHERE q.event_id = e.id AND q.status = 'played') AS songs_played "
            "FROM events e ORDER BY e.id DESC")
        return rows

    def update_event(self, event_id: int, name: str | None, config: dict | None) -> dict:
        ev = self.get_event(event_id)
        fields = {}
        if name is not None:
            name = logic.clean_name(name)
            if not 1 <= len(name) <= 80:
                raise EngineError("Event name must be 1 to 80 characters")
            fields["name"] = name
        if config:
            try:
                fields["config"] = logic.merge_config(ev["config"], config)
            except (ValueError, TypeError) as exc:
                raise EngineError(str(exc)) from exc
        if "config" in fields and fields["config"]["last_call"] != ev["config"]["last_call"]:
            fields["last_call_announced"] = 0  # a new closing time gets its own announcement
        if fields:
            self._set(event_id, **fields)
        rnd = self._round(ev["current_round_id"])
        if (config or {}).get("themes_enabled") and not ev["config"]["themes_enabled"] and rnd \
                and ev["status"] == "active" and self._pick_theme(event_id):
            self.force_spin(event_id)  # themes switched on mid-event: this round gets one straight away
        self.emit(event_id, "event_updated")
        return self.get_event(event_id)

    def start_event(self, event_id: int) -> None:
        ev = self.get_event(event_id)
        if ev["status"] == "ended":
            raise EngineError("This event has ended")
        if ev["status"] != "active":
            self._set(event_id, status="active", started_at=ev["started_at"] or self.clock())
            self.notice(event_id, "The event has started. Let's sing!")
        if ev["current_round"] == 0:
            self._start_round(event_id, 1)
        ev = self.get_event(event_id)
        if ev["config"]["autoplay"] and not ev["now_playing_item_id"] and not ev["paused"]:
            self.play_next(event_id)
        self.emit(event_id, "event_started")

    def end_event(self, event_id: int) -> None:
        ev = self.get_event(event_id)
        if ev["status"] == "ended":
            return
        self.db.execute("UPDATE queue_items SET status = 'removed' WHERE event_id = ? AND status = 'queued'",
                        (event_id,))
        self.db.execute("UPDATE queue_items SET status = 'played', played_at = ? "
                        "WHERE event_id = ? AND status = 'playing'", (self.clock(), event_id))
        vote = self._open_vote(event_id)
        if vote:
            self.db.execute("UPDATE superset_votes SET status = 'cancelled', closed_at = ? WHERE id = ?",
                            (self.clock(), vote["id"]))
        self.db.execute("UPDATE superset_sets SET status = 'cancelled', ended_at = ? WHERE event_id = ? "
                        "AND status = 'active'", (self.clock(), event_id))
        self._set(event_id, status="ended", ended_at=self.clock(), now_playing_item_id=None, ready_until=None,
                  paused=0)
        self.emit(event_id, "event_ended")
        self.notice(event_id, "Thanks for singing! This event has ended.")

    def delete_event(self, event_id: int) -> None:
        self.get_event(event_id)
        self.db.execute("DELETE FROM events WHERE id = ?", (event_id,))
