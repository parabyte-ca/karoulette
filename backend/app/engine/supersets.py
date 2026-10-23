"""Supersets: bonus sets in singer order, and the votes that call them."""
from __future__ import annotations

from .. import logic
from .constants import EngineError


class SupersetsMixin:
    # ------------------------------------------------------------------ Superset sets
    #
    # A Superset is a bonus set: every singer picks one extra song that fits its theme, and the set goes
    # once round the singer order (carrying on from the rotation), waiting for each singer to pick. Then
    # the regular queue carries on exactly where it left off. "Start now" makes the song playing the first
    # of the set (the theme is "Songs like <it>"); "after" spins a theme from the list.

    def _active_set(self, event_id: int) -> dict | None:
        return self.db.one("SELECT * FROM superset_sets WHERE event_id = ? AND status = 'active'", (event_id,))

    def _slots(self, set_id: int) -> list[dict]:
        return self.db.all("SELECT * FROM superset_slots WHERE set_id = ? ORDER BY position", (set_id,))

    def _open_slot(self, set_id: int) -> dict | None:
        """The next turn in the set: the first singer who hasn't sung or sat out yet."""
        return self.db.one("SELECT * FROM superset_slots WHERE set_id = ? AND status IN ('pending', 'picked') "
                           "ORDER BY position LIMIT 1", (set_id,))

    def _my_slot(self, event_id: int, guest_id: int) -> tuple[dict | None, dict | None]:
        sset = self._active_set(event_id)
        if not sset:
            return None, None
        return sset, self.db.one("SELECT * FROM superset_slots WHERE set_id = ? AND guest_id = ?",
                                 (sset["id"], guest_id))

    def declare_superset(self, event_id: int, mode: str, source: str, inspired_item_id: int | None = None,
                         round_no: int | None = None) -> dict:
        ev = self.get_event(event_id)
        if ev["status"] != "active":
            raise EngineError("A Superset can be declared once the event has started.", 409)
        if self._active_set(event_id):
            raise EngineError("A Superset is already under way!", 409)
        if source != "host":  # the host can always squeeze one in
            self._check_last_call(ev, None, "Superset")
        playing = self.db.one("SELECT * FROM queue_items WHERE id = ?", (ev["now_playing_item_id"],)) \
            if ev["now_playing_item_id"] else None
        inspired = self.db.one("SELECT * FROM queue_items WHERE id = ?", (inspired_item_id,)) \
            if inspired_item_id else None
        if mode == "now" and inspired is None:
            inspired = playing
        if mode == "now" and (not playing or not inspired or playing["id"] != inspired["id"] or playing["set_id"]):
            mode = "after"  # the song that was meant to kick it off has finished
        theme, spun_at = None, None
        if inspired:
            theme_name = f"Songs like “{logic.song_name(inspired['title'])}”"
        else:
            theme = self._pick_theme(event_id)
            theme_name = theme["name"] if theme else "Singer's choice"
            spun_at = self.clock() if theme else None
        now = self.clock()
        set_id = self.db.insert(
            "INSERT INTO superset_sets(event_id, round_no, source, mode, theme_id, theme_name, inspired_by, spun_at, "
            "started_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (event_id, round_no if round_no is not None else ev["current_round"], source, mode,
             theme["id"] if theme else None, theme_name, inspired["title"] if inspired else None, spun_at, now))
        anchor = self._guest(playing["guest_id"]) if playing else self._anchor(ev)
        order = logic.set_order(self._guests(event_id), anchor["rotation_pos"] if anchor else None,
                                include_anchor=mode == "now")
        for pos, g in enumerate(order):
            first_song = mode == "now" and g["id"] == playing["guest_id"]
            self.db.execute("INSERT INTO superset_slots(set_id, guest_id, position, status, item_id) "
                            "VALUES (?, ?, ?, ?, ?)",
                            (set_id, g["id"], pos, "sung" if first_song else "pending",
                             playing["id"] if first_song else None))
        if mode == "now":
            self.db.execute("UPDATE queue_items SET set_id = ?, is_superset = 1, theme_name = ? WHERE id = ?",
                            (set_id, theme_name, playing["id"]))
        how = ("This song kicks it off. " if mode == "now" else
               "It starts after this song. " if playing else "")
        what = f"songs like “{logic.song_name(inspired['title'])}”" if inspired else f"“{theme_name}”"
        self.notice(event_id, f"★ SUPERSET! Everyone sings {what}. {how}Pick a song that fits: "
                              "we'll go round in singer order.", "gold", kind="superset")
        theme_out = self._theme_out(theme) or {"id": None, "name": theme_name, "description": ""}
        self.emit(event_id, "superset", {"active": True, "theme": theme_out, "mode": mode, "source": source,
                                         "spun": bool(spun_at)})
        if spun_at:
            self._emit_spin(event_id, ev["current_round"], theme, superset=True)
        if not ev["now_playing_item_id"] and not ev["paused"]:
            self.play_next(event_id)
        return self._active_set(event_id) or {}

    def force_superset(self, event_id: int, mode: str = "after") -> None:
        """Host: declare a Superset now, kicked off by this song ("now") or after it."""
        self.declare_superset(event_id, mode, "host")

    def cancel_superset(self, event_id: int) -> None:
        """Host: cancel a vote under way, or end the Superset set (its unsung picks are dropped)."""
        vote = self._open_vote(event_id)
        sset = self._active_set(event_id)
        if vote:
            self._close_vote(vote, "cancelled", "The host cancelled the Superset vote.")
        elif sset:
            self.db.execute("UPDATE queue_items SET status = 'removed' WHERE set_id = ? AND status = 'queued'",
                            (sset["id"],))
            self._finish_set(sset, "cancelled", "The host ended the Superset. Back to the queue!")
            ev = self.get_event(event_id)
            if ev["status"] == "active" and not ev["now_playing_item_id"] and not ev["paused"]:
                self.play_next(event_id)
        else:
            raise EngineError("There's no Superset to cancel.", 409)

    def _finish_set(self, sset: dict, status: str, text: str) -> None:
        self.db.execute("UPDATE superset_sets SET status = ?, ended_at = ? WHERE id = ?",
                        (status, self.clock(), sset["id"]))
        self.notice(sset["event_id"], text, "success" if status == "done" else "info")
        self.emit(sset["event_id"], "superset", {"active": False, "ended": status})

    def pass_superset(self, guest_id: int) -> None:
        """A singer sits this Superset out (their pick, if any, is dropped)."""
        guest = self._guest(guest_id)
        sset, slot = self._my_slot(guest["event_id"], guest_id)
        if not slot or slot["status"] not in ("pending", "picked"):
            raise EngineError("You're not waiting on a Superset song.", 409)
        if slot["item_id"]:
            self.db.execute("UPDATE queue_items SET status = 'removed' WHERE id = ? AND status = 'queued'",
                            (slot["item_id"],))
        self.db.execute("UPDATE superset_slots SET status = 'passed', item_id = NULL WHERE set_id = ? AND guest_id = ?",
                        (sset["id"], guest_id))
        self.notice(guest["event_id"], f"{guest['display_name']} sits this Superset out.")
        self._nudge(guest["event_id"])

    def skip_superset_turn(self, event_id: int) -> None:
        """Host: the set is waiting on someone who hasn't picked; move on without them."""
        sset = self._active_set(event_id)
        slot = self._open_slot(sset["id"]) if sset else None
        if not slot or slot["status"] != "pending":
            raise EngineError("The Superset isn't waiting on anyone.", 409)
        self.db.execute("UPDATE superset_slots SET status = 'skipped' WHERE set_id = ? AND guest_id = ?",
                        (sset["id"], slot["guest_id"]))
        self.notice(event_id, f"The host skipped {self._guest(slot['guest_id'])['display_name']}'s Superset turn.")
        self._nudge(event_id)

    def _nudge(self, event_id: int) -> None:
        """Start the next song if the TV is sitting idle (e.g. the set was waiting on a pick)."""
        ev = self.get_event(event_id)
        if ev["status"] == "active" and not ev["now_playing_item_id"] and not ev["paused"]:
            self.play_next(event_id)

    def _roll_random_set(self, ev: dict, next_round: int) -> bool:
        """Random Supersets open a new round, once per round, at the host's chosen chance (default 0 %)."""
        if self.db.one("SELECT 1 FROM superset_sets WHERE event_id = ? AND source = 'random' AND round_no = ?",
                       (ev["id"], next_round)):
            return False
        if not logic.roll_superset(float(ev["config"]["superset_chance"]), self.rng):
            return False
        info = self.last_call_info(ev)
        if info and not info["open"]:  # no surprise Supersets after last call
            return False
        self.declare_superset(ev["id"], "after", "random", round_no=next_round)
        return True

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

    def call_superset_vote(self, guest_id: int, mode: str = "after") -> dict:
        """Any singer can call a Superset; the others vote and the majority wins. ``mode`` "now" makes the
        song playing the first of the set (if the vote passes while it's still on)."""
        if mode not in ("now", "after"):
            raise EngineError("Choose to start now or after this song.")
        guest = self._guest(guest_id)
        ev = self.get_event(guest["event_id"])
        rnd = self._round(ev["current_round_id"])
        if ev["status"] != "active" or not rnd:
            raise EngineError("A Superset can be called once the event has started.", 409)
        if self._active_set(ev["id"]):
            raise EngineError("A Superset is already under way!", 409)
        if self._open_vote(ev["id"]):
            raise EngineError("A Superset vote is already under way. Cast your vote!", 409)
        if mode == "now" and not ev["now_playing_item_id"]:
            raise EngineError("Nothing's playing to kick it off. Start it after this song instead.", 409)
        self._check_last_call(ev, None, "Superset")
        if self.db.one("SELECT 1 FROM superset_votes WHERE round_id = ? AND called_by = ?", (rnd["id"], guest_id)):
            raise EngineError("You've already called a Superset this round.", 409)
        if not any(g["id"] != guest_id for g in self._guests(ev["id"])):
            raise EngineError("You need at least one other singer to vote on it.", 409)
        now = self.clock()
        playing = ev["now_playing_item_id"] if mode == "now" else None
        vote_id = self.db.insert(
            "INSERT INTO superset_votes(event_id, round_id, called_by, mode, item_id, started_at, ends_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (ev["id"], rnd["id"], guest_id, mode, playing, now, now + int(ev["config"]["superset_vote_seconds"])))
        what = (f"kicked off by “{logic.song_name(self.db.one('SELECT title FROM queue_items WHERE id = ?', (playing,))['title'])}”"
                if playing else "after this song")
        self.notice(ev["id"], f"★ {guest['display_name']} calls a SUPERSET, {what}! Vote on your phone.", "gold")
        self.emit(ev["id"], "superset_vote", {"status": "open", "name": guest["display_name"], "mode": mode})
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
            self._close_vote(vote, "passed", f"★ The vote passed ({yes}–{no})!", "gold")
            if self.get_event(vote["event_id"])["status"] == "active":
                try:
                    self.declare_superset(vote["event_id"], vote["mode"] or "after", "vote", vote["item_id"])
                except EngineError as exc:  # e.g. last call came while the vote was open
                    self.notice(vote["event_id"], exc.message, "warning")
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
