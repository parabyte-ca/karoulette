"""Push alerts: which phones want which alerts, and what each engine message says on a locked screen."""
from __future__ import annotations

import json

from .. import logic

KINDS = ("turn", "superset", "duet", "playlist")
DEFAULT_PREFS = {k: True for k in KINDS}


class AlertsMixin:
    def save_push(self, guest_id: int, endpoint: str, p256dh: str, auth: str, prefs: dict | None = None) -> dict:
        """Store (or move to tonight's guest) a phone's push subscription."""
        clean = {**DEFAULT_PREFS, **{k: bool(v) for k, v in (prefs or {}).items() if k in KINDS}}
        self.db.execute(
            "INSERT INTO push_subscriptions(guest_id, endpoint, p256dh, auth, prefs, created_at) VALUES (?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(endpoint) DO UPDATE SET guest_id = excluded.guest_id, p256dh = excluded.p256dh, "
            "auth = excluded.auth, prefs = excluded.prefs",
            (guest_id, endpoint, p256dh, auth, json.dumps(clean), self.clock()))
        return clean

    def set_push_prefs(self, guest_id: int, endpoint: str, prefs: dict) -> dict:
        row = self.db.one("SELECT prefs FROM push_subscriptions WHERE endpoint = ? AND guest_id = ?", (endpoint, guest_id))
        if not row:
            return {}
        clean = {**json.loads(row["prefs"]), **{k: bool(v) for k, v in prefs.items() if k in KINDS}}
        self.db.execute("UPDATE push_subscriptions SET prefs = ? WHERE endpoint = ?", (json.dumps(clean), endpoint))
        return clean

    def delete_push(self, guest_id: int, endpoint: str) -> None:
        self.db.execute("DELETE FROM push_subscriptions WHERE endpoint = ? AND guest_id = ?", (endpoint, guest_id))

    def push_jobs(self, messages: list[dict]) -> list[tuple[dict, dict]]:
        """(subscription, payload) pairs for the messages just sent: each kind only to phones that want it."""
        jobs = []
        for m in messages:
            built = self._push_payload(m)
            if not built:
                continue
            kind, payload, guest_ids, exclude = built
            ev = m["event_id"]
            if guest_ids is None:  # everyone at the event
                subs = self.db.all("SELECT s.* FROM push_subscriptions s JOIN guests g ON g.id = s.guest_id "
                                   "WHERE g.event_id = ? AND g.status = 'active'", (ev,))
            else:
                marks = ",".join("?" * len(guest_ids))
                subs = self.db.all(f"SELECT * FROM push_subscriptions WHERE guest_id IN ({marks})", guest_ids)
            for s in subs:
                if s["guest_id"] != exclude and json.loads(s["prefs"] or "{}").get(kind, True):
                    jobs.append((s, payload))
        return jobs

    def _push_payload(self, m: dict) -> tuple[str, dict, list[int] | None, int | None] | None:
        msg, d, gid = m["message"], m["message"]["data"], m["guest_id"]
        kind = msg["type"]
        ev = self.db.one("SELECT name, join_code FROM events WHERE id = ?", (m["event_id"],))
        if not ev:
            return None
        here = f"/join/{ev['join_code']}"
        song = logic.song_name(d.get("title") or "") or "your song"

        def to_guest(k, title, body):
            return (k, {"title": title, "body": body, "url": here, "tag": f"karoulette-{k}"}, [gid], None) if gid else None

        if kind == "two_to_go":
            return to_guest("turn", "🎤 Two songs to go", f"{song} is coming up soon. Start heading for the mic.")
        if kind == "you_are_next":
            return to_guest("turn", "You're up next!", f"Head to the mic: {song} is next.")
        if kind == "you_are_singing":
            return to_guest("turn", "🎤 You're up!", f"Grab the mic: {song}")
        if kind == "superset_your_turn":
            return to_guest("superset", "★ Your Superset turn!", f"Pick a song that fits {d.get('theme', 'the theme')}.")
        if kind == "duet_invite":
            return to_guest("duet", "🎶 Duet!", f"{d.get('name', 'Someone')} added you to a duet: {song}")
        if kind == "song_error":
            return to_guest("duet", "Your song couldn't play", f"{song} couldn't play. Pick another and it plays straight away.")
        if kind == "superset_vote" and d.get("status") == "open" and d.get("name"):
            return ("superset", {"title": "★ Superset vote!", "body": f"{d['name']} called a Superset. Vote on your phone.",
                                 "url": here, "tag": "karoulette-vote"}, None, d.get("guest_id"))
        if kind == "event_ended":
            if not self.db.one("SELECT 1 FROM queue_items WHERE event_id = ? AND status = 'played'", (m["event_id"],)):
                return None
            return ("playlist", {"title": "That's a wrap! 🎶", "body": f"Tonight's songs from {ev['name']} as a playlist.",
                                 "url": f"/playlist/{ev['join_code']}", "tag": "karoulette-playlist"}, None, None)
        return None
