"""The song queue: adding, removing and reordering songs, duets and flags."""
from __future__ import annotations

from .. import logic
from .constants import ACTIVE_QUEUE_STATUSES, EngineError


class QueueMixin:
    # ------------------------------------------------------------------ queue

    def _queue(self, event_id: int) -> list[dict]:
        """The regular queue in play order (Superset picks wait in their set, not here)."""
        ev = self.get_event(event_id)
        sset = self._active_set(event_id)
        in_set = sset["id"] if sset else None
        regular = [i for i in self._items(event_id, ("queued",)) if not i["set_id"] or i["set_id"] != in_set]
        return logic.play_order(regular, self._positions(event_id), ev["current_round"])

    def queue_song(self, guest_id: int, video: dict, duet_guest_id: int | None = None) -> dict:
        """Singers add as many songs as they like; each lands in the next round they don't have a song in.
        During a Superset, a singer's first pick is their Superset song."""
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

        sset, slot = self._my_slot(ev["id"], guest_id)
        for_set = bool(slot and slot["status"] == "pending")
        mine = self.db.all("SELECT * FROM queue_items WHERE guest_id = ? AND set_id IS NULL AND status IN "
                           "('queued', 'playing', 'played', 'skipped')", (guest_id,))
        cap = int(ev["config"]["max_songs_per_singer"])
        waiting = sum(1 for m in mine if m["status"] == "queued")
        if cap and waiting >= cap and not for_set:  # a Superset song is a bonus, outside the limit
            raise EngineError(f"You already have {waiting} song{'s' if waiting != 1 else ''} waiting (the limit is "
                              f"{cap}). Add another once one has played.", 409)
        if duet_guest_id is not None:
            partner = self.db.one("SELECT * FROM guests WHERE id = ?", (duet_guest_id,))
            if not partner or partner["event_id"] != ev["id"] or partner["status"] != "active":
                raise EngineError("Your duet partner isn't at this event any more.", 404)
            if duet_guest_id == guest_id:
                raise EngineError("Pick someone else to sing the duet with.")
        if for_set:
            return self._queue_set_song(ev, sset, guest, video, duet_guest_id)
        self._check_last_call(ev, video.get("duration_s"))
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
        self._announce_last_call(self.get_event(ev["id"]))
        return self.db.one("SELECT * FROM queue_items WHERE id = ?", (item_id,))

    def _queue_set_song(self, ev: dict, sset: dict, guest: dict, video: dict, duet_guest_id: int | None) -> dict:
        item_id = self.db.insert(
            "INSERT INTO queue_items(event_id, guest_id, duet_guest_id, set_id, is_superset, theme_name, video_id, "
            "title, channel, duration_s, thumbnail, position, added_at) VALUES (?, ?, ?, ?, 1, ?, ?, ?, ?, ?, ?, 0, ?)",
            (ev["id"], guest["id"], duet_guest_id, sset["id"], sset["theme_name"], video["video_id"],
             video["title"][:200], (video.get("channel") or "")[:120], video.get("duration_s"),
             video.get("thumbnail") or "", self.clock()))
        self.db.execute("UPDATE superset_slots SET status = 'picked', item_id = ? WHERE set_id = ? AND guest_id = ?",
                        (item_id, sset["id"], guest["id"]))
        self.emit(ev["id"], "song_queued", {"item_id": item_id, "guest_id": guest["id"], "superset": True,
                                            "name": guest["display_name"], "title": video["title"]})
        if duet_guest_id is not None:
            self.emit(ev["id"], "duet_invite", {"item_id": item_id, "name": guest["display_name"],
                                                "title": video["title"]}, guest_id=duet_guest_id)
        self._nudge(ev["id"])  # the set may have been waiting for this pick
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
        if item["set_id"] and self._in_superset(self.get_event(event_id), item):  # a Superset pick: pick again
            self.db.execute("UPDATE superset_slots SET status = 'pending', item_id = NULL WHERE item_id = ?",
                            (item_id,))
            self.emit(event_id, "song_removed", {"item_id": item_id, "title": item["title"]})
            return
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
            raise EngineError("Only Superset songs can be flagged, while the Superset is on")
        if flagged_by == f"guest:{item['guest_id']}":
            raise EngineError("You can't flag your own song")
        self.db.execute("INSERT OR IGNORE INTO flags(queue_item_id, flagged_by, created_at) VALUES (?, ?, ?)",
                        (item_id, flagged_by, self.clock()))
        count = self.db.one("SELECT COUNT(*) AS n FROM flags WHERE queue_item_id = ?", (item_id,))["n"]
        self.emit(event_id, "song_flagged", {"item_id": item_id, "count": count, "title": item["title"]})
        return count

    def _in_superset(self, ev: dict, item: dict) -> bool:
        """A song can be flagged while its Superset set is running."""
        sset = self._active_set(ev["id"])
        return bool(sset and item["set_id"] == sset["id"])
