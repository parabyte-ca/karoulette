"""Read models: the live snapshot, the recap, CSV history and appearance."""
from __future__ import annotations

import csv
import io
from datetime import datetime, timezone

from .. import logic
from .constants import (ACTIVE_QUEUE_STATUSES, COLOUR_SCHEMES, DEFAULT_SCHEME, REACTIONS, STAGE_BANNER,
                        UNKNOWN_DURATION_S, EngineError)


class ViewsMixin:
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

        active_set = self._active_set(event_id)
        set_id = active_set["id"] if active_set else None

        def item_out(i: dict) -> dict:
            return {"id": i["id"], "video_id": i["video_id"], "title": i["title"], "channel": i["channel"],
                    "duration_s": i["duration_s"], "thumbnail": i["thumbnail"], "guest_id": i["guest_id"],
                    "guest_name": names.get(i["guest_id"], "?"), "theme": i["theme_name"],
                    "round": i["round_no"], "priority": i["priority"] is not None,
                    "is_superset": bool(set_id and i["set_id"] == set_id) if i["status"] in ACTIVE_QUEUE_STATUSES
                    else bool(i["is_superset"]),
                    "flags": flag_counts.get(i["id"], 0), "status": i["status"],
                    "duet_guest_id": i["duet_guest_id"],
                    "duet_name": names.get(i["duet_guest_id"]) if i["duet_guest_id"] else None,
                    "started_at": i["played_at"] if i["status"] == "playing" else None, "cheers": i["cheers"]}

        queue = [item_out(i) for i in self._queue(event_id)]
        playing = self.db.one("SELECT * FROM queue_items WHERE id = ?", (ev["now_playing_item_id"],)) \
            if ev["now_playing_item_id"] else None
        recent = [item_out(i) for i in self.db.all(
            "SELECT * FROM queue_items WHERE event_id = ? AND status = 'played' ORDER BY played_at DESC LIMIT 10",
            (event_id,))]
        history = [{"number": r["number"], "theme": r["theme_name"]}
                   for r in self.db.all("SELECT * FROM rounds WHERE event_id = ? AND theme_name IS NOT NULL "
                                        "ORDER BY id DESC LIMIT 12", (event_id,))]
        set_history = [{"theme": r["theme_name"], "status": r["status"], "source": r["source"]}
                       for r in self.db.all("SELECT * FROM superset_sets WHERE event_id = ? ORDER BY id DESC LIMIT 12",
                                            (event_id,))]
        counts: dict[int, int] = {}
        for q in queue:
            counts[q["guest_id"]] = counts.get(q["guest_id"], 0) + 1
        themed = bool(ev["config"]["themes_enabled"] and rnd and rnd["theme_name"])
        theme = self._theme(rnd["theme_id"]) if themed else None
        superset = self._set_out(event_id, ev, names)
        return {
            "server_time": now,
            "event": {"id": ev["id"], "name": ev["name"], "join_code": ev["join_code"], "status": ev["status"],
                      "config": ev["config"], "paused": bool(ev["paused"])},
            "round": {"number": ev["current_round"], "is_superset": superset is not None,
                      "theme": (self._theme_out(theme) or {"id": None, "name": rnd["theme_name"], "description": ""})
                      if themed else None,
                      "spun_at": rnd["spun_at"] if themed else None,
                      "spin_seconds": int(ev["config"]["spin_seconds"])},
            "superset": superset,
            "guests": [{"id": g["id"], "name": g["display_name"], "rotation_pos": g["rotation_pos"],
                        "new_singer": bool(g["debut_pending"]), "queued": counts.get(g["id"], 0)}
                       for g in active],
            "queue": queue,
            "now_playing": {**item_out(playing), "starts_at": ev["ready_until"] or playing["played_at"]}
            if playing else None,
            "recent": recent,
            "rounds": history,
            "superset_history": set_history,
            "appearance": self.appearance(),
            "reactions": list(REACTIONS),
            "superset_vote": self._vote_out(event_id, names),
            "vote_callers": [r["called_by"] for r in self.db.all(
                "SELECT called_by FROM superset_votes WHERE round_id = ?", (rnd["id"],))] if rnd else [],
            "recap": self.recap(event_id) if ev["status"] == "ended" else None,
            "last_call": self.last_call_info(ev),
        }

    def _set_out(self, event_id: int, ev: dict, names: dict[int, str]) -> dict | None:
        """The Superset set under way: its theme and every singer's turn, in order."""
        sset = self._active_set(event_id)
        if not sset:
            return None
        slots = self._slots(sset["id"])
        items = {i["id"]: i for i in self.db.all("SELECT * FROM queue_items WHERE set_id = ?", (sset["id"],))}
        open_slot = self._open_slot(sset["id"])
        waiting = open_slot["guest_id"] if open_slot and open_slot["status"] == "pending" \
            and not ev["now_playing_item_id"] else None
        out = []
        for sl in slots:
            item = items.get(sl["item_id"])
            status = "singing" if item and item["id"] == ev["now_playing_item_id"] else sl["status"]
            out.append({"guest_id": sl["guest_id"], "name": names.get(sl["guest_id"], "?"), "status": status,
                        "item_id": sl["item_id"], "title": item["title"] if item else None,
                        "duration_s": item["duration_s"] if item else None,
                        "duet_name": names.get(item["duet_guest_id"]) if item and item["duet_guest_id"] else None})
        theme = self._theme(sset["theme_id"])
        # Search ideas for phones: the theme's own list, or the artist and title of the song that kicked it off.
        ideas = logic.split_ideas(theme["ideas"]) if theme else logic.song_parts(sset["inspired_by"] or "")
        return {"id": sset["id"], "theme": sset["theme_name"], "description": theme["description"] if theme else "",
                "ideas": ideas,
                "inspired_by": sset["inspired_by"], "mode": sset["mode"], "source": sset["source"],
                "spun_at": sset["spun_at"], "spin_seconds": int(ev["config"]["spin_seconds"]) + 2,
                "slots": out, "waiting_for": waiting}

    def _vote_out(self, event_id: int, names: dict[int, str]) -> dict | None:
        vote = self._open_vote(event_id)
        if not vote:
            return None
        yes, no, eligible = self._vote_counts(vote)
        voters = [b["guest_id"] for b in self.db.all("SELECT guest_id FROM superset_ballots WHERE vote_id = ?",
                                                      (vote["id"],))]
        item = self.db.one("SELECT title FROM queue_items WHERE id = ?", (vote["item_id"],)) if vote["item_id"] else None
        return {"id": vote["id"], "called_by": vote["called_by"], "called_by_name": names.get(vote["called_by"], "?"),
                "ends_at": vote["ends_at"], "yes": yes, "no": no, "eligible": eligible, "voters": voters,
                "mode": vote["mode"], "song": logic.song_name(item["title"]) if item else None}

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
        sets = self.db.one("SELECT COUNT(*) AS n FROM superset_sets WHERE event_id = ? AND status = 'done'",
                           (event_id,))["n"]
        theme_counts: dict[str, int] = {}
        for s in sung:
            if s["theme_name"]:
                theme_counts[s["theme_name"]] = theme_counts.get(s["theme_name"], 0) + 1
        stars = sorted({s["display_name"] for s in sung if s["set_id"] and s["id"] not in flagged})
        fav = max(sung, key=lambda s: s["cheers"], default=None)
        cheered: dict[str, int] = {}
        for s in sung:
            for name in filter(None, (s["display_name"], s["duet_name"])):
                cheered[name] = cheered.get(name, 0) + s["cheers"]
        top_cheered = max(cheered.items(), key=lambda kv: kv[1], default=None)
        top_cheered = top_cheered if top_cheered and top_cheered[1] else None
        song = (lambda s: {"title": s["title"], "singer": s["display_name"] + (f" & {s['duet_name']}"
                                                                              if s["duet_name"] else "")})
        longest = max(sung, key=lambda s: s["duration_s"] or 0, default=None)
        return {
            "songs": len(sung),
            "singers": len(per_singer),
            "minutes": round(sum(s["duration_s"] or UNKNOWN_DURATION_S for s in sung) / 60),
            "duets": sum(1 for s in sung if s["duet_name"]),
            "rounds": len(rounds),
            "superset_rounds": sets,
            "top_singers": sorted(n for n, c in per_singer.items() if c == best) if best else [],
            "top_count": best,
            "per_singer": per_singer,
            "top_themes": [t for t, _ in sorted(theme_counts.items(), key=lambda kv: (-kv[1], kv[0]))[:3]],
            "superset_stars": stars,
            "crowd_favourite": ({**song(fav), "cheers": fav["cheers"]} if fav and fav["cheers"] else None),
            "most_cheered": ({"singer": top_cheered[0], "cheers": top_cheered[1]} if top_cheered else None),
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
        """The colour scheme and banner every screen uses. Main Stage always has a banner (yours if you've
        uploaded one, else its built-in photo); other schemes show an uploaded banner only if asked to."""
        scheme = self.db.get_setting("colour_scheme", DEFAULT_SCHEME)
        scheme = scheme if scheme in COLOUR_SCHEMES else DEFAULT_SCHEME
        custom = self.db.get_setting("banner_custom")
        banner_all = bool(self.db.get_setting("banner_all", False))
        url = f"/api/public/banner?v={custom['version']}" if custom else None
        out = {"scheme": scheme, "custom_banner": bool(custom), "custom_url": url, "banner_all": banner_all,
               "banner": None, "banner_small": None, "og_image": None}
        if custom and (scheme == "stage" or banner_all):
            out.update(banner=url, banner_small=url, og_image=url)
        elif scheme == "stage":
            out.update(STAGE_BANNER)
        return out

    def set_banner(self, ext: str | None) -> dict:
        """Record (or clear) an uploaded banner; the file itself is kept in the data folder by the server."""
        self.db.set_setting("banner_custom", {"ext": ext, "version": int(self.clock())} if ext else None)
        return self.appearance()

    def set_banner_all(self, on: bool) -> dict:
        self.db.set_setting("banner_all", bool(on))
        return self.appearance()

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
                    "duration_s", "status", "cheers", "youtube_url"])
        for r in rows:
            ts = datetime.fromtimestamp(r["played_at"] or r["added_at"], tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
            w.writerow([ev["name"], ts, r["round_number"] or "", "yes" if r["is_superset"] else "no",
                        r["theme_name"] or "", r["display_name"] + (f" & {r['duet_name']}" if r["duet_name"] else ""),
                        r["title"], r["channel"], r["duration_s"] or "",
                        r["status"], r["cheers"], f"https://www.youtube.com/watch?v={r['video_id']}"])
        return buf.getvalue()
