"""Pure, side-effect-free game logic: singer order, fair queue order, theme picking, superset rolls and votes.

Everything here works on plain dicts so it can be unit tested without a database.
"""
from __future__ import annotations

import random
import re
import unicodedata
from datetime import datetime, timedelta
from typing import Iterable, Sequence

DEFAULT_EVENT_CONFIG: dict = {
    "themes_enabled": False,     # spin a theme each round as a suggestion; off = singers pick freely
    "superset_chance": 0.0,      # chance a new round opens with a Superset (they mostly come from votes)
    "recent_theme_window": 3,
    "prevent_duplicates": True,
    "safe_search": "moderate",   # none | moderate | strict
    "max_duration_s": 900,       # 0 disables the limit
    "autoplay": True,
    "spin_seconds": 5,
    "ready_seconds": 5,          # "Get ready" countdown on the TV before each song; 0 turns it off
    "max_songs_per_singer": 0,   # songs a singer may have waiting at once; 0 = no limit
    "superset_vote_seconds": 60, # how long a guest-called Superset vote stays open
    "last_call": "",             # "HH:MM" closing time; songs that would run past it are refused
}

CONFIG_LIMITS: dict = {
    "superset_chance": (0.0, 1.0),
    "recent_theme_window": (0, 20),
    "max_duration_s": (0, 3600),
    "spin_seconds": (1, 15),
    "ready_seconds": (0, 60),
    "max_songs_per_singer": (0, 50),
    "superset_vote_seconds": (15, 300),
}


def merge_config(base: dict, overrides: dict | None) -> dict:
    """Merge overrides into a config, validating types and clamping to sane limits."""
    cfg = {**DEFAULT_EVENT_CONFIG, **{k: v for k, v in (base or {}).items() if k in DEFAULT_EVENT_CONFIG}}
    for key, value in (overrides or {}).items():
        if key not in DEFAULT_EVENT_CONFIG or value is None:
            continue
        default = DEFAULT_EVENT_CONFIG[key]
        if isinstance(default, bool):
            cfg[key] = bool(value)
        elif isinstance(default, (int, float)):
            num = float(value) if isinstance(default, float) else int(value)
            lo, hi = CONFIG_LIMITS.get(key, (num, num))
            cfg[key] = min(max(num, lo), hi)
        elif key == "safe_search":
            if value not in ("none", "moderate", "strict"):
                raise ValueError("safe_search must be none, moderate or strict")
            cfg[key] = value
        elif key == "last_call":
            value = str(value).strip()
            if value and not re.fullmatch(r"([01]?\d|2[0-3]):[0-5]\d", value):
                raise ValueError("Last call must be a time like 23:30, or blank")
            cfg[key] = value.zfill(5) if value else ""
    return cfg


# --------------------------------------------------------------------------- singer order

def ordered_active(guests: Iterable[dict]) -> list[dict]:
    return sorted((g for g in guests if g.get("status", "active") == "active"),
                  key=lambda g: (g["rotation_pos"], g["id"]))


def next_rotation_pos(guests: Iterable[dict]) -> int:
    positions = [g["rotation_pos"] for g in guests]
    return (max(positions) + 1) if positions else 1


# --------------------------------------------------------------------------- fair queue

def assign_round(current_round: int, anchor_pos: int | None, singer_pos: int, last_round: int | None) -> int:
    """The round a singer's new song belongs to: one song per singer per round, in singer order.

    It goes in the current round if the singer's slot in it is still ahead of the singer on the mic
    and they have no song there yet; otherwise in the next round after their last song.
    """
    current_round = max(current_round, 1)
    slot_ahead = anchor_pos is None or singer_pos > anchor_pos
    base = current_round if slot_ahead else current_round + 1
    return max(base, (last_round or 0) + 1)


def sort_key(item: dict, positions: dict[int, int], current_round: int) -> tuple:
    """Play order: prioritised songs first (host "play next", re-pick after an embed error), then by
    round, then by the singer's place in the order (``order_bias`` lets a singer step back a place)."""
    if item.get("priority") is not None:
        return (0, float(item["priority"]), 0, 0.0, item["id"])
    rnd = item.get("round_no") or max(current_round, 1)
    pos = positions.get(item["guest_id"], 10 ** 6) + float(item.get("order_bias") or 0)
    return (1, 0.0, rnd, pos, item["id"])


def play_order(items: Iterable[dict], positions: dict[int, int] | None = None, current_round: int = 1) -> list[dict]:
    positions = positions or {}
    return sorted((i for i in items if i["status"] == "queued"), key=lambda i: sort_key(i, positions, current_round))


def is_duplicate(items: Iterable[dict], video_id: str) -> bool:
    return any(i["video_id"] == video_id and i["status"] in ("queued", "playing", "played") for i in items)


# --------------------------------------------------------------------------- themes

def pick_theme(themes: Sequence[dict], history_ids: Sequence[int], window: int,
               rng: random.Random) -> dict | None:
    """Weighted random theme.

    Never repeats the previous theme when an alternative exists, and avoids the last
    ``window`` themes when possible (relaxed progressively if the list is too short).
    """
    enabled = [t for t in themes if t.get("enabled", True) and float(t.get("weight", 1)) > 0]
    if not enabled:
        return None
    last = history_ids[-1] if history_ids else None
    recent = set(history_ids[-window:]) if window > 0 else set()
    candidates = [t for t in enabled if t["id"] not in recent and t["id"] != last]
    if not candidates:
        candidates = [t for t in enabled if t["id"] != last]
    if not candidates:
        candidates = enabled
    weights = [float(t.get("weight", 1)) for t in candidates]
    return rng.choices(candidates, weights=weights, k=1)[0]


