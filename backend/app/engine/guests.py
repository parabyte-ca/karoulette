"""Singers: joining, rejoin codes, leaving, bouching and the singer order."""
from __future__ import annotations

import secrets

from .. import logic
from .constants import JOIN_CODE_ALPHABET, EngineError, hash_token


class GuestsMixin:
    # ------------------------------------------------------------------ singer order

    def _anchor(self, ev: dict) -> dict | None:
        """Where the current round has got to: the singer on the mic, or the last one to sing in the round.
        Superset turns and songs put first (by the host, or a re-pick after an error) are outside the
        rotation, so they don't count: otherwise singers still to come in the round would lose their turn."""
        item = None
        if ev["now_playing_item_id"]:
            item = self.db.one("SELECT * FROM queue_items WHERE id = ?", (ev["now_playing_item_id"],))
            if item and (item["priority"] is not None or item["set_id"]):
                item = None
        if item is None and ev["current_round"]:
            item = self.db.one(
                "SELECT * FROM queue_items WHERE event_id = ? AND status IN ('played', 'skipped', 'error') "
                "AND COALESCE(round_no, ?) = ? AND priority IS NULL AND set_id IS NULL "
                "ORDER BY played_at DESC, id DESC LIMIT 1",
                (ev["id"], ev["current_round"], ev["current_round"]))
        return self._guest(item["guest_id"]) if item else None

    def _anchor_pos(self, ev: dict) -> int | None:
        anchor = self._anchor(ev)
        return anchor["rotation_pos"] if anchor else None

    def _positions(self, event_id: int) -> dict[int, int]:
        return {g["id"]: g["rotation_pos"] for g in self._guests(event_id, active_only=False)}

    def join(self, event_id: int, display_name: str) -> tuple[dict, str]:
        ev = self.get_event(event_id)
        if ev["status"] == "ended":
            raise EngineError("This event has ended", 410)
        name = logic.clean_name(display_name)
        if not 1 <= len(name) <= 24:
            raise EngineError("Display name must be 1 to 24 characters")
        if self.db.one("SELECT 1 FROM guests WHERE event_id = ? AND status = 'active' "
                       "AND display_name = ? COLLATE NOCASE", (event_id, name)):
            raise EngineError("That name is already taken at this event. Try another.", 409)
        token = secrets.token_urlsafe(32)
        singing_started = self._anchor(ev) is not None
        guest_id = self.db.insert(
            "INSERT INTO guests(event_id, display_name, token_hash, rotation_pos, joined_at, debut_pending, "
            "rejoin_code) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (event_id, name, hash_token(token), logic.next_rotation_pos(self._guests(event_id, active_only=False)),
             self.clock(), int(singing_started), self._new_rejoin_code(event_id)))
        if singing_started:  # new singers join the end of the singer order; they're announced at their debut
            self.notice(event_id, f"🎉 New singer! {name} joins the end of the line-up.", "success")
        sset = self._active_set(event_id)
        if sset:  # they get a turn at the end of a Superset that's under way
            last = self.db.one("SELECT MAX(position) AS p FROM superset_slots WHERE set_id = ?", (sset["id"],))["p"]
            self.db.execute("INSERT INTO superset_slots(set_id, guest_id, position) VALUES (?, ?, ?)",
                            (sset["id"], guest_id, (last or 0) + 1))
        self.emit(event_id, "guest_joined", {"guest_id": guest_id, "name": name, "new_singer": singing_started})
        return self._guest(guest_id), token

    def _new_rejoin_code(self, event_id: int) -> str:
        while True:
            code = "".join(secrets.choice(JOIN_CODE_ALPHABET) for _ in range(6))
            if not self.db.one("SELECT 1 FROM guests WHERE event_id = ? AND rejoin_code = ?", (event_id, code)):
                return code

    def rejoin_code(self, guest_id: int) -> str:
        """A singer's personal code for getting back in on another phone (made on demand for older guests)."""
        g = self._guest(guest_id)
        if not g["rejoin_code"]:
            g["rejoin_code"] = self._new_rejoin_code(g["event_id"])
            self.db.execute("UPDATE guests SET rejoin_code = ? WHERE id = ?", (g["rejoin_code"], guest_id))
        return g["rejoin_code"]

    def rejoin(self, event_id: int, rejoin_code: str) -> tuple[dict, str]:
        """Swap a singer onto a new phone: issues a fresh token and signs the old phone out."""
        ev = self.get_event(event_id)
        if ev["status"] == "ended":
            raise EngineError("This event has ended", 410)
        code = (rejoin_code or "").strip().upper()
        g = self.db.one("SELECT * FROM guests WHERE event_id = ? AND rejoin_code = ?", (event_id, code)) \
            if len(code) == 6 else None
        if not g or g["status"] == "removed":
            raise EngineError("That rejoin code didn't match. Ask the host to check it in Host admin.", 404)
        if g["status"] == "left":
            if self.db.one("SELECT 1 FROM guests WHERE event_id = ? AND status = 'active' AND id != ? "
                           "AND display_name = ? COLLATE NOCASE", (event_id, g["id"], g["display_name"])):
                raise EngineError("Someone else is using your name now. Join again with a new name.", 409)
            self.db.execute("UPDATE guests SET status = 'active' WHERE id = ?", (g["id"],))
            self.notice(event_id, f"{g['display_name']} is back!", "success")
            self.emit(event_id, "guest_joined", {"guest_id": g["id"], "name": g["display_name"], "new_singer": False})
        token = secrets.token_urlsafe(32)
        self.db.execute("UPDATE guests SET token_hash = ? WHERE id = ?", (hash_token(token), g["id"]))
        self.emit(event_id, "session_replaced", {}, guest_id=g["id"])
        return self._guest(g["id"]), token

    def guest_by_token(self, token: str) -> dict:
        g = self.db.one("SELECT * FROM guests WHERE token_hash = ?", (hash_token(token or ""),))
        if not g or g["status"] != "active":
            raise EngineError("Your session has expired. Please join again.", 401)
        return g

    def _drop_guest(self, guest_id: int, status: str, text: str, kind: str | None = None) -> None:
        g = self._guest(guest_id)
        if g["status"] != "active":
            return
        self.db.execute("UPDATE guests SET status = ? WHERE id = ?", (status, guest_id))
        self.db.execute("UPDATE queue_items SET status = 'removed' WHERE guest_id = ? AND status = 'queued'",
                        (guest_id,))
        self.db.execute("UPDATE queue_items SET duet_guest_id = NULL WHERE duet_guest_id = ? AND status = 'queued'",
                        (guest_id,))
        sset, slot = self._my_slot(g["event_id"], guest_id)
        if slot and slot["status"] in ("pending", "picked"):
            self.db.execute("UPDATE superset_slots SET status = 'skipped' WHERE set_id = ? AND guest_id = ?",
                            (sset["id"], guest_id))
        self.emit(g["event_id"], "guest_left", {"guest_id": guest_id, "name": g["display_name"], "reason": status})
        self.notice(g["event_id"], text, kind=kind)
        self._nudge(g["event_id"])  # the Superset may have been waiting on them

    def leave(self, guest_id: int) -> None:
        g = self._guest(guest_id)
        self._drop_guest(guest_id, "left", f"{g['display_name']} has left the party.")

    def remove_guest(self, guest_id: int) -> None:
        """Host: "Bouche!" a singer off the line-up (their queued songs go too). The TV makes a show of it."""
        g = self._guest(guest_id)
        if g["status"] != "active":
            return
        self._drop_guest(guest_id, "removed", f"🥖 {g['display_name']} has been BOUCHED!", kind="bouched")
        self.emit(g["event_id"], "bouched", {"guest_id": guest_id, "name": g["display_name"]})

    def move_guest(self, guest_id: int, direction: int) -> None:
        """Host: move a singer one place earlier (-1) or later (+1) in the singer order."""
        g = self._guest(guest_id)
        order = self._guests(g["event_id"])
        idx = next(i for i, x in enumerate(order) if x["id"] == guest_id)
        j = idx + direction
        if not 0 <= j < len(order):
            return
        other = order[j]
        self.db.execute("UPDATE guests SET rotation_pos = ? WHERE id = ?", (other["rotation_pos"], guest_id))
        self.db.execute("UPDATE guests SET rotation_pos = ? WHERE id = ?", (g["rotation_pos"], other["id"]))
        self.emit(g["event_id"], "order_changed")
