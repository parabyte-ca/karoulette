"""Event engine: the single place where event state changes.

Every mutating method runs synchronously against SQLite and appends messages to
``self.outbox``; the async layer drains the outbox and broadcasts over WebSockets.
Timing is driven by ``tick()`` using persisted deadlines, so a restart resumes cleanly.
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import random
import secrets
import time
from datetime import datetime, timezone
from typing import Callable

from . import logic
from .db import Database

JOIN_CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
SEED_THEMES = [
    ("80s", "Anything released in the 1980s.", 1.0),
    ("Duets", "Grab a partner and share the mic.", 1.0),
    ("From a Soundtrack", "Songs from films, TV or musicals.", 1.0),
    ("Canadiana", "Canadian artists, coast to coast to coast.", 1.0),
    ("90s", "Anything released in the 1990s.", 1.0),
    ("Power Ballads", "Big hair, bigger choruses.", 1.0),
    ("Guilty Pleasures", "The song you secretly know every word to.", 1.0),
    ("One-Hit Wonders", "Artists famous for exactly one song.", 1.0),
]
ACTIVE_QUEUE_STATUSES = ("queued", "playing")


class EngineError(Exception):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.message = message
        self.status = status


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


class Engine:
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

    def notice(self, event_id: int, text: str, level: str = "info", guest_id: int | None = None) -> None:
        self.emit(event_id, "notice", {"text": text, "level": level}, guest_id)

    def drain(self) -> list[dict]:
        out, self.outbox = self.outbox, []
        return out

    def get_event(self, event_id: int) -> dict:
        ev = self.db.one("SELECT * FROM events WHERE id = ?", (event_id,))
        if not ev:
            raise EngineError("Event not found", 404)
        ev["config"] = logic.merge_config(json.loads(ev["config"] or "{}"), None)
        ev["bonus_queue"] = json.loads(ev["bonus_queue"] or "[]")
        return ev

    def event_by_code(self, code: str) -> dict:
        row = self.db.one("SELECT id FROM events WHERE join_code = ?", ((code or "").strip().upper(),))
        if not row:
            raise EngineError("No event with that code", 404)
        return self.get_event(row["id"])

    def _set(self, event_id: int, **fields) -> None:
        if "bonus_queue" in fields:
            fields["bonus_queue"] = json.dumps(fields["bonus_queue"])
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

    def _turn(self, turn_id: int | None) -> dict | None:
        if turn_id is None:
            return None
        return self.db.one("SELECT * FROM turns WHERE id = ?", (turn_id,))

    def _items(self, event_id: int, statuses: tuple[str, ...] | None = None) -> list[dict]:
        if statuses:
            marks = ",".join("?" * len(statuses))
            return self.db.all(f"SELECT * FROM queue_items WHERE event_id = ? AND status IN ({marks})",
                               (event_id, *statuses))
        return self.db.all("SELECT * FROM queue_items WHERE event_id = ?", (event_id,))

    # ------------------------------------------------------------------ themes

    def seed_themes(self) -> None:
        if self.db.get_setting("themes_seeded"):
            return
        now = self.clock()
        for name, desc, weight in SEED_THEMES:
            self.db.execute("INSERT OR IGNORE INTO themes(name, description, weight, enabled, created_at) "
                            "VALUES (?, ?, ?, 1, ?)", (name, desc, weight, now))
        self.db.set_setting("themes_seeded", True)

    def list_themes(self) -> list[dict]:
        return [self._theme_out(t) for t in self.db.all("SELECT * FROM themes ORDER BY name COLLATE NOCASE")]

    @staticmethod
    def _theme_out(t: dict | None) -> dict | None:
        if not t:
            return None
        return {"id": t["id"], "name": t["name"], "description": t["description"],
                "weight": t["weight"], "enabled": bool(t["enabled"])}

    def save_theme(self, data: dict, theme_id: int | None = None) -> dict:
        name = logic.clean_name(data.get("name", ""))
        if not 1 <= len(name) <= 60:
            raise EngineError("Theme name must be 1 to 60 characters")
        desc = (data.get("description") or "").strip()[:280]
        weight = float(data.get("weight", 1) if data.get("weight") is not None else 1)
        if not 0 <= weight <= 100:
            raise EngineError("Weight must be between 0 and 100")
        enabled = 1 if data.get("enabled", True) else 0
        clash = self.db.one("SELECT id FROM themes WHERE name = ? COLLATE NOCASE AND id IS NOT ?", (name, theme_id))
        if clash:
            raise EngineError("A theme with that name already exists", 409)
        if theme_id is None:
            theme_id = self.db.insert("INSERT INTO themes(name, description, weight, enabled, created_at) "
                                      "VALUES (?, ?, ?, ?, ?)", (name, desc, weight, enabled, self.clock()))
        else:
            if not self._theme(theme_id):
                raise EngineError("Theme not found", 404)
            self.db.execute("UPDATE themes SET name = ?, description = ?, weight = ?, enabled = ? WHERE id = ?",
                            (name, desc, weight, enabled, theme_id))
        return self._theme_out(self._theme(theme_id))

    def delete_theme(self, theme_id: int) -> None:
        if not self._theme(theme_id):
            raise EngineError("Theme not found", 404)
        self.db.execute("DELETE FROM themes WHERE id = ?", (theme_id,))

    def _pick_theme(self, event_id: int) -> dict | None:
        ev = self.get_event(event_id)
        history = [r["theme_id"] for r in self.db.all(
            "SELECT theme_id FROM turns WHERE event_id = ? AND theme_id IS NOT NULL ORDER BY id DESC LIMIT 50",
            (event_id,))][::-1]
        themes = self.db.all("SELECT * FROM themes")
        return logic.pick_theme(themes, history, int(ev["config"]["recent_theme_window"]), self.rng)

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
        if fields:
            self._set(event_id, **fields)
        self.emit(event_id, "event_updated")
        return self.get_event(event_id)

    def start_event(self, event_id: int) -> None:
        ev = self.get_event(event_id)
        if ev["status"] == "ended":
            raise EngineError("This event has ended")
        if ev["status"] != "active":
            self._set(event_id, status="active", started_at=ev["started_at"] or self.clock())
            self.notice(event_id, "The event has started. Let's sing!")
        if ev["turn_state"] == "idle" and not ev["rotation_paused"]:
            self._advance(event_id)
        self.emit(event_id, "event_started")

    def end_event(self, event_id: int) -> None:
        ev = self.get_event(event_id)
        if ev["status"] == "ended":
            return
        self._close_turn(ev, "skipped")
        self.db.execute("UPDATE queue_items SET status = 'removed' WHERE event_id = ? AND status = 'queued'",
                        (event_id,))
        self.db.execute("UPDATE queue_items SET status = 'played', played_at = ? "
                        "WHERE event_id = ? AND status = 'playing'", (self.clock(), event_id))
        self._set(event_id, status="ended", ended_at=self.clock(), turn_state="idle", phase_deadline=None,
                  current_turn_id=None, now_playing_item_id=None, bonus_queue=[])
        self.emit(event_id, "event_ended")
        self.notice(event_id, "Thanks for singing! This event has ended.")

    def delete_event(self, event_id: int) -> None:
        self.get_event(event_id)
        self.db.execute("DELETE FROM events WHERE id = ?", (event_id,))

    # ------------------------------------------------------------------ guests

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
        pos = logic.next_rotation_pos(self._guests(event_id, active_only=False))
        guest_id = self.db.insert(
            "INSERT INTO guests(event_id, display_name, token_hash, rotation_pos, joined_at) VALUES (?, ?, ?, ?, ?)",
            (event_id, name, hash_token(token), pos, self.clock()))
        guest = self._guest(guest_id)
        self.emit(event_id, "guest_joined", {"guest_id": guest_id, "name": name})
        if ev["status"] == "active" and ev["turn_state"] == "idle" and not ev["rotation_paused"]:
            self._advance(event_id)
        return guest, token

    def guest_by_token(self, token: str) -> dict:
        g = self.db.one("SELECT * FROM guests WHERE token_hash = ?", (hash_token(token or ""),))
        if not g or g["status"] != "active":
            raise EngineError("Your session has expired. Please join again.", 401)
        return g

    def _drop_guest(self, guest_id: int, status: str, text: str) -> None:
        g = self._guest(guest_id)
        if g["status"] != "active":
            return
        event_id = g["event_id"]
        self.db.execute("UPDATE guests SET status = ? WHERE id = ?", (status, guest_id))
        self.db.execute("UPDATE queue_items SET status = 'removed' WHERE guest_id = ? AND status = 'queued'",
                        (guest_id,))
        ev = self.get_event(event_id)
        bonus = [b for b in ev["bonus_queue"] if b["guest_id"] != guest_id]
        self._set(event_id, bonus_queue=bonus)
        self.emit(event_id, "guest_left", {"guest_id": guest_id, "name": g["display_name"], "reason": status})
        self.notice(event_id, text)
        turn = self._turn(ev["current_turn_id"])
        if turn and turn["guest_id"] == guest_id and turn["outcome"] is None:
            self._close_turn(ev, status)
            self._advance(event_id)

    def leave(self, guest_id: int) -> None:
        g = self._guest(guest_id)
        self._drop_guest(guest_id, "left", f"{g['display_name']} has left the party.")

    def remove_guest(self, guest_id: int) -> None:
        g = self._guest(guest_id)
        self._drop_guest(guest_id, "removed", f"{g['display_name']} was removed by the host.")

    def skip_guest(self, guest_id: int) -> None:
        g = self._guest(guest_id)
        ev = self.get_event(g["event_id"])
        turn = self._turn(ev["current_turn_id"])
        if turn and turn["guest_id"] == guest_id and turn["outcome"] is None:
            self.skip_turn(ev["id"])
        else:
            self.db.execute("UPDATE guests SET skip_next = 1 WHERE id = ?", (guest_id,))
            self.notice(ev["id"], f"{g['display_name']} will be skipped next time around.")
            self.emit(ev["id"], "guest_updated", {"guest_id": guest_id})

    # ------------------------------------------------------------------ rotation

    def _close_turn(self, ev: dict, outcome: str) -> None:
        turn = self._turn(ev["current_turn_id"])
        if turn and turn["outcome"] is None:
            self.db.execute("UPDATE turns SET outcome = ?, ended_at = ? WHERE id = ?",
                            (outcome, self.clock(), turn["id"]))
        self._set(ev["id"], current_turn_id=None, turn_state="idle", phase_deadline=None, paused_remaining=None)

    def _start_round(self, event_id: int) -> dict:
        ev = self.get_event(event_id)
        number = ev["current_round"] + 1
        superset = logic.roll_superset(float(ev["config"]["superset_chance"]), ev["superset_pending"], self.rng)
        theme = self._pick_theme(event_id) if superset else None
        if superset and not theme:
            superset = False
        round_id = self.db.insert(
            "INSERT INTO rounds(event_id, number, is_superset, superset_theme_id, started_at) VALUES (?, ?, ?, ?, ?)",
            (event_id, number, int(superset), theme["id"] if theme else None, self.clock()))
        self._set(event_id, current_round=number, current_round_id=round_id, superset_pending=None)
        self.emit(event_id, "round_changed", {"number": number, "is_superset": superset,
                                              "theme": self._theme_out(theme)})
        if superset:
            self.emit(event_id, "superset", {"active": True, "round": number, "theme": self._theme_out(theme)})
        return self._round(round_id)

    def _advance(self, event_id: int) -> None:
        """Start the next turn.

        Priority: a bonus re-pick (embed error), then a passed singer whose one-singer wait is
        over, then the next guest in the fixed rotation.
        """
        ev = self.get_event(event_id)
        if ev["status"] != "active" or ev["rotation_paused"]:
            self._set(event_id, turn_state="idle", current_turn_id=None, phase_deadline=None)
            return
        guests = self._guests(event_id)
        if not guests:
            self._set(event_id, turn_state="idle", current_turn_id=None, phase_deadline=None)
            return
        active_ids = {g["id"] for g in guests}
        pending = [b for b in ev["bonus_queue"] if b["guest_id"] in active_ids]
        for b in pending:
            # If the singer they let go first has left, the wait is over.
            if b.get("kind") == "deferred" and b.get("after_guest_id") not in active_ids:
                b["ready"] = True
        entry = next((b for b in pending if b.get("kind") != "deferred" or b.get("ready")), None)
        now = self.clock()
        cfg = ev["config"]

        if entry:
            pending.remove(entry)
            if ev["current_round_id"] is None:
                self._start_round(event_id)
                ev = self.get_event(event_id)
            guest = next(g for g in guests if g["id"] == entry["guest_id"])
            if entry.get("kind") == "deferred":
                # Their regular turn, just moved one singer later. Rotation cursor stays put.
                theme = self._turn_theme(event_id)
                is_bonus = False
            else:
                theme = self._theme(entry.get("theme_id"))
                is_bonus = True
        else:
            guest, wrapped, skipped = logic.next_in_rotation(guests, ev["cursor_pos"])
            for gid in skipped:
                self.db.execute("UPDATE guests SET skip_next = 0 WHERE id = ?", (gid,))
                skipped_name = next(g["display_name"] for g in guests if g["id"] == gid)
                self.notice(event_id, f"Skipping {skipped_name} this time around.")
            if wrapped or ev["current_round_id"] is None:
                self._start_round(event_id)
            ev = self.get_event(event_id)
            theme = self._turn_theme(event_id)
            self._set(event_id, cursor_pos=guest["rotation_pos"])
            is_bonus = False

        for b in pending:
            if b.get("kind") == "deferred" and b.get("after_guest_id") == guest["id"]:
                b["ready"] = True
        self._set(event_id, bonus_queue=pending)

        turn_id = self.db.insert(
            "INSERT INTO turns(event_id, round_id, guest_id, theme_id, theme_name, is_bonus, started_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (event_id, ev["current_round_id"], guest["id"], theme["id"] if theme else None,
             theme["name"] if theme else None, int(is_bonus), now))
        self._set(event_id, current_turn_id=turn_id, turn_state="announcing",
                  phase_deadline=now + int(cfg["announce_seconds"]), paused_remaining=None)
        self.emit(event_id, "turn_changed", {"guest_id": guest["id"], "name": guest["display_name"],
                                             "is_bonus": is_bonus, "round": ev["current_round"]})
        if is_bonus:
            self.emit(event_id, "your_turn", {"bonus": True}, guest_id=guest["id"])
        if int(cfg["announce_seconds"]) == 0:
            self.tick(now)

    def _turn_theme(self, event_id: int) -> dict | None:
        ev = self.get_event(event_id)
        rnd = self._round(ev["current_round_id"])
        if rnd and rnd["is_superset"]:
            return self._theme(rnd["superset_theme_id"])
        return self._pick_theme(event_id)

    def _next_singer_preview(self, ev: dict, exclude_id: int) -> dict | None:
        """Who would pick next if ``exclude_id`` stepped aside right now."""
        guests = [g for g in self._guests(ev["id"]) if g["id"] != exclude_id]
        by_id = {g["id"]: g for g in guests}
        for b in ev["bonus_queue"]:
            if b["guest_id"] in by_id and (b.get("kind") != "deferred" or b.get("ready")):
                return by_id[b["guest_id"]]
        guest, _, _ = logic.next_in_rotation(guests, ev["cursor_pos"])
        return guest

    def pass_turn(self, guest_id: int) -> None:
        """The singer lets the next person go first and picks right after them."""
        guest = self._guest(guest_id)
        ev = self.get_event(guest["event_id"])
        turn = self._turn(ev["current_turn_id"])
        if ev["status"] != "active" or not turn or turn["guest_id"] != guest_id or turn["outcome"] is not None:
            raise EngineError("It isn't your turn right now.", 409)
        after = self._next_singer_preview(ev, guest_id)
        if not after:
            raise EngineError("There's nobody else to go ahead of you. Pick a song when you're ready!", 409)
        self._close_turn(ev, "passed")
        pending = [b for b in ev["bonus_queue"] if b["guest_id"] != guest_id]
        pending.append({"guest_id": guest_id, "kind": "deferred", "after_guest_id": after["id"], "ready": False})
        self._set(ev["id"], bonus_queue=pending)
        self.notice(ev["id"], f"{guest['display_name']} passed. {after['display_name']} goes first, "
                              f"then {guest['display_name']} picks.")
        self._advance(ev["id"])

    def _needs_spin(self, ev: dict, turn: dict) -> bool:
        if turn["is_bonus"]:
            return False
        rnd = self._round(turn["round_id"])
        if rnd and rnd["is_superset"]:
            first = self.db.one("SELECT MIN(id) AS first FROM turns WHERE round_id = ? AND is_bonus = 0",
                                (rnd["id"],))
            return first["first"] == turn["id"]
        return True

    def _enter_spin(self, ev: dict, turn: dict, now: float) -> None:
        rnd = self._round(turn["round_id"])
        superset = bool(rnd and rnd["is_superset"])
        spin = int(ev["config"]["spin_seconds"]) + (2 if superset else 0)
        self._set(ev["id"], turn_state="spinning", phase_deadline=now + spin)
        themes = [self._theme_out(t) for t in self.db.all("SELECT * FROM themes WHERE enabled = 1 ORDER BY name")]
        self.emit(ev["id"], "theme_spun", {
            "guest_id": turn["guest_id"], "theme": self._theme_out(self._theme(turn["theme_id"])) or
            ({"id": None, "name": turn["theme_name"], "description": ""} if turn["theme_name"] else None),
            "superset": superset, "duration": spin, "candidates": [t["name"] for t in themes]})

    def _enter_choosing(self, ev: dict, turn: dict, now: float) -> None:
        self._set(ev["id"], turn_state="choosing", phase_deadline=now + int(ev["config"]["turn_seconds"]))
        self.emit(ev["id"], "your_turn", {"bonus": bool(turn["is_bonus"])}, guest_id=turn["guest_id"])

    def tick(self, now: float | None = None) -> bool:
        """Advance any phases whose deadline has passed. Returns True if anything changed."""
        now = self.clock() if now is None else now
        changed = False
        for row in self.db.all("SELECT id FROM events WHERE status = 'active' AND rotation_paused = 0 "
                               "AND phase_deadline IS NOT NULL AND phase_deadline <= ?", (now,)):
            ev = self.get_event(row["id"])
            turn = self._turn(ev["current_turn_id"])
            if not turn:
                self._set(ev["id"], turn_state="idle", phase_deadline=None)
                continue
            changed = True
            if ev["turn_state"] == "announcing":
                if self._needs_spin(ev, turn):
                    self._enter_spin(ev, turn, now)
                else:
                    self._enter_choosing(ev, turn, now)
            elif ev["turn_state"] == "spinning":
                self._enter_choosing(ev, turn, now)
            elif ev["turn_state"] == "choosing":
                # Time's up, but nobody loses their turn: they keep picking until they add a
                # song or choose to pass. The host can still skip them.
                guest = self._guest(turn["guest_id"])
                self._set(ev["id"], turn_state="overtime", phase_deadline=None)
                self.notice(ev["id"], f"{guest['display_name']}'s time is up, but they can still pick a song "
                                      "or pass.", "warning")
                self.emit(ev["id"], "turn_overtime", {"guest_id": guest["id"]}, guest_id=guest["id"])
        return changed

    def pause_rotation(self, event_id: int) -> None:
        ev = self.get_event(event_id)
        if ev["rotation_paused"]:
            return
        remaining = max(0.0, ev["phase_deadline"] - self.clock()) if ev["phase_deadline"] else None
        self._set(event_id, rotation_paused=1, paused_remaining=remaining, phase_deadline=None)
        self.notice(event_id, "The host paused the rotation.")
        self.emit(event_id, "rotation_paused", {"paused": True})

    def resume_rotation(self, event_id: int) -> None:
        ev = self.get_event(event_id)
        if not ev["rotation_paused"]:
            return
        deadline = self.clock() + ev["paused_remaining"] if ev["paused_remaining"] is not None else None
        self._set(event_id, rotation_paused=0, paused_remaining=None, phase_deadline=deadline)
        self.notice(event_id, "The rotation is back on.")
        self.emit(event_id, "rotation_paused", {"paused": False})
        ev = self.get_event(event_id)
        if ev["status"] == "active" and (ev["turn_state"] == "idle" or not ev["current_turn_id"]):
            self._advance(event_id)

    def skip_turn(self, event_id: int) -> None:
        ev = self.get_event(event_id)
        turn = self._turn(ev["current_turn_id"])
        if not turn:
            raise EngineError("Nobody is up right now")
        guest = self._guest(turn["guest_id"])
        self._close_turn(ev, "skipped")
        self.notice(event_id, f"The host skipped {guest['display_name']}'s turn.")
        self._advance(event_id)

    def force_spin(self, event_id: int) -> None:
        ev = self.get_event(event_id)
        turn = self._turn(ev["current_turn_id"])
        if not turn:
            raise EngineError("Nobody is up right now, so there is nothing to spin")
        rnd = self._round(turn["round_id"])
        theme = self._pick_theme(event_id)
        if not theme:
            raise EngineError("Add or enable at least one theme first")
        if rnd and rnd["is_superset"] and not turn["is_bonus"]:
            self.db.execute("UPDATE rounds SET superset_theme_id = ? WHERE id = ?", (theme["id"], rnd["id"]))
            self.emit(event_id, "superset", {"active": True, "round": rnd["number"], "theme": self._theme_out(theme)})
        self.db.execute("UPDATE turns SET theme_id = ?, theme_name = ? WHERE id = ?",
                        (theme["id"], theme["name"], turn["id"]))
        self._enter_spin(ev, self._turn(turn["id"]), self.clock())

    def force_superset(self, event_id: int) -> None:
        self.get_event(event_id)
        self._set(event_id, superset_pending="force")
        self.notice(event_id, "A Superset round is coming up next round!")
        self.emit(event_id, "superset", {"active": False, "pending": "force"})

    def cancel_superset(self, event_id: int) -> None:
        ev = self.get_event(event_id)
        rnd = self._round(ev["current_round_id"])
        if ev["superset_pending"] == "force":
            self._set(event_id, superset_pending=None)
            self.notice(event_id, "The upcoming Superset round was cancelled.")
        elif rnd and rnd["is_superset"]:
            self.db.execute("UPDATE rounds SET is_superset = 0 WHERE id = ?", (rnd["id"],))
            self.notice(event_id, "The host ended the Superset. Themes spin per turn again.")
        else:
            self._set(event_id, superset_pending="cancel")
            self.notice(event_id, "No Superset next round.")
        self.emit(event_id, "superset", {"active": False, "pending": self.get_event(event_id)["superset_pending"]})

    # ------------------------------------------------------------------ queue

    def queue_song(self, guest_id: int, video: dict) -> dict:
        guest = self._guest(guest_id)
        ev = self.get_event(guest["event_id"])
        if ev["status"] != "active":
            raise EngineError("The event isn't running right now")
        turn = self._turn(ev["current_turn_id"])
        if not turn or turn["guest_id"] != guest_id or ev["turn_state"] not in ("spinning", "choosing", "overtime"):
            raise EngineError("It isn't your turn yet. Hang tight!", 409)
        if ev["config"]["prevent_duplicates"] and logic.is_duplicate(self._items(ev["id"]), video["video_id"]):
            raise EngineError("That song has already been sung or queued tonight. Pick another!", 409)
        max_d = int(ev["config"]["max_duration_s"])
        if max_d and video.get("duration_s") and video["duration_s"] > max_d:
            raise EngineError(f"That video is longer than the {max_d // 60}-minute limit")
        rnd = self._round(turn["round_id"])
        items = self._items(ev["id"], ("queued",))
        item_id = self.db.insert(
            "INSERT INTO queue_items(event_id, guest_id, turn_id, round_id, theme_name, is_superset, video_id, title, "
            "channel, duration_s, thumbnail, position, added_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (ev["id"], guest_id, turn["id"], turn["round_id"], turn["theme_name"],
             int(bool(rnd and rnd["is_superset"])), video["video_id"], video["title"][:200],
             (video.get("channel") or "")[:120], video.get("duration_s"), video.get("thumbnail") or "",
             logic.append_position(items), self.clock()))
        self.emit(ev["id"], "song_queued", {"item_id": item_id, "guest_id": guest_id,
                                            "name": guest["display_name"], "title": video["title"]})
        self._close_turn(ev, "queued")
        if ev["config"]["autoplay"] and not ev["now_playing_item_id"]:
            self.play_next(ev["id"])
        self._advance(ev["id"])
        return self.db.one("SELECT * FROM queue_items WHERE id = ?", (item_id,))

    def remove_item(self, event_id: int, item_id: int, by_guest_id: int | None = None) -> None:
        item = self.db.one("SELECT * FROM queue_items WHERE id = ? AND event_id = ?", (item_id, event_id))
        if not item or item["status"] not in ACTIVE_QUEUE_STATUSES:
            raise EngineError("Song not found in the queue", 404)
        if by_guest_id is not None and item["guest_id"] != by_guest_id:
            raise EngineError("You can only remove your own songs", 403)
        if item["status"] == "playing":
            self.skip_song(event_id)
            return
        self.db.execute("UPDATE queue_items SET status = 'removed' WHERE id = ?", (item_id,))
        self.emit(event_id, "song_removed", {"item_id": item_id, "title": item["title"]})

    def reorder(self, event_id: int, ordered_ids: list[int]) -> None:
        current = [i["id"] for i in logic.play_order(self._items(event_id, ("queued",)))]
        if sorted(current) != sorted(ordered_ids):
            raise EngineError("The queue changed. Refresh and try again.", 409)
        with self.db.transaction():
            for pos, item_id in enumerate(ordered_ids, start=1):
                self.db.execute("UPDATE queue_items SET position = ? WHERE id = ?", (float(pos), item_id))
        self.emit(event_id, "queue_reordered")

    def move_item(self, event_id: int, item_id: int, new_index: int) -> None:
        current = [i["id"] for i in logic.play_order(self._items(event_id, ("queued",)))]
        try:
            self.reorder(event_id, logic.move_item(current, item_id, new_index))
        except ValueError as exc:
            raise EngineError(str(exc), 404) from exc

    def flag_item(self, event_id: int, item_id: int, flagged_by: str) -> int:
        item = self.db.one("SELECT * FROM queue_items WHERE id = ? AND event_id = ?", (item_id, event_id))
        if not item or item["status"] not in ACTIVE_QUEUE_STATUSES:
            raise EngineError("Song not found in the queue", 404)
        if not item["is_superset"]:
            raise EngineError("Songs can only be flagged during a Superset round")
        if flagged_by == f"guest:{item['guest_id']}":
            raise EngineError("You can't flag your own song")
        self.db.execute("INSERT OR IGNORE INTO flags(queue_item_id, flagged_by, created_at) VALUES (?, ?, ?)",
                        (item_id, flagged_by, self.clock()))
        count = self.db.one("SELECT COUNT(*) AS n FROM flags WHERE queue_item_id = ?", (item_id,))["n"]
        self.emit(event_id, "song_flagged", {"item_id": item_id, "count": count, "title": item["title"]})
        return count

    # ------------------------------------------------------------------ playback

    def play_next(self, event_id: int) -> dict | None:
        ev = self.get_event(event_id)
        if ev["now_playing_item_id"]:
            self.db.execute("UPDATE queue_items SET status = 'played', played_at = ? WHERE id = ? AND status = 'playing'",
                            (self.clock(), ev["now_playing_item_id"]))
        nxt = logic.play_order(self._items(event_id, ("queued",)))
        if not nxt:
            self._set(event_id, now_playing_item_id=None)
            self.emit(event_id, "now_playing", {"item": None})
            return None
        item = nxt[0]
        self.db.execute("UPDATE queue_items SET status = 'playing', played_at = ? WHERE id = ?",
                        (self.clock(), item["id"]))
        self._set(event_id, now_playing_item_id=item["id"])
        guest = self._guest(item["guest_id"])
        self.emit(event_id, "now_playing", {"item_id": item["id"], "video_id": item["video_id"],
                                            "title": item["title"], "guest_id": guest["id"],
                                            "name": guest["display_name"]})
        self.emit(event_id, "you_are_singing", {"title": item["title"]}, guest_id=guest["id"])
        if len(nxt) > 1:
            self.emit(event_id, "you_are_next", {"title": nxt[1]["title"]}, guest_id=nxt[1]["guest_id"])
        return item

    def player_ended(self, event_id: int, item_id: int) -> None:
        ev = self.get_event(event_id)
        if ev["now_playing_item_id"] != item_id:
            return  # duplicate or stale report from another tab
        self.play_next(event_id)

    def skip_song(self, event_id: int) -> None:
        ev = self.get_event(event_id)
        if not ev["now_playing_item_id"]:
            self.play_next(event_id)
            return
        self.db.execute("UPDATE queue_items SET status = 'skipped' WHERE id = ?", (ev["now_playing_item_id"],))
        self._set(event_id, now_playing_item_id=None)
        self.notice(event_id, "The host skipped the current song.")
        self.play_next(event_id)

    def stop_playback(self, event_id: int) -> None:
        ev = self.get_event(event_id)
        if ev["now_playing_item_id"]:
            # Put the current song back at the top of the queue.
            items = logic.play_order(self._items(event_id, ("queued",)))
            top = (items[0]["position"] - 1.0) if items else 1.0
            self.db.execute("UPDATE queue_items SET status = 'queued', position = ?, played_at = NULL WHERE id = ?",
                            (top, ev["now_playing_item_id"]))
            self._set(event_id, now_playing_item_id=None)
            self.emit(event_id, "now_playing", {"item": None})

    def player_error(self, event_id: int, item_id: int, code: int) -> None:
        ev = self.get_event(event_id)
        if ev["now_playing_item_id"] != item_id:
            return
        item = self.db.one("SELECT * FROM queue_items WHERE id = ?", (item_id,))
        self.db.execute("UPDATE queue_items SET status = 'error', error_code = ? WHERE id = ?", (code, item_id))
        self._set(event_id, now_playing_item_id=None)
        guest = self._guest(item["guest_id"])
        reason = "can't be played outside YouTube" if code in (101, 150) else "couldn't be played"
        follow_up = f", and {guest['display_name']} gets to pick again" if guest["status"] == "active" else ""
        self.notice(event_id, f"“{item['title']}” {reason}. Skipping it{follow_up}.", "warning")
        if guest["status"] == "active":
            turn = self._turn(item["turn_id"])
            bonus = ev["bonus_queue"] + [{"guest_id": guest["id"], "theme_id": turn["theme_id"] if turn else None}]
            self._set(event_id, bonus_queue=bonus)
            self.emit(event_id, "song_error", {"item_id": item_id, "code": code, "title": item["title"]},
                      guest_id=guest["id"])
            ev = self.get_event(event_id)
            if ev["status"] == "active" and ev["turn_state"] == "idle" and not ev["rotation_paused"]:
                self._advance(event_id)
        self.play_next(event_id)

    # ------------------------------------------------------------------ views

    def snapshot(self, event_id: int) -> dict:
        ev = self.get_event(event_id)
        now = self.clock()
        guests_all = self._guests(event_id, active_only=False)
        names = {g["id"]: g["display_name"] for g in guests_all}
        active = [g for g in guests_all if g["status"] == "active"]
        turn = self._turn(ev["current_turn_id"])
        rnd = self._round(ev["current_round_id"])
        flag_counts = {r["queue_item_id"]: r["n"] for r in self.db.all(
            "SELECT f.queue_item_id, COUNT(*) AS n FROM flags f JOIN queue_items q ON q.id = f.queue_item_id "
            "WHERE q.event_id = ? GROUP BY f.queue_item_id", (event_id,))}

        def item_out(i: dict) -> dict:
            return {"id": i["id"], "video_id": i["video_id"], "title": i["title"], "channel": i["channel"],
                    "duration_s": i["duration_s"], "thumbnail": i["thumbnail"], "guest_id": i["guest_id"],
                    "guest_name": names.get(i["guest_id"], "?"), "theme": i["theme_name"],
                    "is_superset": bool(i["is_superset"]), "flags": flag_counts.get(i["id"], 0),
                    "status": i["status"]}

        queue = [item_out(i) for i in logic.play_order(self._items(event_id, ("queued",)))]
        playing = self.db.one("SELECT * FROM queue_items WHERE id = ?", (ev["now_playing_item_id"],)) \
            if ev["now_playing_item_id"] else None
        recent = [item_out(i) for i in self.db.all(
            "SELECT * FROM queue_items WHERE event_id = ? AND status = 'played' ORDER BY played_at DESC LIMIT 10",
            (event_id,))]
        history = [{"round_id": t["round_id"], "guest_name": names.get(t["guest_id"], "?"),
                    "theme": t["theme_name"], "outcome": t["outcome"], "is_bonus": bool(t["is_bonus"])}
                   for t in self.db.all("SELECT * FROM turns WHERE event_id = ? ORDER BY id DESC LIMIT 12",
                                        (event_id,))]
        superset_theme = self._theme_out(self._theme(rnd["superset_theme_id"])) if rnd and rnd["is_superset"] else None
        deadline = ev["phase_deadline"]
        turn_out = None
        if turn:
            theme = self._theme(turn["theme_id"])
            hide_theme = ev["turn_state"] == "announcing" and self._needs_spin(ev, turn)
            turn_out = {
                "id": turn["id"], "guest_id": turn["guest_id"], "guest_name": names.get(turn["guest_id"], "?"),
                "is_bonus": bool(turn["is_bonus"]), "state": ev["turn_state"],
                "theme": None if hide_theme else (self._theme_out(theme) or (
                    {"id": None, "name": turn["theme_name"], "description": ""} if turn["theme_name"] else None)),
                "deadline": deadline, "remaining": max(0.0, deadline - now) if deadline else ev["paused_remaining"],
            }
        upcoming = logic.upcoming_order(active, ev["cursor_pos"], exclude_id=turn["guest_id"] if turn else None,
                                        pending=ev["bonus_queue"])
        return {
            "server_time": now,
            "event": {"id": ev["id"], "name": ev["name"], "join_code": ev["join_code"], "status": ev["status"],
                      "config": ev["config"], "rotation_paused": bool(ev["rotation_paused"]),
                      "superset_pending": ev["superset_pending"]},
            "round": {"number": ev["current_round"], "is_superset": bool(rnd and rnd["is_superset"]),
                      "theme": superset_theme},
            "turn": turn_out,
            "guests": [{"id": g["id"], "name": g["display_name"], "rotation_pos": g["rotation_pos"],
                        "skip_next": bool(g["skip_next"])} for g in active],
            "upcoming": upcoming,
            "bonus_queue": [b["guest_id"] for b in ev["bonus_queue"]],
            "passed": [{"guest_id": b["guest_id"], "after_guest_id": b.get("after_guest_id"), "ready": b.get("ready")}
                       for b in ev["bonus_queue"] if b.get("kind") == "deferred"],
            "queue": queue,
            "now_playing": item_out(playing) if playing else None,
            "recent": recent,
            "theme_history": history,
        }

    def history_csv(self, event_id: int) -> str:
        ev = self.get_event(event_id)
        rows = self.db.all(
            "SELECT q.*, g.display_name, r.number AS round_number FROM queue_items q "
            "JOIN guests g ON g.id = q.guest_id LEFT JOIN rounds r ON r.id = q.round_id "
            "WHERE q.event_id = ? AND q.status IN ('played', 'playing', 'skipped', 'error') "
            "ORDER BY COALESCE(q.played_at, q.added_at)", (event_id,))
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(["event", "played_at_utc", "round", "superset", "theme", "singer", "title", "channel",
                    "duration_s", "status", "youtube_url"])
        for r in rows:
            ts = datetime.fromtimestamp(r["played_at"] or r["added_at"], tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
            w.writerow([ev["name"], ts, r["round_number"] or "", "yes" if r["is_superset"] else "no",
                        r["theme_name"] or "", r["display_name"], r["title"], r["channel"], r["duration_s"] or "",
                        r["status"], f"https://www.youtube.com/watch?v={r['video_id']}"])
        return buf.getvalue()