def vote_outcome(yes: int, no: int, eligible: int, closing: bool = False) -> str | None:
    """Result of a Superset vote among the other singers: "passed", "failed" or None (still open).

    A majority of the votes cast wins; ties fail. It ends early once the result can't change: more than
    half of everyone eligible said yes, at least half said no, or everyone has voted."""
    if yes * 2 > eligible:
        return "passed"
    if no * 2 >= eligible or closing or yes + no >= eligible:
        return "passed" if yes > no else "failed"
    return None


def roll_superset(chance: float, rng: random.Random) -> bool:
    return chance > 0 and rng.random() < chance


def set_order(guests: Sequence[dict], anchor_pos: int | None, include_anchor: bool) -> list[dict]:
    """Singers in a Superset set: once round the singer order, carrying on from the rotation.

    It starts after the singer at ``anchor_pos`` (or with them, when their song kicks the set off) and
    wraps to the top, so nobody sings twice in a row."""
    order = ordered_active(guests)
    if anchor_pos is None:
        return order
    first = [g for g in order if g["rotation_pos"] > anchor_pos or (include_anchor and g["rotation_pos"] == anchor_pos)]
    return first + [g for g in order if g not in first]


def song_name(title: str) -> str:
    """'Africa (Karaoke Version)' -> 'Africa': karaoke channels' extra words, for "Songs like …" themes."""
    name = re.sub(r"\s*[\(\[][^)\]]*(karaoke|instrumental|lyrics|version|backing)[^)\]]*[\)\]]", "", title,
                  flags=re.IGNORECASE)
    name = re.sub(r"\s*[-|–]\s*(karaoke|instrumental|lyrics).*$", "", name, flags=re.IGNORECASE).strip()
    return name or title.strip()


# --------------------------------------------------------------------------- last call

def closing_at(start: float, hhmm: str) -> float | None:
    """The first local HH:MM after ``start`` (so 01:30 for a night that started at 19:00 is the next day)."""
    if not hhmm:
        return None
    hour, minute = (int(x) for x in hhmm.split(":"))
    base = datetime.fromtimestamp(start).astimezone()
    close = base.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if close <= base:
        close += timedelta(days=1)
    return close.timestamp()


def clock_text(epoch: float) -> str:
    """11:30 p.m., the Canadian way."""
    t = datetime.fromtimestamp(epoch).astimezone()
    return f"{t.hour % 12 or 12}:{t.minute:02d} {'a.m.' if t.hour < 12 else 'p.m.'}"


def split_ideas(text: str | list | None) -> list[str]:
    """'Bon Jovi, a-ha,, Journey' -> ['Bon Jovi', 'a-ha', 'Journey'] (at most 8, each up to 40 characters)."""
    items = text if isinstance(text, list) else (text or "").split(",")
    clean = [clean_name(str(i))[:40] for i in items]
    return list(dict.fromkeys(i for i in clean if i))[:8]


def song_parts(title: str) -> list[str]:
    """Search ideas from a karaoke title: 'Toto - Africa (Karaoke)' gives ['Toto', 'Africa']."""
    parts = [p.strip() for p in re.split(r"\s+[-–|]\s+", song_name(title)) if p.strip()]
    return list(dict.fromkeys(parts))[:3]


# --------------------------------------------------------------------------- playlists

_STYLE_OF = re.compile(r"\s*[\(\[]\s*(?:in the style of|as made famous by|made famous by|originally (?:performed|sung) by|"
                       r"as performed by|performed by)\s+([^)\]]+)[\)\]]", re.IGNORECASE)
_NOISE = re.compile(r"\s*[\(\[][^)\]]*(?:lyrics?|hd|4k|official|sing ?along|no vocals|with vocals|"
                    r"guide vocals?|duet)[^)\]]*[\)\]]", re.IGNORECASE)


def playlist_song(title: str) -> str:
    """'Africa (In the Style of Toto) (Karaoke Version)' -> 'Toto - Africa': the original song to look for."""
    artist = None
    m = _STYLE_OF.search(title)
    if m:
        artist = m.group(1).strip()
        title = _STYLE_OF.sub("", title)
    name = _NOISE.sub("", song_name(title))
    parts = [p.strip() for p in re.split(r"\s+[|]\s+", name) if p.strip()]
    name = " - ".join(parts[:2]) if parts else name.strip()
    name = re.sub(r"\s+", " ", name).strip(" -|")
    if artist and artist.casefold() not in name.casefold():
        name = f"{artist} - {name}"
    return name or title.strip()


# --------------------------------------------------------------------------- misc

def normalise_query(q: str) -> str:
    q = unicodedata.normalize("NFKC", q).strip().lower()
    q = re.sub(r"\s+", " ", q)
    return q


def karaoke_query(q: str) -> str:
    q = normalise_query(q)
    return q if re.search(r"\bkaraoke\b", q) else f"{q} karaoke"


def clean_name(name: str) -> str:
    name = unicodedata.normalize("NFKC", name or "")
    name = "".join(ch for ch in name if ch.isprintable())
    return re.sub(r"\s+", " ", name).strip()
