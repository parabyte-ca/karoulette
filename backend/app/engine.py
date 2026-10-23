"""Event engine: the single place where event state changes.

Every mutating method runs synchronously against SQLite and appends messages to
``self.outbox``; the async layer drains the outbox and broadcasts over WebSockets.

Singers add songs whenever they like. The play order is a fair round-robin: each singer has at
most one song per round, and within a round songs follow the singer order.
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
COLOUR_SCHEMES = ("neon", "onair", "synthwave", "velvet", "aurora", "disco")
DEFAULT_SCHEME = "neon"
REACTIONS = ("👏", "🔥", "😂", "❤️", "🎉", "🤘")
VIDEO_COMMANDS = ("toggle", "volume_up", "volume_down")
UNKNOWN_DURATION_S = 240  # what the recap and wait estimates assume when YouTube gave no length


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

    def notice(self, event_id: int, text: str, level: str = "info", guest_id: int | None = None,
               kind: str | None = None) -> None:
        """A toast for phones and the TV. ``kind`` tags notices the TV already shows as a big banner."""
        data = {"text": text, "level": level, **({"kind": kind} if kind else {})}
        self.emit(event_id, "notice", data, guest_id)

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
            "SELECT theme_id FROM rounds WHERE event_id = ? AND theme_id IS NOT NULL ORDER BY id DESC LIMIT 50",
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
        self._set(event_id, status="ended", ended_at=self.clock(), now_playing_item_id=None, ready_until=None,
                  paused=0)
        self.emit(event_id, "event_ended")
        self.notice(event_id, "Thanks for singing! This event has ended.")

    def delete_event(self, event_id: int) -> None:
        self.get_event(event_id)
        self.db.execute("DELETE FROM events WHERE id = ?", (event_id,))

    # ------------------------------------------------------------------ singer order

    def _anchor(self, ev: dict) -> dict | None:
        """The singer on the mic, or the last one to sing in the current round."""
        item = None
        if ev["now_playing_item_id"]:
            item = self.db.one("SELECT * FROM queue_items WHERE id = ?", (ev["now_playing_item_id"],))
        if item is None and ev["current_round"]:
            item = self.db.one(
                "SELECT * FROM queue_items WHERE event_id = ? AND status IN ('played', 'skipped', 'error') "
                "AND COALESCE(round_no, ?) = ? AND priority IS NULL ORDER BY played_at DESC, id DESC LIMIT 1",
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
        self.emit(g["event_id"], "guest_left", {"guest_id": guest_id, "name": g["display_name"], "reason": status})
        self.notice(g["event_id"], text, kind=kind)

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

    # ------------------------------------------------------------------ rounds and themes

    def _start_round(self, event_id: int, number: int) -> dict:
        """A round is one pass through the singer order. Each gets a theme spin (and maybe a Superset)."""
        ev = self.get_event(event_id)
        superset = logic.roll_superset(float(ev["config"]["superset_chance"]), ev["superset_pending"], self.rng)
        theme = self._pick_theme(event_id)
        if not theme:
            superset = False
        round_id = self.db.insert(
            "INSERT INTO rounds(event_id, number, is_superset, superset_theme_id, theme_id, theme_name, spun_at, "
            "started_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (event_id, number, int(superset), theme["id"] if superset else None, theme["id"] if theme else None,
             theme["name"] if theme else None, self.clock(), self.clock()))
        if self._open_vote(event_id):
            self._close_vote(self._open_vote(event_id), "cancelled",
                             "The round ended before the Superset vote finished.")
        self._set(event_id, current_round=number, current_round_id=round_id, superset_pending=None)
        self.emit(event_id, "round_changed", {"number": number, "is_superset": superset,
                                              "theme": self._theme_out(theme)})
        self._emit_spin(event_id, number, theme, superset)
        return self._round(round_id)

    def _emit_spin(self, event_id: int, number: int, theme: dict | None, superset: bool) -> None:
        ev = self.get_event(event_id)
        candidates = [t["name"] for t in self.db.all("SELECT name FROM themes WHERE enabled = 1 ORDER BY name")]
        self.emit(event_id, "theme_spun", {"round": number, "theme": self._theme_out(theme), "superset": superset,
                                           "duration": int(ev["config"]["spin_seconds"]) + (2 if superset else 0),
                                           "candidates": candidates})
        if superset:
            self.emit(event_id, "superset", {"active": True, "round": number, "theme": self._theme_out(theme)})

    def force_spin(self, event_id: int) -> None:
        ev = self.get_event(event_id)
        rnd = self._round(ev["current_round_id"])
        if not rnd:
            raise EngineError("Start the event first; the first round spins its theme then.")
        theme = self._pick_theme(event_id)
        if not theme:
            raise EngineError("Add or enable at least one theme first")
        self.db.execute("UPDATE rounds SET theme_id = ?, theme_name = ?, spun_at = ?, "
                        "superset_theme_id = CASE WHEN is_superset = 1 THEN ? ELSE superset_theme_id END WHERE id = ?",
                        (theme["id"], theme["name"], self.clock(), theme["id"], rnd["id"]))
        self._emit_spin(event_id, rnd["number"], theme, bool(rnd["is_superset"]))

    def force_superset(self, event_id: int) -> None:
        self.get_event(event_id)
        self._set(event_id, superset_pending="force")
        self.notice(event_id, "A Superset round is coming up next round!")
        self.emit(event_id, "superset", {"active": False, "pending": "force"})

    def cancel_superset(self, event_id: int) -> None:
        ev = self.get_event(event_id)
        rnd = self._round(ev["current_round_id"])
        vote = self._open_vote(event_id)
        if vote:
            self._close_vote(vote, "cancelled", "The host cancelled the Superset vote.")
        elif ev["superset_pending"] == "force":
            self._set(event_id, superset_pending=None)
            self.notice(event_id, "The upcoming Superset round was cancelled.")
        elif rnd and rnd["is_superset"]:
            self.db.execute("UPDATE rounds SET is_superset = 0 WHERE id = ?", (rnd["id"],))
            self.notice(event_id, "The host ended the Superset. The theme is just a suggestion again.")
        else:
            self._set(event_id, superset_pending="cancel")
            self.notice(event_id, "No Superset next round.")
        self.emit(event_id, "superset", {"active": False, "pending": self.get_event(event_id)["superset_pending"]})

    # ------------------------------------------------------------------ Superset votes

    def _open_vote(self, event_id: int) -> dict | None:
        return self.db.one("SELECT * FROM superset_votes WHERE event_id = ? AND status = 'open'", (event_id,))

    def _vote_counts(self, vote: dict) -> tuple[int, int, int]:
        """(yes, no, eligible): everyone still at the event except the singer who called it votes."""
        ballots = self.db.all("SELECT b.yes FROM superset_ballots b JOIN guests g ON g.id = b.guest_id "
                              "WHERE b.vote_id = ? AND g.status = 'active'", (vote["id"],))
        yes = sum(1 for b in ballots if b["yes"])
        eligible = sum(1 for g in self._guests(vote["event_id"]) if g["id"] != vote["called_by"])
        return yes, len(ballots) - yes, eligible

    def call_superset_vote(self, guest_id: int) -> dict:
        """Any singer can call a Superset for the round in progress; the others vote and the majority wins."""
        guest = self._guest(guest_id)
        ev = self.get_event(guest["event_id"])
        rnd = self._round(ev["current_round_id"])
        if ev["status"] != "active" or not rnd:
            raise EngineError("A Superset can be called once the event has started.", 409)
        if rnd["is_superset"]:
            raise EngineError("This round is already a Superset!", 409)
        if not rnd["theme_name"]:
            raise EngineError("This round has no theme to sing to.", 409)
        if self._open_vote(ev["id"]):
            raise EngineError("A Superset vote is already under way. Cast your vote!", 409)
        if self.db.one("SELECT 1 FROM superset_votes WHERE round_id = ? AND called_by = ?", (rnd["id"], guest_id)):
            raise EngineError("You've already called a Superset this round.", 409)
        if not any(g["id"] != guest_id for g in self._guests(ev["id"])):
            raise EngineError("You need at least one other singer to vote on it.", 409)
        now = self.clock()
        vote_id = self.db.insert(
            "INSERT INTO superset_votes(event_id, round_id, called_by, started_at, ends_at) VALUES (?, ?, ?, ?, ?)",
            (ev["id"], rnd["id"], guest_id, now, now + int(ev["config"]["superset_vote_seconds"])))
        self.notice(ev["id"], f"★ {guest['display_name']} calls a SUPERSET on “{rnd['theme_name']}”! "
                              "Vote on your phone.", "gold")
        self.emit(ev["id"], "superset_vote", {"status": "open", "name": guest["display_name"],
                                              "theme": rnd["theme_name"]})
        return self.db.one("SELECT * FROM superset_votes WHERE id = ?", (vote_id,))

    def vote_superset(self, guest_id: int, yes: bool) -> None:
        guest = self._guest(guest_id)
        vote = self._open_vote(guest["event_id"])
        if not vote:
            raise EngineError("There's no Superset vote right now.", 409)
        if vote["called_by"] == guest_id:
            raise EngineError("You called this one, so it's up to everyone else.", 409)
        self.db.execute("INSERT INTO superset_ballots(vote_id, guest_id, yes) VALUES (?, ?, ?) "
                        "ON CONFLICT(vote_id, guest_id) DO UPDATE SET yes = excluded.yes",
                        (vote["id"], guest_id, int(bool(yes))))
        self.emit(guest["event_id"], "superset_vote", {"status": "open", "voted": True})
        self._settle_vote(vote)

    def _settle_vote(self, vote: dict, closing: bool = False) -> None:
        yes, no, eligible = self._vote_counts(vote)
        outcome = logic.vote_outcome(yes, no, eligible, closing)
        if outcome == "passed":
            rnd = self._round(vote["round_id"])
            self.db.execute("UPDATE rounds SET is_superset = 1, superset_theme_id = theme_id WHERE id = ?",
                            (rnd["id"],))
            self.db.execute("UPDATE queue_items SET is_superset = 1 WHERE id = (SELECT now_playing_item_id FROM events "
                            "WHERE id = ?)", (vote["event_id"],))
            self._close_vote(vote, "passed", f"★ The vote passed ({yes}–{no})! This round is a SUPERSET: "
                                             f"everyone sings “{rnd['theme_name']}”.", "gold")
            self.emit(vote["event_id"], "superset", {"active": True, "round": rnd["number"], "voted": True,
                                                     "theme": self._theme_out(self._theme(rnd["theme_id"]))
                                                     or {"id": None, "name": rnd["theme_name"], "description": ""}})
        elif outcome == "failed":
            self._close_vote(vote, "failed", f"The Superset vote didn't pass ({yes}–{no}). Sing what you like!")

    def _close_vote(self, vote: dict, status: str, text: str, level: str = "info") -> None:
        self.db.execute("UPDATE superset_votes SET status = ?, closed_at = ? WHERE id = ?",
                        (status, self.clock(), vote["id"]))
        self.notice(vote["event_id"], text, level)
        self.emit(vote["event_id"], "superset_vote", {"status": status})

    def tick(self) -> None:
        """Called every second by the server: closes Superset votes whose time is up."""
        for vote in self.db.all("SELECT * FROM superset_votes WHERE status = 'open' AND ends_at <= ?",
                                (self.clock(),)):
            self._settle_vote(vote, closing=True)

    # ------------------------------------------------------------------ queue

    def _queue(self, event_id: int) -> list[dict]:
        ev = self.get_event(event_id)
        return logic.play_order(self._items(event_id, ("queued",)), self._positions(event_id), ev["current_round"])

    def queue_song(self, guest_id: int, video: dict, duet_guest_id: int | None = None) -> dict:
        """Singers add as many songs as they like; each lands in the next round they don't have a song in."""
        guest = self._guest(guest_id)
        if guest["status"] != "active":
            raise EngineError("You're not in this event any more.", 403)
        ev = self.get_event(guest["event_id"])
        if ev["status"] == "ended":
            raise EngineError("This event has ended", 410)
        if ev["config"]["prevent_duplicates"] and logic.is_duplicate(self._items(ev["id"]), video["video_id"]):
            raise EngineError("That song has already been sung or queued tonight. Pick another!", 409)
        max_d = int(ev["config"]["max_duration_s"])
        if max_d and video.get("duration_s") and video["duration_s"] > max_d:
            raise EngineError(f"That video is longer than the {max_d // 60}-minute limit")

        mine = self.db.all("SELECT * FROM queue_items WHERE guest_id = ? AND status IN "
                           "('queued', 'playing', 'played', 'skipped')", (guest_id,))
        cap = int(ev["config"]["max_songs_per_singer"])
        waiting = sum(1 for m in mine if m["status"] == "queued")
        if cap and waiting >= cap:
            raise EngineError(f"You already have {waiting} song{'s' if waiting != 1 else ''} waiting (the limit is "
                              f"{cap}). Add another once one has played.", 409)
        if duet_guest_id is not None:
            partner = self.db.one("SELECT * FROM guests WHERE id = ?", (duet_guest_id,))
            if not partner or partner["event_id"] != ev["id"] or partner["status"] != "active":
                raise EngineError("Your duet partner isn't at this event any more.", 404)
            if duet_guest_id == guest_id:
                raise EngineError("Pick someone else to sing the duet with.")
        last_round = max((m["round_no"] or ev["current_round"] for m in mine), default=None)
        round_no = logic.assign_round(ev["current_round"], self._anchor_pos(ev), guest["rotation_pos"], last_round)
        priority = None
        if guest["repick_credit"]:  # their last song couldn't play: this one goes straight to the front
            queued = self._items(ev["id"], ("queued",))
            priority = max((q["priority"] for q in queued if q["priority"] is not None), default=0) + 1
            self.db.execute("UPDATE guests SET repick_credit = 0 WHERE id = ?", (guest_id,))
        item_id = self.db.insert(
            "INSERT INTO queue_items(event_id, guest_id, duet_guest_id, round_no, priority, video_id, title, channel, "
            "duration_s, thumbnail, position, added_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?)",
            (ev["id"], guest_id, duet_guest_id, round_no, priority, video["video_id"], video["title"][:200],
             (video.get("channel") or "")[:120], video.get("duration_s"), video.get("thumbnail") or "", self.clock()))
        self.emit(ev["id"], "song_queued", {"item_id": item_id, "guest_id": guest_id,
                                            "name": guest["display_name"], "title": video["title"]})
        if duet_guest_id is not None:
            self.emit(ev["id"], "duet_invite", {"item_id": item_id, "name": guest["display_name"],
                                                "title": video["title"]}, guest_id=duet_guest_id)
        if ev["status"] == "active" and ev["config"]["autoplay"] and not ev["now_playing_item_id"] \
                and not ev["paused"]:
            self.play_next(ev["id"])
        return self.db.one("SELECT * FROM queue_items WHERE id = ?", (item_id,))

    def _my_item(self, event_id: int, item_id: int, guest_id: int | None) -> dict:
        item = self.db.one("SELECT * FROM queue_items WHERE id = ? AND event_id = ?", (item_id, event_id))
        if not item or item["status"] not in ACTIVE_QUEUE_STATUSES:
            raise EngineError("Song not found in the queue", 404)
        if guest_id is not None and item["guest_id"] != guest_id:
            raise EngineError("You can only change your own songs", 403)
        return item

    def remove_item(self, event_id: int, item_id: int, by_guest_id: int | None = None) -> None:
        item = self._my_item(event_id, item_id, by_guest_id)
        if item["status"] == "playing":
            self.skip_song(event_id)
            return
        self.db.execute("UPDATE queue_items SET status = 'removed' WHERE id = ?", (item_id,))
        # Close the gap so the singer's later songs each move up a round.
        self.db.execute("UPDATE queue_items SET round_no = round_no - 1 WHERE guest_id = ? AND status = 'queued' "
                        "AND priority IS NULL AND round_no > ?", (item["guest_id"], item["round_no"] or 0))
        self.emit(event_id, "song_removed", {"item_id": item_id, "title": item["title"]})

    def play_item_next(self, event_id: int, item_id: int) -> None:
        """Host: put a song at the very front of the queue."""
        item = self._my_item(event_id, item_id, None)
        if item["status"] != "queued":
            return
        queued = self._items(event_id, ("queued",))
        front = min((q["priority"] for q in queued if q["priority"] is not None), default=1.0) - 1
        self.db.execute("UPDATE queue_items SET priority = ? WHERE id = ?", (front, item_id))
        self.emit(event_id, "queue_reordered")

    def move_my_song_up(self, guest_id: int, item_id: int) -> None:
        """A singer swaps one of their songs with their own previous one."""
        guest = self._guest(guest_id)
        order = [i for i in self._queue(guest["event_id"]) if i["guest_id"] == guest_id]
        idx = next((i for i, x in enumerate(order) if x["id"] == item_id), None)
        if idx is None:
            raise EngineError("Song not found in the queue", 404)
        if idx == 0:
            return
        a, b = order[idx - 1], order[idx]
        for src, dst in ((a, b), (b, a)):
            self.db.execute("UPDATE queue_items SET round_no = ?, priority = ?, order_bias = ? WHERE id = ?",
                            (src["round_no"], src["priority"], src["order_bias"], dst["id"]))
        self.emit(guest["event_id"], "queue_reordered")

    def let_next_go_first(self, guest_id: int, item_id: int) -> None:
        """'Not ready? Let the next singer go first': exactly one song moves ahead of this one."""
        guest = self._guest(guest_id)
        event_id = guest["event_id"]
        queue = self._queue(event_id)
        if not queue or queue[0]["id"] != item_id or queue[0]["guest_id"] != guest_id:
            raise EngineError("You can only do this when your song is up next.", 409)
        if len(queue) < 2:
            raise EngineError("There's nobody else in the queue to go ahead of you.", 409)
        mine, nxt = queue[0], queue[1]
        positions = self._positions(event_id)
        if nxt["priority"] is not None:
            self.db.execute("UPDATE queue_items SET priority = ? WHERE id = ?", (nxt["priority"] + 0.5, mine["id"]))
        else:
            new_round = nxt["round_no"] or self.get_event(event_id)["current_round"]
            bias = positions[nxt["guest_id"]] + float(nxt["order_bias"] or 0) - positions[guest_id] + 0.5
            if new_round > (mine["round_no"] or 0):  # keep this singer's own songs in their order
                self.db.execute("UPDATE queue_items SET round_no = round_no + 1 WHERE guest_id = ? AND id != ? "
                                "AND status = 'queued' AND priority IS NULL AND round_no >= ?",
                                (guest_id, mine["id"], new_round))
            self.db.execute("UPDATE queue_items SET priority = NULL, round_no = ?, order_bias = ? WHERE id = ?",
                            (new_round, bias, mine["id"]))
        nxt_name = self._guest(nxt["guest_id"])["display_name"]
        self.notice(event_id, f"{guest['display_name']} let {nxt_name} go first.")
        self.emit(event_id, "queue_reordered")

    def leave_duet(self, guest_id: int, item_id: int) -> None:
        """The second singer on a duet drops out; the song stays with the singer who picked it."""
        guest = self._guest(guest_id)
        item = self._my_item(guest["event_id"], item_id, None)
        if item["duet_guest_id"] != guest_id or item["status"] != "queued":
            raise EngineError("You're not on that duet.", 409)
        self.db.execute("UPDATE queue_items SET duet_guest_id = NULL WHERE id = ?", (item_id,))
        self.notice(guest["event_id"], f"{guest['display_name']} stepped out of a duet.", guest_id=item["guest_id"])
        self.emit(guest["event_id"], "queue_reordered")

    def flag_item(self, event_id: int, item_id: int, flagged_by: str) -> int:
        item = self._my_item(event_id, item_id, None)
        if not self._in_superset(self.get_event(event_id), item):
            raise EngineError("Songs can only be flagged during a Superset round")
        if flagged_by == f"guest:{item['guest_id']}":
            raise EngineError("You can't flag your own song")
        self.db.execute("INSERT OR IGNORE INTO flags(queue_item_id, flagged_by, created_at) VALUES (?, ?, ?)",
                        (item_id, flagged_by, self.clock()))
        count = self.db.one("SELECT COUNT(*) AS n FROM flags WHERE queue_item_id = ?", (item_id,))["n"]
        self.emit(event_id, "song_flagged", {"item_id": item_id, "count": count, "title": item["title"]})
        return count

    def _in_superset(self, ev: dict, item: dict) -> bool:
        """A song is in the Superset if it plays (or is playing) in the current Superset round."""
        rnd = self._round(ev["current_round_id"])
        if not rnd or not rnd["is_superset"]:
            return False
        return item["status"] == "playing" or (item["round_no"] or ev["current_round"]) == ev["current_round"]

    # ------------------------------------------------------------------ playback

    def play_next(self, event_id: int) -> dict | None:
        ev = self.get_event(event_id)
        if ev["now_playing_item_id"]:
            self.db.execute("UPDATE queue_items SET status = 'played', played_at = ? WHERE id = ? AND status = 'playing'",
                            (self.clock(), ev["now_playing_item_id"]))
        nxt = self._queue(event_id)
        if not nxt or ev["status"] != "active" or ev["paused"]:
            self._set(event_id, now_playing_item_id=None, ready_until=None)
            self.emit(event_id, "now_playing", {"item": None})
            return None
        item = nxt[0]
        if item["priority"] is None and (item["round_no"] or 0) > ev["current_round"]:
            self._start_round(event_id, item["round_no"])
            ev = self.get_event(event_id)
        rnd = self._round(ev["current_round_id"])
        self.db.execute("UPDATE queue_items SET status = 'playing', played_at = ?, round_id = ?, theme_name = ?, "
                        "is_superset = ?, round_no = COALESCE(round_no, ?) WHERE id = ?",
                        (self.clock(), rnd["id"] if rnd else None, rnd["theme_name"] if rnd else None,
                         int(bool(rnd and rnd["is_superset"])), ev["current_round"], item["id"]))
        ready = int(ev["config"]["ready_seconds"])
        self._set(event_id, now_playing_item_id=item["id"], ready_until=self.clock() + ready if ready else None)
        guest = self._guest(item["guest_id"])
        self.emit(event_id, "now_playing", {"item_id": item["id"], "video_id": item["video_id"],
                                            "title": item["title"], "guest_id": guest["id"],
                                            "name": guest["display_name"], "ready_seconds": ready})
        if guest["debut_pending"]:
            self.db.execute("UPDATE guests SET debut_pending = 0 WHERE id = ?", (guest["id"],))
            self.emit(event_id, "new_singer", {"guest_id": guest["id"], "name": guest["display_name"]})
        for gid in filter(None, (guest["id"], item["duet_guest_id"])):
            self.emit(event_id, "you_are_singing", {"title": item["title"]}, guest_id=gid)
        if len(nxt) > 1:
            for gid in filter(None, (nxt[1]["guest_id"], nxt[1]["duet_guest_id"])):
                self.emit(event_id, "you_are_next", {"title": nxt[1]["title"]}, guest_id=gid)
        return item

    def pause_queue(self, event_id: int) -> None:
        """Host: "Smoke break!" Stop the song (it goes back to the front) and hold the queue."""
        ev = self.get_event(event_id)
        if ev["status"] != "active" or ev["paused"]:
            return
        self.stop_playback(event_id)
        self._set(event_id, paused=1)
        self.emit(event_id, "queue_paused")
        self.notice(event_id, "🚬 Smoke break! The queue is on hold. Keep adding songs.", kind="paused")

    def resume_queue(self, event_id: int) -> None:
        ev = self.get_event(event_id)
        if not ev["paused"]:
            return
        self._set(event_id, paused=0)
        self.emit(event_id, "queue_resumed")
        self.notice(event_id, "Break's over! Back to the music. 🎤", "success")
        if ev["status"] == "active" and not ev["now_playing_item_id"]:
            self.play_next(event_id)

    def start_now(self, event_id: int) -> None:
        """Host: cut the "Get ready" countdown short."""
        ev = self.get_event(event_id)
        if ev["now_playing_item_id"] and ev["ready_until"]:
            self._set(event_id, ready_until=None)
            self.emit(event_id, "ready_skipped")

    def video_command(self, event_id: int, command: str) -> None:
        """Host remote: pause/play or change the volume of the TV's player."""
        self.get_event(event_id)
        if command not in VIDEO_COMMANDS:
            raise EngineError("Unknown video command")
        self.emit(event_id, "video_command", {"command": command})

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
            # Put the current song back at the front of the queue.
            queued = self._items(event_id, ("queued",))
            front = min((q["priority"] for q in queued if q["priority"] is not None), default=1.0) - 1
            self.db.execute("UPDATE queue_items SET status = 'queued', priority = ?, played_at = NULL WHERE id = ?",
                            (front, ev["now_playing_item_id"]))
            self._set(event_id, now_playing_item_id=None, ready_until=None)
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
        active = guest["status"] == "active"
        follow_up = f". {guest['display_name']}'s next pick plays straight away" if active else ""
        self.notice(event_id, f"“{item['title']}” {reason}. Skipping it{follow_up}.", "warning")
        if active:
            self.db.execute("UPDATE guests SET repick_credit = 1 WHERE id = ?", (guest["id"],))
            self.emit(event_id, "song_error", {"item_id": item_id, "code": code, "title": item["title"]},
                      guest_id=guest["id"])
        self.play_next(event_id)

    # ------------------------------------------------------------------ views

    def snapshot(self, event_id: int) -> dict:
        ev = self.get_event(event_id)
        now = self.clock()
        guests_all = self._guests(event_id, active_only=False)
        names = {g["id"]: g["display_name"] for g in guests_all}
        active = [g for g in guests_all if g["status"] == "active"]
        rnd = self._round(ev["current_round_id"])
        flag_counts = {r["queue_item_id"]: r["n"] for r in self.db.all(
            "SELECT f.queue_item_id, COUNT(*) AS n FROM flags f JOIN queue_items q ON q.id = f.queue_item_id "
            "WHERE q.event_id = ? GROUP BY f.queue_item_id", (event_id,))}

        def item_out(i: dict) -> dict:
            return {"id": i["id"], "video_id": i["video_id"], "title": i["title"], "channel": i["channel"],
                    "duration_s": i["duration_s"], "thumbnail": i["thumbnail"], "guest_id": i["guest_id"],
                    "guest_name": names.get(i["guest_id"], "?"), "theme": i["theme_name"],
                    "round": i["round_no"], "priority": i["priority"] is not None,
                    "is_superset": self._in_superset(ev, i) if i["status"] in ACTIVE_QUEUE_STATUSES
                    else bool(i["is_superset"]),
                    "flags": flag_counts.get(i["id"], 0), "status": i["status"],
                    "duet_guest_id": i["duet_guest_id"],
                    "duet_name": names.get(i["duet_guest_id"]) if i["duet_guest_id"] else None,
                    "started_at": i["played_at"] if i["status"] == "playing" else None}

        queue = [item_out(i) for i in self._queue(event_id)]
        playing = self.db.one("SELECT * FROM queue_items WHERE id = ?", (ev["now_playing_item_id"],)) \
            if ev["now_playing_item_id"] else None
        recent = [item_out(i) for i in self.db.all(
            "SELECT * FROM queue_items WHERE event_id = ? AND status = 'played' ORDER BY played_at DESC LIMIT 10",
            (event_id,))]
        history = [{"number": r["number"], "theme": r["theme_name"], "is_superset": bool(r["is_superset"])}
                   for r in self.db.all("SELECT * FROM rounds WHERE event_id = ? ORDER BY id DESC LIMIT 12",
                                        (event_id,))]
        counts: dict[int, int] = {}
        for q in queue:
            counts[q["guest_id"]] = counts.get(q["guest_id"], 0) + 1
        theme = self._theme(rnd["theme_id"]) if rnd else None
        return {
            "server_time": now,
            "event": {"id": ev["id"], "name": ev["name"], "join_code": ev["join_code"], "status": ev["status"],
                      "config": ev["config"], "superset_pending": ev["superset_pending"],
                      "paused": bool(ev["paused"])},
            "round": {"number": ev["current_round"], "is_superset": bool(rnd and rnd["is_superset"]),
                      "theme": self._theme_out(theme) or ({"id": None, "name": rnd["theme_name"], "description": ""}
                                                          if rnd and rnd["theme_name"] else None),
                      "spun_at": rnd["spun_at"] if rnd else None,
                      "spin_seconds": int(ev["config"]["spin_seconds"]) + (2 if rnd and rnd["is_superset"] else 0)},
            "guests": [{"id": g["id"], "name": g["display_name"], "rotation_pos": g["rotation_pos"],
                        "new_singer": bool(g["debut_pending"]), "queued": counts.get(g["id"], 0)}
                       for g in active],
            "queue": queue,
            "now_playing": {**item_out(playing), "starts_at": ev["ready_until"] or playing["played_at"]}
            if playing else None,
            "recent": recent,
            "rounds": history,
            "appearance": self.appearance(),
            "reactions": list(REACTIONS),
            "superset_vote": self._vote_out(event_id, names),
            "vote_callers": [r["called_by"] for r in self.db.all(
                "SELECT called_by FROM superset_votes WHERE round_id = ?", (rnd["id"],))] if rnd else [],
            "recap": self.recap(event_id) if ev["status"] == "ended" else None,
        }

    def _vote_out(self, event_id: int, names: dict[int, str]) -> dict | None:
        vote = self._open_vote(event_id)
        if not vote:
            return None
        yes, no, eligible = self._vote_counts(vote)
        voters = [b["guest_id"] for b in self.db.all("SELECT guest_id FROM superset_ballots WHERE vote_id = ?",
                                                      (vote["id"],))]
        return {"id": vote["id"], "called_by": vote["called_by"], "called_by_name": names.get(vote["called_by"], "?"),
                "ends_at": vote["ends_at"], "yes": yes, "no": no, "eligible": eligible, "voters": voters}

    def recap(self, event_id: int) -> dict:
        """End-of-night numbers for the TV and phones."""
        ev = self.get_event(event_id)
        sung = self.db.all(
            "SELECT q.*, g.display_name, d.display_name AS duet_name FROM queue_items q "
            "JOIN guests g ON g.id = q.guest_id LEFT JOIN guests d ON d.id = q.duet_guest_id "
            "WHERE q.event_id = ? AND q.status = 'played' ORDER BY q.played_at, q.id", (event_id,))
        flagged = {r["queue_item_id"] for r in self.db.all(
            "SELECT DISTINCT f.queue_item_id FROM flags f JOIN queue_items q ON q.id = f.queue_item_id "
            "WHERE q.event_id = ?", (event_id,))}
        per_singer: dict[str, int] = {}
        for s in sung:
            for name in filter(None, (s["display_name"], s["duet_name"])):
                per_singer[name] = per_singer.get(name, 0) + 1
        best = max(per_singer.values(), default=0)
        rounds = self.db.all("SELECT * FROM rounds WHERE event_id = ? ORDER BY number", (event_id,))
        theme_counts: dict[str, int] = {}
        for s in sung:
            if s["theme_name"]:
                theme_counts[s["theme_name"]] = theme_counts.get(s["theme_name"], 0) + 1
        stars = sorted({s["display_name"] for s in sung if s["is_superset"] and s["id"] not in flagged})
        song = (lambda s: {"title": s["title"], "singer": s["display_name"] + (f" & {s['duet_name']}"
                                                                              if s["duet_name"] else "")})
        longest = max(sung, key=lambda s: s["duration_s"] or 0, default=None)
        return {
            "songs": len(sung),
            "singers": len(per_singer),
            "minutes": round(sum(s["duration_s"] or UNKNOWN_DURATION_S for s in sung) / 60),
            "duets": sum(1 for s in sung if s["duet_name"]),
            "rounds": len(rounds),
            "superset_rounds": sum(1 for r in rounds if r["is_superset"]),
            "top_singers": sorted(n for n, c in per_singer.items() if c == best) if best else [],
            "top_count": best,
            "per_singer": per_singer,
            "top_themes": [t for t, _ in sorted(theme_counts.items(), key=lambda kv: (-kv[1], kv[0]))[:3]],
            "superset_stars": stars,
            "late_joiners": self.db.one(
                "SELECT COUNT(*) AS n FROM guests WHERE event_id = ? AND joined_at > ?",
                (event_id, ev["started_at"] or float("inf")))["n"],
            "first_song": song(sung[0]) if sung else None,
            "last_song": song(sung[-1]) if sung else None,
            "longest_song": song(longest) if longest and longest["duration_s"] else None,
        }

    def guest_codes(self, event_id: int) -> list[dict]:
        """Host only: every singer's rejoin code (never part of the shared snapshot)."""
        return [{"id": g["id"], "name": g["display_name"], "status": g["status"],
                 "rejoin_code": self.rejoin_code(g["id"])} for g in self._guests(event_id, active_only=False)
                if g["status"] != "removed"]

    def appearance(self) -> dict:
        scheme = self.db.get_setting("colour_scheme", DEFAULT_SCHEME)
        return {"scheme": scheme if scheme in COLOUR_SCHEMES else DEFAULT_SCHEME}

    def set_scheme(self, scheme: str) -> dict:
        if scheme not in COLOUR_SCHEMES:
            raise EngineError(f"Unknown colour scheme. Choose one of: {', '.join(COLOUR_SCHEMES)}")
        self.db.set_setting("colour_scheme", scheme)
        return self.appearance()

    def history_csv(self, event_id: int) -> str:
        ev = self.get_event(event_id)
        rows = self.db.all(
            "SELECT q.*, g.display_name, d.display_name AS duet_name, COALESCE(r.number, q.round_no) AS round_number "
            "FROM queue_items q JOIN guests g ON g.id = q.guest_id LEFT JOIN guests d ON d.id = q.duet_guest_id "
            "LEFT JOIN rounds r ON r.id = q.round_id "
            "WHERE q.event_id = ? AND q.status IN ('played', 'playing', 'skipped', 'error') "
            "ORDER BY COALESCE(q.played_at, q.added_at)", (event_id,))
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(["event", "played_at_utc", "round", "superset", "theme", "singer", "title", "channel",
                    "duration_s", "status", "youtube_url"])
        for r in rows:
            ts = datetime.fromtimestamp(r["played_at"] or r["added_at"], tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
            w.writerow([ev["name"], ts, r["round_number"] or "", "yes" if r["is_superset"] else "no",
                        r["theme_name"] or "", r["display_name"] + (f" & {r['duet_name']}" if r["duet_name"] else ""),
                        r["title"], r["channel"], r["duration_s"] or "",
                        r["status"], f"https://www.youtube.com/watch?v={r['video_id']}"])
        return buf.getvalue()
