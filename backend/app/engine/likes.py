"""Crowd love: ❤️ likes on other people's songs (shown, never reordering anything) and song suggestions,
where one guest suggests a song for another, who adds it with one tap or dismisses it."""
from __future__ import annotations

from .. import logic
from .constants import EngineError

LIKEABLE = ("queued", "playing", "played")
MAX_PENDING_PER_PAIR = 3  # suggestions from one guest waiting on another


class LikesMixin:
    # ------------------------------------------------------------------ likes

    def toggle_like(self, guest_id: int, item_id: int) -> dict:
        guest = self._guest(guest_id)
        item = self.db.one("SELECT * FROM queue_items WHERE id = ?", (item_id,))
        if not item or item["event_id"] != guest["event_id"] or item["status"] not in LIKEABLE:
            raise EngineError("That song isn't in the queue any more.", 404)
        if guest_id in (item["guest_id"], item["duet_guest_id"]):
            raise EngineError("You can't like your own song. Everyone else can, though!")
        if self.db.one("SELECT 1 FROM likes WHERE item_id = ? AND guest_id = ?", (item_id, guest_id)):
            self.db.execute("DELETE FROM likes WHERE item_id = ? AND guest_id = ?", (item_id, guest_id))
            liked = False
        else:
            self.db.execute("INSERT INTO likes(item_id, guest_id, created_at) VALUES (?, ?, ?)",
                            (item_id, guest_id, self.clock()))
            liked = True
        n = self.db.one("SELECT COUNT(*) AS n FROM likes WHERE item_id = ?", (item_id,))["n"]
        return {"liked": liked, "likes": n}

    def _likers(self, event_id: int) -> dict[int, list[int]]:
        """Who liked each song at the event: {item_id: [guest_id, ...]}."""
        out: dict[int, list[int]] = {}
        for r in self.db.all("SELECT l.item_id, l.guest_id FROM likes l JOIN queue_items q ON q.id = l.item_id "
                             "WHERE q.event_id = ? ORDER BY l.created_at", (event_id,)):
            out.setdefault(r["item_id"], []).append(r["guest_id"])
        return out

    # ------------------------------------------------------------------ song suggestions

    def suggest_song(self, guest_id: int, to_guest_id: int, video: dict) -> dict:
        guest = self._guest(guest_id)
        ev = self.get_event(guest["event_id"])
        if ev["status"] == "ended":
            raise EngineError("This event has ended", 410)
        to = self.db.one("SELECT * FROM guests WHERE id = ?", (to_guest_id,))
        if not to or to["event_id"] != ev["id"] or to["status"] != "active":
            raise EngineError("That singer isn't at this event any more.", 404)
        if to_guest_id == guest_id:
            raise EngineError("Add it yourself! Suggestions are for someone else.")
        pending = self.db.all("SELECT video_id FROM song_requests WHERE from_guest_id = ? AND to_guest_id = ? "
                              "AND status = 'pending'", (guest_id, to_guest_id))
        if any(p["video_id"] == video["video_id"] for p in pending):
            raise EngineError(f"You've already suggested that one to {to['display_name']}.", 409)
        if len(pending) >= MAX_PENDING_PER_PAIR:
            raise EngineError(f"{to['display_name']} has {len(pending)} of your suggestions to look at already. "
                              "Give them a moment!", 409)
        rid = self.db.insert(
            "INSERT INTO song_requests(event_id, from_guest_id, to_guest_id, video_id, title, channel, thumbnail, "
            "duration_s, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (ev["id"], guest_id, to_guest_id, video["video_id"], video.get("title") or "", video.get("channel") or "",
             video.get("thumbnail") or "", video.get("duration_s"), self.clock()))
        song = logic.song_name(video.get("title") or "")
        self.emit(ev["id"], "song_request", {"id": rid, "name": guest["display_name"], "title": video.get("title") or ""},
                  guest_id=to_guest_id)
        self.log(ev["id"], "songs", f"{guest['display_name']} suggested “{song}” to {to['display_name']}",
                 guest_id=guest_id, to_guest_id=to_guest_id)
        return {"id": rid, "to": to["display_name"]}

    def song_requests_for(self, guest_id: int) -> list[dict]:
        return [{"id": r["id"], "from": r["from_name"], "video_id": r["video_id"], "title": r["title"],
                 "channel": r["channel"], "thumbnail": r["thumbnail"], "duration_s": r["duration_s"]}
                for r in self.db.all(
                    "SELECT r.*, g.display_name AS from_name FROM song_requests r JOIN guests g ON g.id = r.from_guest_id "
                    "WHERE r.to_guest_id = ? AND r.status = 'pending' ORDER BY r.created_at", (guest_id,))]

    def _request(self, guest_id: int, request_id: int) -> dict:
        r = self.db.one("SELECT * FROM song_requests WHERE id = ? AND to_guest_id = ?", (request_id, guest_id))
        if not r or r["status"] != "pending":
            raise EngineError("That suggestion has already been handled.", 404)
        return r

    def accept_request(self, guest_id: int, request_id: int) -> dict:
        """Add a suggested song to your own songs (the usual limits and duplicate check apply)."""
        r = self._request(guest_id, request_id)
        video = {k: r[k] for k in ("video_id", "title", "channel", "thumbnail", "duration_s")}
        item = self.queue_song(guest_id, video)
        self.db.execute("UPDATE song_requests SET status = 'added', decided_at = ? WHERE id = ?", (self.clock(), r["id"]))
        guest = self._guest(guest_id)
        self.notice(r["event_id"], f"🎁 {guest['display_name']} added your suggestion “{logic.song_name(r['title'])}”!",
                    "success", guest_id=r["from_guest_id"])
        return item

    def dismiss_request(self, guest_id: int, request_id: int) -> None:
        r = self._request(guest_id, request_id)
        self.db.execute("UPDATE song_requests SET status = 'dismissed', decided_at = ? WHERE id = ?",
                        (self.clock(), r["id"]))
