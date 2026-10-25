"""Playback: what plays next, get-ready countdowns, smoke breaks and player reports."""
from __future__ import annotations

from .constants import VIDEO_COMMANDS, EngineError


class PlaybackMixin:
    # ------------------------------------------------------------------ playback

    def play_next(self, event_id: int) -> dict | None:
        """Finish the current song and start the next: the Superset set's next turn if one is running
        (waiting for that singer to pick if need be), otherwise the regular queue."""
        ev = self.get_event(event_id)
        if ev["now_playing_item_id"]:
            self.db.execute("UPDATE queue_items SET status = 'played', played_at = ? WHERE id = ? AND status = 'playing'",
                            (self.clock(), ev["now_playing_item_id"]))
            self._set(event_id, now_playing_item_id=None, ready_until=None)
            ev = self.get_event(event_id)
        if ev["status"] != "active" or ev["paused"]:
            return self._idle(event_id)
        sset = self._active_set(event_id)
        if not sset:
            nxt = self._queue(event_id)
            if nxt and nxt[0]["priority"] is None and (nxt[0]["round_no"] or 0) > ev["current_round"] \
                    and self._roll_random_set(ev, nxt[0]["round_no"]):
                return self.db.one("SELECT * FROM queue_items WHERE id = ?",
                                   (self.get_event(event_id)["now_playing_item_id"],))
        if sset:
            slot = self._open_slot(sset["id"])
            if slot is None:
                self._finish_set(sset, "done", "★ Superset complete! Back to the queue. 🎤")
            elif slot["status"] == "pending":
                guest = self._guest(slot["guest_id"])
                self.emit(event_id, "superset_waiting", {"guest_id": guest["id"], "name": guest["display_name"]})
                self.emit(event_id, "superset_your_turn", {"theme": sset["theme_name"]}, guest_id=guest["id"])
                return self._idle(event_id)
            else:
                self.db.execute("UPDATE superset_slots SET status = 'sung' WHERE set_id = ? AND guest_id = ?",
                                (sset["id"], slot["guest_id"]))
                item = self.db.one("SELECT * FROM queue_items WHERE id = ?", (slot["item_id"],))
                return self._start_item(event_id, item)
        nxt = self._queue(event_id)
        if not nxt:
            return self._idle(event_id)
        item = nxt[0]
        if item["priority"] is None and (item["round_no"] or 0) > ev["current_round"]:
            self._start_round(event_id, item["round_no"])
        return self._start_item(event_id, item)

    def _idle(self, event_id: int) -> None:
        self._set(event_id, now_playing_item_id=None, ready_until=None)
        self.emit(event_id, "now_playing", {"item": None})
        return None

    def _upcoming(self, event_id: int) -> dict | None:
        """The song after the one playing: the set's next pick, or the head of the regular queue."""
        sset = self._active_set(event_id)
        if sset:
            slot = self._open_slot(sset["id"])
            if slot:
                return self.db.one("SELECT * FROM queue_items WHERE id = ?", (slot["item_id"],)) \
                    if slot["item_id"] else {"guest_id": slot["guest_id"], "duet_guest_id": None, "title": None}
        nxt = self._queue(event_id)
        return nxt[0] if nxt else None

    def _start_item(self, event_id: int, item: dict) -> dict:
        ev = self.get_event(event_id)
        rnd = self._round(ev["current_round_id"])
        if self._in_superset(ev, item):  # Superset songs keep their set's theme and don't use up a round
            self.db.execute("UPDATE queue_items SET status = 'playing', played_at = ?, round_id = ? WHERE id = ?",
                            (self.clock(), rnd["id"] if rnd else None, item["id"]))
        else:
            self.db.execute("UPDATE queue_items SET status = 'playing', played_at = ?, round_id = ?, theme_name = ?, "
                            "is_superset = 0, round_no = COALESCE(round_no, ?) WHERE id = ?",
                            (self.clock(), rnd["id"] if rnd else None, rnd["theme_name"] if rnd else None,
                             ev["current_round"], item["id"]))
        ready = int(ev["config"]["ready_seconds"])
        self._set(event_id, now_playing_item_id=item["id"], ready_until=self.clock() + ready if ready else None)
        singers = self._who(item["guest_id"]) + (f" & {self._who(item['duet_guest_id'])}" if item["duet_guest_id"] else "")
        where = ("Superset turn" if self._in_superset(ev, item) else
                 f"played out of turn (round {item['round_no']})" if item["priority"] is not None else
                 f"round {item['round_no'] or ev['current_round']}")
        self.log(event_id, "playback", f"Now playing: {singers}, {self._song(item)} ({where})", automatic=True,
                 item_id=item["id"])
        guest = self._guest(item["guest_id"])
        self.emit(event_id, "now_playing", {"item_id": item["id"], "video_id": item["video_id"],
                                            "title": item["title"], "guest_id": guest["id"],
                                            "name": guest["display_name"], "ready_seconds": ready})
        if guest["debut_pending"]:
            self.db.execute("UPDATE guests SET debut_pending = 0 WHERE id = ?", (guest["id"],))
            self.emit(event_id, "new_singer", {"guest_id": guest["id"], "name": guest["display_name"]})
        for gid in filter(None, (guest["id"], item["duet_guest_id"])):
            self.emit(event_id, "you_are_singing", {"title": item["title"]}, guest_id=gid)
        upcoming = self._upcoming(event_id)
        if upcoming:
            for gid in filter(None, (upcoming["guest_id"], upcoming["duet_guest_id"])):
                self.emit(event_id, "you_are_next", {"title": upcoming["title"]}, guest_id=gid)
        queue = [] if self._active_set(event_id) else self._queue(event_id)
        if len(queue) > 1:  # a heads-up for whoever sings after the next song (push alerts use it)
            busy = {guest["id"], item["duet_guest_id"]} | ({upcoming["guest_id"], upcoming["duet_guest_id"]} if upcoming else set())
            for gid in filter(None, (queue[1]["guest_id"], queue[1]["duet_guest_id"])):
                if gid not in busy:  # already told they're singing or up next
                    self.emit(event_id, "two_to_go", {"title": queue[1]["title"]}, guest_id=gid)
        return item

    def pause_queue(self, event_id: int) -> None:
        """Host: "Smoke break!" Stop the song (it goes back to the front) and hold the queue."""
        ev = self.get_event(event_id)
        if ev["status"] != "active" or ev["paused"]:
            return
        self.stop_playback(event_id)
        self._set(event_id, paused=1)
        self.log(event_id, "event", "Smoke break: queue on hold")
        self.emit(event_id, "queue_paused")
        self.notice(event_id, "🚬 Smoke break! The queue is on hold. Keep adding songs.", kind="paused")

    def resume_queue(self, event_id: int) -> None:
        ev = self.get_event(event_id)
        if not ev["paused"]:
            return
        self._set(event_id, paused=0)
        self.log(event_id, "event", "Smoke break over: queue resumed")
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

    def cheer(self, guest_id: int) -> tuple[int, int] | None:
        """A reaction from a phone counts towards the song playing: (item id, cheers so far)."""
        guest = self._guest(guest_id)
        ev = self.get_event(guest["event_id"])
        item_id = ev["now_playing_item_id"]
        if not item_id:
            return None
        self.db.execute("UPDATE queue_items SET cheers = cheers + 1 WHERE id = ?", (item_id,))
        return item_id, self.db.one("SELECT cheers FROM queue_items WHERE id = ?", (item_id,))["cheers"]

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
        item = self.db.one("SELECT * FROM queue_items WHERE id = ?", (ev["now_playing_item_id"],))
        self.log(event_id, "playback", f"Skipped {self._song(item)} ({self._who(item['guest_id'])})",
                 item_id=item["id"])
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
            self.db.execute("UPDATE superset_slots SET status = 'picked' WHERE item_id = ? AND status = 'sung' AND "
                            "set_id IN (SELECT id FROM superset_sets WHERE status = 'active')",
                            (ev["now_playing_item_id"],))
            self._set(event_id, now_playing_item_id=None, ready_until=None)
            item = self.db.one("SELECT * FROM queue_items WHERE id = ?", (ev["now_playing_item_id"],))
            self.log(event_id, "playback", f"Stopped {self._song(item)} ({self._who(item['guest_id'])}); "
                     "it goes back to the front of the queue", item_id=item["id"])
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
        in_set = active and item["set_id"] and self.db.one(
            "SELECT 1 FROM superset_sets WHERE id = ? AND status = 'active'", (item["set_id"],))
        if in_set:  # their Superset turn comes round again: the set waits for a new pick
            self.db.execute("UPDATE superset_slots SET status = 'pending', item_id = NULL WHERE item_id = ?",
                            (item_id,))
            follow_up = f". {guest['display_name']}, pick another Superset song"
        else:
            follow_up = f". {guest['display_name']}'s next pick plays straight away" if active else ""
        self.notice(event_id, f"“{item['title']}” {reason}. Skipping it{follow_up}.", "warning")
        self.log(event_id, "playback", f"{self._song(item)} ({guest['display_name']}) couldn't play (YouTube error "
                 f"{code}), skipped" + (f"; {guest['display_name']} picks again" if active else ""),
                 item_id=item_id, code=code)
        if active and not in_set:
            self.db.execute("UPDATE guests SET repick_credit = 1 WHERE id = ?", (guest["id"],))
            self.emit(event_id, "song_error", {"item_id": item_id, "code": code, "title": item["title"]},
                      guest_id=guest["id"])
        self.play_next(event_id)
