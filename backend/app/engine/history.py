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

    @staticmethod
    def _label(singer_name: str | None, display_name: str, groups: dict[str, str], aliases: dict[str, str]) -> str:
        """Who a song counts for: the singer code's name if the night is claimed, else the name group; the
        host's name merges apply on top of either."""
        if singer_name:
            return aliases.get(name_key(singer_name)) or singer_name
        return groups[name_key(display_name)]

    def history(self) -> dict:
        rows = self.db.all(
            "SELECT q.id, q.event_id, q.title, q.channel, q.video_id, q.duration_s, q.status, q.is_superset, "
            "q.theme_name, q.cheers, q.played_at, q.added_at, COALESCE(r.number, q.round_no) AS round_number, "
            "e.name AS event_name, COALESCE(e.started_at, e.created_at) AS event_date, "
            "g.display_name AS singer, d.display_name AS duet, gs.display_name AS singer_named, "
            "ds.display_name AS duet_named "
            "FROM queue_items q JOIN events e ON e.id = q.event_id JOIN guests g ON g.id = q.guest_id "
            "LEFT JOIN guests d ON d.id = q.duet_guest_id LEFT JOIN rounds r ON r.id = q.round_id "
            "LEFT JOIN singers gs ON gs.id = g.singer_id LEFT JOIN singers ds ON ds.id = d.singer_id "
            "WHERE q.status IN ('played', 'playing', 'skipped') "
            "ORDER BY COALESCE(q.played_at, q.added_at) DESC, q.id DESC")
        groups, aliases = self._singer_groups(), self._aliases()
        songs = [{
            "id": r["id"], "event_id": r["event_id"], "event": r["event_name"], "event_date": r["event_date"],
            "at": r["played_at"] or r["added_at"], "singer": r["singer"], "singer_group": self._label(r["singer_named"], r["singer"], groups, aliases),
            "duet": r["duet"], "duet_group": self._label(r["duet_named"], r["duet"], groups, aliases) if r["duet"] else None,
            "title": r["title"], "song": logic.song_name(r["title"]), "track": logic.playlist_song(r["title"]),
            "channel": r["channel"],
            "video_id": r["video_id"], "duration_s": r["duration_s"], "status": STATUS_LABELS[r["status"]],
            "superset": bool(r["is_superset"]), "theme": r["theme_name"], "cheers": r["cheers"],
            "round": r["round_number"],
        } for r in rows]
        return {"songs": songs, "public": self.history_public(), "awards": self.awards()}

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

    # ------------------------------------------------------------------ playlists

    def event_playlist(self, code: str) -> dict:
        """The songs played at an event, in order, for a playlist (anyone with the join code may see it)."""
        ev = self.event_by_code(code)
        rows = self.db.all(
            "SELECT q.id, q.title, q.video_id, g.display_name AS singer, d.display_name AS duet FROM queue_items q "
            "JOIN guests g ON g.id = q.guest_id LEFT JOIN guests d ON d.id = q.duet_guest_id "
            "WHERE q.event_id = ? AND q.status IN ('played', 'playing') ORDER BY q.played_at, q.id", (ev["id"],))
        return {"event": {"name": ev["name"], "code": ev["join_code"], "status": ev["status"],
                          "date": ev["started_at"] or ev["created_at"]},
                "tracks": [{"item_id": r["id"], "track": logic.playlist_song(r["title"]), "title": r["title"],
                            "singer": r["singer"], "duet": r["duet"], "karaoke_video_id": r["video_id"]} for r in rows]}

    def playlist_items(self, item_ids: list[int], event_code: str | None = None) -> list[dict]:
        """Sung songs by id (optionally only from one event), in the order asked for."""
        if not item_ids:
            return []
        marks = ",".join("?" * len(item_ids))
        sql = (f"SELECT q.id, q.title, q.video_id FROM queue_items q JOIN events e ON e.id = q.event_id "
               f"WHERE q.id IN ({marks}) AND q.status IN ('played', 'playing', 'skipped')")
        params = list(item_ids)
        if event_code is not None:
            sql += " AND e.join_code = ?"
            params.append(event_code.upper())
        found = {r["id"]: r for r in self.db.all(sql, params)}
        return [{"item_id": i, "track": logic.playlist_song(found[i]["title"]), "karaoke_video_id": found[i]["video_id"]}
                for i in item_ids if i in found]

    def spotify_client_id(self, env_value: str = "") -> str:
        return env_value or self.db.get_setting("spotify_client_id", "") or ""

    def set_spotify_client_id(self, client_id: str) -> str:
        self.db.set_setting("spotify_client_id", client_id.strip())
        return client_id.strip()
