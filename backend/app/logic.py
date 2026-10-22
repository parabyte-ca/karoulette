"""Pure, side-effect-free game logic: singer order, fair queue order, theme picking and superset rolls.

Everything here works on plain dicts so it can be unit tested without a database.
"""
from __future__ import annotations

import random
import re
import unicodedata
from typing import Iterable, Sequence

DEFAULT_EVENT_CONFIG: dict = {
    "superset_chance": 0.15,
    "recent_theme_window": 3,
    "prevent_duplicates": True,
    "safe_search": "moderate",   # none | moderate | strict
    "max_duration_s": 900,       # 0 disables the limit
    "autoplay": True,
    "spin_seconds": 5,
}

CONFIG_LIMITS: dict = {
    "superset_chance": (0.0, 1.0),
    "recent_theme_window": (0, 20),
    "max_duration_s": (0, 3600),
    "spin_seconds": (1, 15),
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
    return cfg


# --------------------------------------------------------------------------- singer order

def ordered_active(guests: Iterable[dict]) -> list[dict]:
    return sorted((g for g in guests if g.get("status", "active") == "active"),
                  key=lambda g: (g["rotation_pos"], g["id"]))


def next_rotation_pos(guests: Iterable[dict]) -> int:
    positions = [g["rotation_pos"] for g in guests]
    return (max(positions) + 1) if positions else 1


def newcomer_position(guests: Sequence[dict], anchor_pos: int | None, newcomer_id: int | None = None) -> int | None:
    """Where a new singer goes: right after the singer on the mic (``anchor_pos``), behind any other
    newcomers still waiting for their first song. ``None`` means "append to the end" (nobody has sung
    in this round yet, so join order applies)."""
    if anchor_pos is None:
        return None
    pos = anchor_pos + 1
    waiting = {g["rotation_pos"] for g in ordered_active(guests)
               if g.get("debut_pending") and g["id"] != newcomer_id}
    while pos in waiting:
        pos += 1
    return pos


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


def roll_superset(chance: float, pending: str | None, rng: random.Random) -> bool:
    if pending == "force":
        return True
    if pending == "cancel":
        return False
    return rng.random() < chance


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
