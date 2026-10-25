"""Last call: an optional closing time. Songs that would run past it are refused, and everyone is told."""
from __future__ import annotations

from .. import logic
from .constants import UNKNOWN_DURATION_S, EngineError


class LastCallMixin:
    def _closing_at(self, ev: dict) -> float | None:
        return logic.closing_at(ev["started_at"] or ev["created_at"], ev["config"]["last_call"])

    def _queue_ends_at(self, ev: dict) -> float:
        """When the last song now waiting would finish: the one playing, any Superset turns, then the queue."""
        now = self.clock()
        ready = int(ev["config"]["ready_seconds"])
        length = (lambda item: (item or {}).get("duration_s") or UNKNOWN_DURATION_S)  # noqa: E731
        ends = now
        if ev["now_playing_item_id"]:
            playing = self.db.one("SELECT * FROM queue_items WHERE id = ?", (ev["now_playing_item_id"],))
            ends = max(now, (ev["ready_until"] or playing["played_at"] or now) + length(playing))
        sset = self._active_set(ev["id"])
        if sset:
            for slot in self._slots(sset["id"]):
                if slot["status"] in ("pending", "picked"):
                    item = self.db.one("SELECT duration_s FROM queue_items WHERE id = ?", (slot["item_id"],)) \
                        if slot["item_id"] else None
                    ends += ready + length(item)
        for item in self._queue(ev["id"]):
            ends += ready + length(item)
        return ends

    def last_call_info(self, ev: dict) -> dict | None:
        closing = self._closing_at(ev)
        if closing is None or ev["status"] == "ended":
            return None
        ends = self._queue_ends_at(ev)
        slot = UNKNOWN_DURATION_S + int(ev["config"]["ready_seconds"])
        room = max(0, int((closing - ends) // slot))
        return {"closing_at": closing, "closing_text": logic.clock_text(closing), "queue_ends_at": ends,
                "room": room, "open": room > 0}

    def _check_last_call(self, ev: dict, duration_s: int | None, what: str = "song") -> None:
        closing = self._closing_at(ev)
        if closing is None:
            return
        ready = int(ev["config"]["ready_seconds"])
        if self._queue_ends_at(ev) + ready + (duration_s or UNKNOWN_DURATION_S) > closing:
            self.log(ev["id"], "songs", f"Refused a {what}: past last call ({logic.clock_text(closing)})", refused="last_call")
            raise EngineError(f"🔔 Last call! The queue already runs to closing time ({logic.clock_text(closing)}), "
                              f"so there's no room for another {what}.", 409)

    def _announce_last_call(self, ev: dict) -> None:
        """Tell everyone once, the moment the queue fills up to closing time."""
        info = self.last_call_info(ev)
        if info and not info["open"] and not ev["last_call_announced"]:
            self._set(ev["id"], last_call_announced=1)
            self.log(ev["id"], "event", f"Last call: the queue now runs to closing time ({info['closing_text']})",
                     automatic=True)
            self.notice(ev["id"], f"🔔 Last call! The queue now runs to closing time ({info['closing_text']}).",
                        "gold", kind="last_call")
            self.emit(ev["id"], "last_call", {"closing_text": info["closing_text"]})
