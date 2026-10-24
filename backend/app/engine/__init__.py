"""Event engine: the single place where event state changes.

Every mutating method runs synchronously against SQLite and appends messages to ``self.outbox``; the
async layer drains the outbox and broadcasts over WebSockets.

Singers add songs whenever they like. The play order is a fair round-robin: each singer has at most
one song per round, and within a round songs follow the singer order. The engine is one class built
from a mixin per area (see the modules in this package); they share state only through ``self``.
"""
from __future__ import annotations

from .constants import (ACTIVE_QUEUE_STATUSES, COLOUR_SCHEMES, DEFAULT_SCHEME, JOIN_CODE_ALPHABET, REACTIONS,
                        SEED_THEMES, UNKNOWN_DURATION_S, VIDEO_COMMANDS, EngineError, hash_token)
from .core import EngineBase
from .events import EventsMixin
from .guests import GuestsMixin
from .history import HistoryMixin
from .lastcall import LastCallMixin
from .playback import PlaybackMixin
from .queue import QueueMixin
from .supersets import SupersetsMixin
from .themes import ThemesMixin
from .views import ViewsMixin


class Engine(EventsMixin, GuestsMixin, ThemesMixin, SupersetsMixin, QueueMixin, PlaybackMixin, LastCallMixin,
             HistoryMixin, ViewsMixin, EngineBase):
    """Everything an event can do. See each mixin's module for its part."""


__all__ = ["Engine", "EngineError", "hash_token", "ACTIVE_QUEUE_STATUSES", "COLOUR_SCHEMES", "DEFAULT_SCHEME",
           "JOIN_CODE_ALPHABET", "REACTIONS", "SEED_THEMES", "UNKNOWN_DURATION_S", "VIDEO_COMMANDS"]
