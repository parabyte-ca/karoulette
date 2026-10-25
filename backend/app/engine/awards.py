"""Awards across every event: regulars, perfect attendance, streaks, all-time records, first nights and each
singer's personal bests. Singers are counted the way the Song history counts them (singer code first, then
the name group, with the host's merges on top), and a night counts once someone has sung at it."""
from __future__ import annotations

from collections import Counter
from datetime import datetime

from .. import logic

MILESTONES = (5, 10, 25, 50, 100)


def ordinal(n: int) -> str:
    return f"{n}{'th' if 10 <= n % 100 <= 20 else {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th')}"


def longest_run(indexes: list[int]) -> int:
    best = run = 0
    prev = None
    for i in indexes:
        run = run + 1 if prev is not None and i == prev + 1 else 1
        best = max(best, run)
        prev = i
    return best


def run_ending(indexes: list[int], at: int) -> int:
    """How many nights in a row a singer has sung, ending at night ``at``."""
    have = set(indexes)
    n = 0
    while at - n in have:
        n += 1
    return n


class AwardsMixin:
    def _award_data(self) -> tuple[list[dict], dict[str, dict]]:
        """Nights in order (only those with songs) and each singer's numbers."""
        rows = self.db.all(
            "SELECT q.event_id, q.title, q.cheers, e.name AS event_name, COALESCE(e.started_at, e.created_at) AS event_date, "
            "g.display_name AS singer, gs.display_name AS singer_named, d.display_name AS duet, "
            "ds.display_name AS duet_named FROM queue_items q JOIN events e ON e.id = q.event_id "
            "JOIN guests g ON g.id = q.guest_id LEFT JOIN guests d ON d.id = q.duet_guest_id "
            "LEFT JOIN singers gs ON gs.id = g.singer_id LEFT JOIN singers ds ON ds.id = d.singer_id "
            "WHERE q.status IN ('played', 'playing') ORDER BY COALESCE(q.played_at, q.added_at), q.id")
        groups, aliases = self._singer_groups(), self._aliases()
        events: dict[int, dict] = {}
        for r in rows:
            events.setdefault(r["event_id"], {"id": r["event_id"], "name": r["event_name"], "date": r["event_date"]})
        ordered = sorted(events.values(), key=lambda e: (e["date"], e["id"]))
        index = {e["id"]: i for i, e in enumerate(ordered)}
        stats: dict[str, dict] = {}
        for r in rows:
            labels = {self._label(r["singer_named"], r["singer"], groups, aliases)}
            if r["duet"]:
                labels.add(self._label(r["duet_named"], r["duet"], groups, aliases))
            for name in labels:
                s = stats.setdefault(name, {"name": name, "nights": [], "per_night": Counter(), "songs": 0,
                                            "cheers": 0, "top_song": None, "song_counts": Counter(), "titles": {}})
                i = index[r["event_id"]]
                if not s["nights"] or s["nights"][-1] != i:
                    s["nights"].append(i)
                s["per_night"][i] += 1
                s["songs"] += 1
                s["cheers"] += r["cheers"]
                if r["cheers"] and (not s["top_song"] or r["cheers"] > s["top_song"]["cheers"]):
                    s["top_song"] = {"title": r["title"], "cheers": r["cheers"], "event": r["event_name"], "night": i}
                key = logic.song_key(r["title"])
                s["song_counts"][key] += 1
                s["titles"].setdefault(key, logic.song_name(r["title"]))
        return ordered, stats

    def awards(self) -> dict:
        """The Awards board (Song history and /history)."""
        ordered, stats = self._award_data()
        everyone = list(stats.values())
        total = len(ordered)
        regulars = sorted((s for s in everyone if len(s["nights"]) >= 2), key=lambda s: (-len(s["nights"]), s["name"]))[:5]
        streaks = sorted(((s["name"], longest_run(s["nights"])) for s in everyone), key=lambda t: (-t[1], t[0]))
        records = []
        if everyone:
            top = max(everyone, key=lambda s: (s["songs"], -min(s["nights"])))
            records.append({"award": "Most songs ever", "holder": top["name"], "value": f"{top['songs']} songs"})
            loud = max(everyone, key=lambda s: s["cheers"])
            if loud["cheers"]:
                records.append({"award": "Most cheers ever", "holder": loud["name"], "value": f"{loud['cheers']} cheers"})
            night_best = max(((s["name"], n, i) for s in everyone for i, n in s["per_night"].items()), key=lambda t: t[1])
            records.append({"award": "Most songs in one night", "holder": night_best[0],
                            "value": f"{night_best[1]} songs at {ordered[night_best[2]]['name']}"})
        songs: Counter = Counter()
        names: dict[str, str] = {}
        for r in self.db.all("SELECT title FROM queue_items WHERE status IN ('played', 'playing')"):  # each song once
            key = logic.song_key(r["title"])
            songs[key] += 1
            names.setdefault(key, logic.song_name(r["title"]))
        if songs:
            key, n = songs.most_common(1)[0]
            if n > 1:
                records.append({"award": "Most-sung song", "holder": names[key], "value": f"sung {n} times"})
        year = datetime.fromtimestamp(self.clock()).year
        fav = self.db.one(
            "SELECT q.title, q.cheers, e.name AS event_name, g.display_name AS singer FROM queue_items q "
            "JOIN events e ON e.id = q.event_id JOIN guests g ON g.id = q.guest_id "
            "WHERE q.status IN ('played', 'playing') AND q.cheers > 0 AND COALESCE(q.played_at, q.added_at) >= ? "
            "ORDER BY q.cheers DESC, q.played_at LIMIT 1", (datetime(year, 1, 1).timestamp(),))
        if fav:
            records.append({"award": f"Crowd favourite of {year}", "holder": f"{fav['singer']} · {logic.song_name(fav['title'])}",
                            "value": f"{fav['cheers']} cheers at {fav['event_name']}"})
        newest = sorted(everyone, key=lambda s: (-s["nights"][0], s["name"]))[:6]
        return {
            "nights": total,
            "regulars": [{"name": s["name"], "nights": len(s["nights"])} for s in regulars],
            "perfect_attendance": sorted(s["name"] for s in everyone if total >= 3 and len(s["nights"]) == total),
            "streaks": [{"name": n, "nights": k} for n, k in streaks if k >= 3][:5],
            "records": records,
            "newcomers": [{"name": s["name"], "event": ordered[s["nights"][0]]["name"],
                           "date": ordered[s["nights"][0]]["date"]} for s in newest],
        }

    def event_awards(self, event_id: int) -> dict:
        """Badges for one night's recap: first nights, milestone nights and streaks."""
        ordered, stats = self._award_data()
        at = next((i for i, e in enumerate(ordered) if e["id"] == event_id), None)
        if at is None:
            return {"first_nights": [], "milestones": []}
        first, milestones = [], []
        for s in sorted(stats.values(), key=lambda s: s["name"]):
            if at not in s["nights"]:
                continue
            nth = s["nights"].index(at) + 1
            streak = run_ending(s["nights"], at)
            if nth == 1:
                first.append(s["name"])
            elif nth in MILESTONES:
                milestones.append(f"{s['name']}: {ordinal(nth)} night!")
            elif streak >= 3:
                milestones.append(f"{s['name']}: {streak} nights in a row")
        return {"first_nights": first, "milestones": milestones}

    def personal_awards(self, guest_id: int) -> dict | None:
        """A singer's own records, for their phone, with anything they beat tonight."""
        guest = self._guest(guest_id)
        singer = self._singer(guest["singer_id"])
        name = self._label(singer["display_name"] if singer else None, guest["display_name"],
                           self._singer_groups(), self._aliases())
        ordered, stats = self._award_data()
        s = stats.get(name)
        if not s:
            return None
        tonight = next((i for i, e in enumerate(ordered) if e["id"] == guest["event_id"]), None)
        best_i, best_n = max(s["per_night"].items(), key=lambda kv: (kv[1], -kv[0]))
        fav_key, fav_n = s["song_counts"].most_common(1)[0]
        news = []
        if tonight is not None and tonight in s["nights"]:
            if s["nights"][0] == tonight:
                news.append("First night! 🎉 Welcome to the stage.")
            else:
                before = max((n for i, n in s["per_night"].items() if i != tonight), default=0)
                if s["per_night"][tonight] > before:
                    news.append(f"New personal best: {s['per_night'][tonight]} songs in one night!")
                if s["top_song"] and s["top_song"]["night"] == tonight:
                    news.append(f"Your most-cheered song yet: {s['top_song']['cheers']} cheers!")
                streak = run_ending(s["nights"], tonight)
                if streak >= 3:
                    news.append(f"{streak} nights in a row! 🔥")
        return {
            "name": name, "nights": len(s["nights"]), "songs": s["songs"], "cheers": s["cheers"],
            "best_night": {"songs": best_n, "event": ordered[best_i]["name"]},
            "top_song": {k: s["top_song"][k] for k in ("title", "cheers", "event")} if s["top_song"] else None,
            "favourite": {"song": s["titles"][fav_key], "times": fav_n} if fav_n > 1 else None,
            "streak": longest_run(s["nights"]),
            "first_night": {"event": ordered[s["nights"][0]]["name"], "date": ordered[s["nights"][0]]["date"]},
            "tonight": news,
        }
