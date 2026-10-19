"""Pure, side-effect-free game logic: rotation, theme picking, superset rolls and queue ordering.

Everything here works on plain dicts so it can be unit tested without a database.
"""
from __future__ import annotations

import random
import re
import unicodedata
from typing import Iterable, Sequence

DEFAULT_EVENT_CONFIG: dict = {
    "turn_seconds": 90,
    "superset_chance": 0.15,
    "recent_theme_window": 3,
    "prevent_duplicates": True,
    "safe_search": "moderate",   # none | moderate | strict
    "max_duration_s": 900,       # 0 disables the limit
    "autoplay": True,
    "announce_seconds": 4,
    "spin_seconds": 5,
}

CONFIG_LIMITS: dict = {
    "turn_seconds": (15, 600),
    "superset_chance": (0.0, 1.0),
    "recent_theme_window": (0, 20),
    "max_duration_s": (0, 3600),
    "announce_seconds": (0, 15),
    "spin_seconds": (1, 15),
}


def merge_config(base: dict, overrides: dict | None) -> dict:
    """Merge overrides into a config, validating types and clamping to sane limits."""
    cfg = {**DEFAULT_EVENT_CONFIG, **(base or {})}
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


# --------------------------------------------------------------------------- rotation

def ordered_active(guests: Iterable[dict]) -> list[dict]:
    return sorted((g for g in guests if g.get("status", "active") == "active"),
                  key=lambda g: (g["rotation_pos"], g["id"]))


def next_in_rotation(guests: Sequence[dict], cursor_pos: int | None):
    """Pick the next singer after ``cursor_pos`` in fixed join order.

    Returns ``(guest | None, wrapped, skipped_ids)``. ``wrapped`` is True when the
    rotation passed the end of the order (i.e. a new round starts). Guests flagged
    ``skip_next`` are passed over once and reported in ``skipped_ids``.
    """
    order = ordered_active(guests)
    if not order:
        return None, False, []
    if cursor_pos is None:
        seq = [(g, True) for g in order]
    else:
        after = [(g, False) for g in order if g["rotation_pos"] > cursor_pos]
        before = [(g, True) for g in order if g["rotation_pos"] <= cursor_pos]
        seq = after + before
    skipped: list[int] = []
    for guest, wrapped in seq:
        if guest.get("skip_next"):
            skipped.append(guest["id"])
            continue
        return guest, wrapped, skipped
    # Everyone asked to be skipped: consume the skips and take the first in line anyway.
    guest, wrapped = seq[0]
    return guest, wrapped, skipped


def upcoming_order(guests: Sequence[dict], cursor_pos: int | None, exclude_id: int | None = None) -> list[int]:
    """Guest ids in the order they will sing after the current cursor."""
    order = ordered_active(guests)
    if cursor_pos is None:
        seq = order
    else:
        seq = [g for g in order if g["rotation_pos"] > cursor_pos] + \
              [g for g in order if g["rotation_pos"] <= cursor_pos]
    return [g["id"] for g in seq if g["id"] != exclude_id]


def next_rotation_pos(guests: Iterable[dict]) -> int:
    positions = [g["rotation_pos"] for g in guests]
    return (max(positions) + 1) if positions else 1


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


# --------------------------------------------------------------------------- queue

def play_order(items: Iterable[dict]) -> list[dict]:
    return sorted((i for i in items if i["status"] == "queued"), key=lambda i: (i["position"], i["id"]))


def append_position(items: Iterable[dict]) -> float:
    positions = [i["position"] for i in items]
    return (max(positions) + 1.0) if positions else 1.0


def move_item(ordered_ids: list[int], item_id: int, new_index: int) -> list[int]:
    if item_id not in ordered_ids:
        raise ValueError("Item is not in the queue")
    ids = [i for i in ordered_ids if i != item_id]
    new_index = max(0, min(new_index, len(ids)))
    ids.insert(new_index, item_id)
    return ids


def is_duplicate(items: Iterable[dict], video_id: str) -> bool:
    return any(i["video_id"] == video_id and i["status"] in ("queued", "playing", "played") for i in items)


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
