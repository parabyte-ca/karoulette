"""Returning singers: a singer code that follows a person across events, and claiming past nights.

Each night someone sang (a ``guests`` row) belongs to at most one singer. A phone that was there claims
it automatically; anyone can claim a name group on the honour system; the first claim wins, and a claim
on a night someone else already owns goes to the host as a dispute. The host can move any night.
"""
from __future__ import annotations

import secrets

from .. import logic
from .constants import JOIN_CODE_ALPHABET, EngineError, hash_token
from .history import name_key

PAST_SONG_STATUSES = ("played", "playing")


class SingersMixin:
    # ------------------------------------------------------------------ singers and codes

    def _new_singer_code(self) -> str:
        while True:
            code = "".join(secrets.choice(JOIN_CODE_ALPHABET) for _ in range(6))
            if not self.db.one("SELECT 1 FROM singers WHERE code = ?", (code,)):
                return code

    def singer_by_code(self, code: str) -> dict:
        code = (code or "").strip().upper()
        s = self.db.one("SELECT * FROM singers WHERE code = ?", (code,)) if len(code) == 6 else None
        if not s:
            raise EngineError("That singer code didn't match. Check it, or ask the host.", 404)
        return s

    def _singer(self, singer_id: int | None) -> dict | None:
        return self.db.one("SELECT * FROM singers WHERE id = ?", (singer_id,)) if singer_id else None

    def singer_info(self, singer: dict | None) -> dict | None:
        if not singer:
            return None
        nights = self.db.one("SELECT COUNT(*) AS n FROM guests WHERE singer_id = ?", (singer["id"],))["n"]
        return {"code": singer["code"], "name": singer["display_name"], "nights": nights}

    def attach_singer(self, guest_id: int, singer_code: str | None = None, known_tokens: list[str] | None = None) -> dict:
        """After joining: link tonight to the phone's singer code (or make one), and claim any past nights this
        phone was at. Returns the singer and what was claimed."""
        guest = self._guest(guest_id)
        if guest["singer_id"] and not singer_code:  # already has one (e.g. pressed twice)
            return {"singer": self.singer_info(self._singer(guest["singer_id"])), "new": False, "code_invalid": False,
                    "claimed": 0, "disputed": 0}
        singer = None
        if singer_code:
            try:
                singer = self.singer_by_code(singer_code)
            except EngineError:  # the host reset it: the phone asks for the new one instead of starting over
                return {"singer": None, "code_invalid": True, "new": False, "claimed": 0, "disputed": 0}
        new = singer is None
        if new:
            sid = self.db.insert("INSERT INTO singers(code, display_name, created_at) VALUES (?, ?, ?)",
                                 (self._new_singer_code(), guest["display_name"], self.clock()))
            singer = self._singer(sid)
        else:
            self.db.execute("UPDATE singers SET display_name = ? WHERE id = ?", (guest["display_name"], singer["id"]))
        self._claim(singer, guest, "phone", log=False)
        claimed, disputed = [], []
        for token in (known_tokens or [])[:30]:
            past = self.db.one("SELECT * FROM guests WHERE token_hash = ?", (hash_token(token or ""),))
            if past and past["id"] != guest_id:
                (claimed if self._claim(singer, past, "phone") else disputed).append(past["id"])
        if new:
            self.log(guest["event_id"], "singers", f"{guest['display_name']} got singer code {singer['code']}",
                     guest_id=guest_id)
        return {"singer": self.singer_info(self._singer(singer["id"])), "new": new, "code_invalid": False,
                "claimed": len(claimed), "disputed": len(disputed)}

    def use_singer_code(self, guest_id: int, singer_code: str) -> dict:
        """'I have a singer code' on a new phone: tonight, and anything the code made for this phone had claimed,
        moves to that singer; the spare code goes."""
        singer = self.singer_by_code(singer_code)
        guest = self._guest(guest_id)
        old = guest["singer_id"]
        self.db.execute("UPDATE guests SET singer_id = ?, claimed_how = 'phone' WHERE id = ?", (singer["id"], guest_id))
        if old and old != singer["id"]:
            self.db.execute("UPDATE guests SET singer_id = ? WHERE singer_id = ?", (singer["id"], old))
            self.db.execute("UPDATE singer_claims SET singer_id = ? WHERE singer_id = ? AND status = 'pending' AND "
                            "guest_id NOT IN (SELECT guest_id FROM singer_claims WHERE singer_id = ?)",
                            (singer["id"], old, singer["id"]))
            self.db.execute("DELETE FROM singers WHERE id = ?", (old,))
        self.log(guest["event_id"], "singers", f"{guest['display_name']} used singer code {singer['code']} "
                 f"({singer['display_name']})", guest_id=guest_id)
        return self.singer_info(singer)

    def _claim(self, singer: dict, guest: dict, how: str, log: bool = True) -> bool:
        """Give a night to a singer if it's free (True); if someone else owns it, open a dispute (False)."""
        if guest["singer_id"] == singer["id"]:
            return True
        if guest["singer_id"] is None:
            self.db.execute("UPDATE guests SET singer_id = ?, claimed_how = ? WHERE id = ?",
                            (singer["id"], how, guest["id"]))
            if log:
                self.log(guest["event_id"], "singers", f"{singer['display_name']} ({singer['code']}) claimed this "
                         f"night as {guest['display_name']} ({'this phone was there' if how == 'phone' else 'by name'})",
                         automatic=True, guest_id=guest["id"])
            return True
        self.db.execute("INSERT OR IGNORE INTO singer_claims(singer_id, guest_id, how, created_at) VALUES (?, ?, ?, ?)",
                        (singer["id"], guest["id"], how, self.clock()))
        return False

    # ------------------------------------------------------------------ claiming past nights by name

    def claimable_names(self, singer_code: str) -> list[dict]:
        """Past names to claim, grouped like the song history (merged spellings together)."""
        singer = self.singer_by_code(singer_code)
        groups = self._singer_groups()
        out: dict[str, dict] = {}
        rows = self.db.all("SELECT g.id, g.display_name, g.singer_id, e.name AS event_name, "
                           "COALESCE(e.started_at, e.created_at) AS event_date, "
                           "(SELECT COUNT(*) FROM queue_items q WHERE q.guest_id = g.id AND q.status IN "
                           "('played', 'playing', 'skipped')) AS songs "
                           "FROM guests g JOIN events e ON e.id = g.event_id ORDER BY event_date DESC")
        for r in rows:
            label = groups.get(name_key(r["display_name"])) or r["display_name"]
            g = out.setdefault(label, {"name": label, "nights": 0, "songs": 0, "mine": 0, "others": 0, "free": 0,
                                       "events": [], "last": r["event_date"]})
            g["nights"] += 1
            g["songs"] += r["songs"]
            owner = "mine" if r["singer_id"] == singer["id"] else "others" if r["singer_id"] else "free"
            g[owner] += 1
            if len(g["events"]) < 3:
                g["events"].append(r["event_name"])
        return sorted(out.values(), key=lambda g: (-g["last"], g["name"].casefold()))

    def claim_names(self, singer_code: str, names: list[str]) -> dict:
        """Honour system: claim every night under these name groups. Nights someone else owns become disputes."""
        singer = self.singer_by_code(singer_code)
        groups = self._singer_groups()
        wanted = {name_key(n) for n in names}
        claimed = disputed = 0
        for g in self.db.all("SELECT * FROM guests"):
            label = groups.get(name_key(g["display_name"])) or g["display_name"]
            if name_key(label) in wanted:
                if self._claim(singer, g, "name"):
                    claimed += 1
                else:
                    disputed += 1
        return {"claimed": claimed, "disputed": disputed, "singer": self.singer_info(singer)}

    def past_songs(self, singer_code: str, limit: int = 50) -> list[dict]:
        """A singer's songs from past nights, newest first, one per song (for one-tap re-adding)."""
        singer = self.singer_by_code(singer_code)
        rows = self.db.all(
            "SELECT q.video_id, q.title, q.channel, q.duration_s, q.thumbnail, q.played_at, e.name AS event_name "
            "FROM queue_items q JOIN guests g ON g.id = q.guest_id JOIN events e ON e.id = q.event_id "
            f"WHERE g.singer_id = ? AND q.status IN {PAST_SONG_STATUSES} ORDER BY q.played_at DESC",
            (singer["id"],))
        seen, out = set(), []
        for r in rows:
            key = logic.song_key(r["title"]) or r["video_id"]
            if key in seen:
                continue
            seen.add(key)
            out.append({**r, "times": sum(1 for x in rows if (logic.song_key(x["title"]) or x["video_id"]) == key)})
            if len(out) >= limit:
                break
        return out

    # ------------------------------------------------------------------ host tools

    def singers_admin(self) -> dict:
        nights = self.db.all(
            "SELECT g.id AS guest_id, g.display_name AS name, g.singer_id, g.claimed_how, e.id AS event_id, "
            "e.name AS event_name, COALESCE(e.started_at, e.created_at) AS event_date, "
            "(SELECT COUNT(*) FROM queue_items q WHERE q.guest_id = g.id AND q.status IN ('played', 'playing', "
            "'skipped')) AS songs FROM guests g JOIN events e ON e.id = g.event_id ORDER BY event_date DESC, g.id")
        singers = [{"id": s["id"], "code": s["code"], "name": s["display_name"], "created_at": s["created_at"],
                    "nights": [n for n in nights if n["singer_id"] == s["id"]]}
                   for s in self.db.all("SELECT * FROM singers ORDER BY display_name COLLATE NOCASE")]
        disputes = self.db.all(
            "SELECT c.id, c.how, c.created_at, s.display_name AS claimant, s.code AS claimant_code, "
            "g.display_name AS name, e.name AS event_name, COALESCE(e.started_at, e.created_at) AS event_date, "
            "o.display_name AS owner, o.code AS owner_code, g.claimed_how AS owner_how "
            "FROM singer_claims c JOIN singers s ON s.id = c.singer_id JOIN guests g ON g.id = c.guest_id "
            "JOIN events e ON e.id = g.event_id LEFT JOIN singers o ON o.id = g.singer_id "
            "WHERE c.status = 'pending' ORDER BY c.created_at")
        return {"singers": singers, "unclaimed": [n for n in nights if n["singer_id"] is None], "disputes": disputes}

    def assign_night(self, guest_id: int, singer_id: int | None) -> dict:
        """Host: give a night to a singer, move it to another, or unclaim it (None)."""
        guest = self._guest(guest_id)
        singer = self._singer(singer_id)
        if singer_id and not singer:
            raise EngineError("Singer not found", 404)
        self.db.execute("UPDATE guests SET singer_id = ?, claimed_how = ? WHERE id = ?",
                        (singer_id, "host" if singer_id else None, guest_id))
        self.db.execute("UPDATE singer_claims SET status = 'declined', decided_at = ? WHERE guest_id = ? "
                        "AND status = 'pending'", (self.clock(), guest_id))
        self.log(guest["event_id"], "singers", f"This night as {guest['display_name']} was "
                 + (f"given to {singer['display_name']} ({singer['code']})" if singer else "unclaimed"), guest_id=guest_id)
        return self.singers_admin()

    def decide_claim(self, claim_id: int, approve: bool) -> dict:
        claim = self.db.one("SELECT * FROM singer_claims WHERE id = ?", (claim_id,))
        if not claim or claim["status"] != "pending":
            raise EngineError("That claim has already been decided.", 409)
        self.db.execute("UPDATE singer_claims SET status = ?, decided_at = ? WHERE id = ?",
                        ("approved" if approve else "declined", self.clock(), claim_id))
        if approve:
            self.assign_night(claim["guest_id"], claim["singer_id"])
        return self.singers_admin()

    def reset_singer_code(self, singer_id: int) -> dict:
        """Host: a code was shared or lost. Phones with the old code are asked for the new one when they next join."""
        singer = self._singer(singer_id)
        if not singer:
            raise EngineError("Singer not found", 404)
        self.db.execute("UPDATE singers SET code = ? WHERE id = ?", (self._new_singer_code(), singer_id))
        return self.singers_admin()
