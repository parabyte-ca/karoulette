"""Song history across every event: who sang what, where and when, with singer names merged by hand."""
from __future__ import annotations

from collections import Counter

from .. import logic
from .constants import EngineError

STATUS_LABELS = {"played": "played", "playing": "singing", "skipped": "skipped"}


def name_key(name: str) -> str:
    """'  Alan ' and 'alan' are the same singer."""
    return " ".join((name or "").split()).casefold()


class HistoryMixin:
    def _aliases(self) -> dict[str, str]:
        return self.db.get_setting("singer_aliases", {}) or {}

    def _singer_groups(self) -> dict[str, str]:
        """Each name's group (by name_key): a hand-made merge if there is one, else the same name ignoring
        capitals and spaces, labelled with its most-used spelling."""
        spellings: dict[str, Counter] = {}
        for r in self.db.all("SELECT display_name FROM guests"):
            spellings.setdefault(name_key(r["display_name"]), Counter())[" ".join(r["display_name"].split())] += 1
        groups = {k: c.most_common(1)[0][0] for k, c in spellings.items()}
        groups.update(self._aliases())
        return groups

    def history(self) -> dict:
        rows = self.db.all(
            "SELECT q.id, q.event_id, q.title, q.channel, q.video_id, q.duration_s, q.status, q.is_superset, "
            "q.theme_name, q.cheers, q.played_at, q.added_at, COALESCE(r.number, q.round_no) AS round_number, "
            "e.name AS event_name, COALESCE(e.started_at, e.created_at) AS event_date, "
            "g.display_name AS singer, d.display_name AS duet "
            "FROM queue_items q JOIN events e ON e.id = q.event_id JOIN guests g ON g.id = q.guest_id "
            "LEFT JOIN guests d ON d.id = q.duet_guest_id LEFT JOIN rounds r ON r.id = q.round_id "
            "WHERE q.status IN ('played', 'playing', 'skipped') "
            "ORDER BY COALESCE(q.played_at, q.added_at) DESC, q.id DESC")
        groups = self._singer_groups()
        songs = [{
            "id": r["id"], "event_id": r["event_id"], "event": r["event_name"], "event_date": r["event_date"],
            "at": r["played_at"] or r["added_at"], "singer": r["singer"], "singer_group": groups[name_key(r["singer"])],
            "duet": r["duet"], "duet_group": groups[name_key(r["duet"])] if r["duet"] else None,
            "title": r["title"], "song": logic.song_name(r["title"]), "channel": r["channel"],
            "video_id": r["video_id"], "duration_s": r["duration_s"], "status": STATUS_LABELS[r["status"]],
            "superset": bool(r["is_superset"]), "theme": r["theme_name"], "cheers": r["cheers"],
            "round": r["round_number"],
        } for r in rows]
        return {"songs": songs, "public": self.history_public()}

    def history_public(self) -> bool:
        return bool(self.db.get_setting("history_public", True))

    def set_history_public(self, on: bool) -> bool:
        self.db.set_setting("history_public", bool(on))
        return bool(on)

    def singer_names(self) -> list[dict]:
        """Every name singers have used, with its group and song count (for merging in Host admin)."""
        rows = self.db.all("SELECT g.display_name AS name, COUNT(q.id) AS songs FROM guests g "
                           "LEFT JOIN queue_items q ON (q.guest_id = g.id OR q.duet_guest_id = g.id) "
                           "AND q.status IN ('played', 'playing', 'skipped') GROUP BY g.id")
        counts: Counter = Counter()
        spelling: dict[str, str] = {}
        for r in rows:
            if r["songs"]:
                counts[name_key(r["name"])] += r["songs"]
                spelling.setdefault(name_key(r["name"]), " ".join(r["name"].split()))
        groups = self._singer_groups()
        aliases = self._aliases()
        return sorted(({"name": spelling[k], "group": groups[k], "songs": n, "merged": k in aliases}
                       for k, n in counts.items()), key=lambda s: (s["group"].casefold(), s["name"].casefold()))

    def merge_singers(self, names: list[str], into: str) -> list[dict]:
        """Treat several names as one singer, shown as `into`. Names already merged move with their group."""
        into = logic.clean_name(into)
        if not 1 <= len(into) <= 24:
            raise EngineError("Give the singer a name of 1 to 24 characters.")
        keys = {name_key(n) for n in names if name_key(n)}
        if len(keys | {name_key(into)}) < 2:
            raise EngineError("Pick at least two names to merge.")
        aliases = self._aliases()
        old_groups = {name_key(aliases[k]) for k in keys if k in aliases} | keys
        for k, group in list(aliases.items()):  # names already in a group being merged follow it
            if name_key(group) in old_groups:
                aliases[k] = into
        for k in keys | {name_key(into)}:
            aliases[k] = into
        self.db.set_setting("singer_aliases", aliases)
        return self.singer_names()

    def unmerge_singer(self, name: str) -> list[dict]:
        aliases = self._aliases()
        aliases.pop(name_key(name), None)
        # A group left with only its own name isn't a merge any more.
        members: Counter = Counter(aliases.values())
        aliases = {k: g for k, g in aliases.items() if members[g] > 1}
        self.db.set_setting("singer_aliases", aliases)
        return self.singer_names()
