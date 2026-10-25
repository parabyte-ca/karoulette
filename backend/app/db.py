"""SQLite persistence: schema, migrations and a small thread-safe helper."""
from __future__ import annotations

import json
import sqlite3
import threading
from pathlib import Path
from typing import Any, Iterable

SCHEMA_VERSION = 4

SCHEMA = """
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    join_code TEXT NOT NULL UNIQUE,
    status TEXT NOT NULL DEFAULT 'draft',          -- draft | active | ended
    config TEXT NOT NULL DEFAULT '{}',
    created_at REAL NOT NULL,
    started_at REAL,
    ended_at REAL,
    current_round INTEGER NOT NULL DEFAULT 0,
    current_round_id INTEGER,
    cursor_pos INTEGER,                            -- rotation_pos of the last regular turn
    current_turn_id INTEGER,
    turn_state TEXT NOT NULL DEFAULT 'idle',       -- idle | announcing | spinning | choosing
    phase_deadline REAL,
    paused_remaining REAL,
    rotation_paused INTEGER NOT NULL DEFAULT 0,
    superset_pending TEXT,                         -- NULL | force | cancel
    bonus_queue TEXT NOT NULL DEFAULT '[]',        -- [{guest_id, theme_id}]
    now_playing_item_id INTEGER
);

CREATE TABLE IF NOT EXISTS guests (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id INTEGER NOT NULL REFERENCES events(id) ON DELETE CASCADE,
    display_name TEXT NOT NULL,
    token_hash TEXT NOT NULL UNIQUE,
    rotation_pos INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'active',         -- active | left | removed
    skip_next INTEGER NOT NULL DEFAULT 0,
    joined_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_guests_event ON guests(event_id, rotation_pos);

CREATE TABLE IF NOT EXISTS themes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    description TEXT NOT NULL DEFAULT '',
    weight REAL NOT NULL DEFAULT 1,
    enabled INTEGER NOT NULL DEFAULT 1,
    created_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS rounds (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id INTEGER NOT NULL REFERENCES events(id) ON DELETE CASCADE,
    number INTEGER NOT NULL,
    is_superset INTEGER NOT NULL DEFAULT 0,
    superset_theme_id INTEGER REFERENCES themes(id) ON DELETE SET NULL,
    started_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_rounds_event ON rounds(event_id, number);

CREATE TABLE IF NOT EXISTS turns (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id INTEGER NOT NULL REFERENCES events(id) ON DELETE CASCADE,
    round_id INTEGER REFERENCES rounds(id) ON DELETE SET NULL,
    guest_id INTEGER NOT NULL REFERENCES guests(id) ON DELETE CASCADE,
    theme_id INTEGER REFERENCES themes(id) ON DELETE SET NULL,
    theme_name TEXT,
    is_bonus INTEGER NOT NULL DEFAULT 0,
    outcome TEXT,                                  -- NULL (open) | queued | timeout | skipped | removed | left
    started_at REAL NOT NULL,
    ended_at REAL
);
CREATE INDEX IF NOT EXISTS ix_turns_event ON turns(event_id, id);

CREATE TABLE IF NOT EXISTS queue_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id INTEGER NOT NULL REFERENCES events(id) ON DELETE CASCADE,
    guest_id INTEGER NOT NULL REFERENCES guests(id) ON DELETE CASCADE,
    turn_id INTEGER REFERENCES turns(id) ON DELETE SET NULL,
    round_id INTEGER REFERENCES rounds(id) ON DELETE SET NULL,
    theme_name TEXT,
    is_superset INTEGER NOT NULL DEFAULT 0,
    video_id TEXT NOT NULL,
    title TEXT NOT NULL,
    channel TEXT NOT NULL DEFAULT '',
    duration_s INTEGER,
    thumbnail TEXT NOT NULL DEFAULT '',
    position REAL NOT NULL,
    status TEXT NOT NULL DEFAULT 'queued',         -- queued | playing | played | skipped | removed | error
    error_code INTEGER,
    added_at REAL NOT NULL,
    played_at REAL
);
CREATE INDEX IF NOT EXISTS ix_queue_event ON queue_items(event_id, status, position);
CREATE INDEX IF NOT EXISTS ix_queue_guest ON queue_items(guest_id, status);

CREATE TABLE IF NOT EXISTS flags (
    queue_item_id INTEGER NOT NULL REFERENCES queue_items(id) ON DELETE CASCADE,
    flagged_by TEXT NOT NULL,
    created_at REAL NOT NULL,
    PRIMARY KEY (queue_item_id, flagged_by)
);

CREATE TABLE IF NOT EXISTS superset_votes (           -- a guest calls a Superset for the current round
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id INTEGER NOT NULL REFERENCES events(id) ON DELETE CASCADE,
    round_id INTEGER REFERENCES rounds(id) ON DELETE CASCADE,
    called_by INTEGER REFERENCES guests(id) ON DELETE SET NULL,
    status TEXT NOT NULL DEFAULT 'open',          -- open | passed | failed | cancelled
    mode TEXT NOT NULL DEFAULT 'after',           -- now (the song playing starts the set) | after
    item_id INTEGER,                              -- the song playing when it was called
    started_at REAL NOT NULL,
    ends_at REAL NOT NULL,
    closed_at REAL
);
CREATE INDEX IF NOT EXISTS ix_votes_event ON superset_votes(event_id, status);

CREATE TABLE IF NOT EXISTS superset_ballots (
    vote_id INTEGER NOT NULL REFERENCES superset_votes(id) ON DELETE CASCADE,
    guest_id INTEGER NOT NULL REFERENCES guests(id) ON DELETE CASCADE,
    yes INTEGER NOT NULL,
    PRIMARY KEY (vote_id, guest_id)
);

-- A Superset set: one extra song per singer, in singer order, on one theme. Then the queue carries on.
CREATE TABLE IF NOT EXISTS superset_sets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id INTEGER NOT NULL REFERENCES events(id) ON DELETE CASCADE,
    round_no INTEGER NOT NULL DEFAULT 0,          -- round it was declared in (random rolls: the round it opens)
    source TEXT NOT NULL,                         -- vote | host | random
    mode TEXT NOT NULL,                           -- now | after
    theme_id INTEGER REFERENCES themes(id) ON DELETE SET NULL,
    theme_name TEXT NOT NULL,
    inspired_by TEXT,                             -- "Title" of the song that kicked it off ("start now")
    spun_at REAL,                                 -- set when the theme was spun from the list
    status TEXT NOT NULL DEFAULT 'active',        -- active | done | cancelled
    started_at REAL NOT NULL,
    ended_at REAL
);
CREATE INDEX IF NOT EXISTS ix_sets_event ON superset_sets(event_id, status);

CREATE TABLE IF NOT EXISTS superset_slots (
    set_id INTEGER NOT NULL REFERENCES superset_sets(id) ON DELETE CASCADE,
    guest_id INTEGER NOT NULL REFERENCES guests(id) ON DELETE CASCADE,
    position INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',       -- pending | picked | sung | passed | skipped
    item_id INTEGER REFERENCES queue_items(id) ON DELETE SET NULL,
    PRIMARY KEY (set_id, guest_id)
);
CREATE INDEX IF NOT EXISTS ix_slots_item ON superset_slots(item_id);

CREATE TABLE IF NOT EXISTS search_cache (
    query_key TEXT PRIMARY KEY,
    results TEXT NOT NULL,
    source TEXT NOT NULL,
    fetched_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS video_cache (
    video_id TEXT PRIMARY KEY,
    data TEXT NOT NULL,
    fetched_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS song_originals (            -- the original recording of a sung song, for playlists
    song_key TEXT PRIMARY KEY,                     -- playlist_song(), case-folded
    video_id TEXT,                                 -- NULL: looked for and not found
    source TEXT NOT NULL,                          -- ytdlp | api
    found_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS event_log (                -- the timeline: who did what during an event
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id INTEGER NOT NULL REFERENCES events(id) ON DELETE CASCADE,
    at REAL NOT NULL,
    kind TEXT NOT NULL,                            -- event | settings | singers | songs | playback | superset
    actor_type TEXT NOT NULL,                      -- host | guest | system
    actor_id INTEGER,                              -- the guest, when a guest did it
    actor_name TEXT NOT NULL,
    text TEXT NOT NULL,
    data TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS ix_event_log ON event_log(event_id, at);

CREATE TABLE IF NOT EXISTS files (                    -- small uploads kept in the database (so backups carry them)
    name TEXT PRIMARY KEY,
    mime TEXT NOT NULL,
    data BLOB NOT NULL,
    updated_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS quota_ledger (
    day TEXT PRIMARY KEY,
    units_used INTEGER NOT NULL DEFAULT 0,
    exhausted INTEGER NOT NULL DEFAULT 0
);
"""


# Columns added after the first release (v0.6.0: free song submission with a fair round-robin queue;
# v0.7.0: get-ready countdown, duets, rejoin codes, Superset sets and the smoke-break pause).
ADDED_COLUMNS = [
    ("queue_items", "round_no", "INTEGER"),            # rotation round this song belongs to
    ("queue_items", "priority", "REAL"),               # non-NULL = plays before the round-robin, ascending
    ("queue_items", "order_bias", "REAL NOT NULL DEFAULT 0"),  # a singer stepping back one place
    ("rounds", "theme_id", "INTEGER"),
    ("rounds", "theme_name", "TEXT"),
    ("rounds", "spun_at", "REAL"),
    ("guests", "debut_pending", "INTEGER NOT NULL DEFAULT 0"),  # joined mid-event, first song not sung yet
    ("guests", "repick_credit", "INTEGER NOT NULL DEFAULT 0"),  # their last song couldn't play
    # v0.7.0
    ("events", "ready_until", "REAL"),                 # the TV's "Get ready" countdown ends at this time
    ("events", "paused", "INTEGER NOT NULL DEFAULT 0"),  # "Smoke break!": the queue is on hold
    ("queue_items", "set_id", "INTEGER"),              # a Superset song (outside the regular queue)
    ("superset_votes", "mode", "TEXT NOT NULL DEFAULT 'after'"),
    ("superset_votes", "item_id", "INTEGER"),
    # v0.8.0
    ("queue_items", "cheers", "INTEGER NOT NULL DEFAULT 0"),  # reactions sent while it played
    ("themes", "ideas", "TEXT NOT NULL DEFAULT ''"),          # comma-separated search ideas for phones
    ("events", "last_call_announced", "INTEGER NOT NULL DEFAULT 0"),
    ("queue_items", "duet_guest_id", "INTEGER"),       # second singer on a duet
    ("guests", "rejoin_code", "TEXT"),                 # lets a singer get back in on another phone
    # v0.12.0
    ("events", "archived_at", "REAL"),                 # hidden from the lists, kept in the song history
]


class Database:
    """Single shared connection guarded by a lock. SQLite is fast enough for one venue."""

    def __init__(self, path: Path | str):
        self.path = str(path)
        self._lock = threading.RLock()
        self.conn = sqlite3.connect(self.path, check_same_thread=False, isolation_level=None)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        if self.path != ":memory:":
            self.conn.execute("PRAGMA journal_mode = WAL")
        self.migrate()
        self.execute(
            "INSERT OR IGNORE INTO settings(key, value) VALUES ('schema_version', ?)",
            (json.dumps(SCHEMA_VERSION),),
        )

    def migrate(self) -> None:
        """Create anything missing: run at start-up and after restoring an older backup."""
        with self._lock:
            self.conn.executescript(SCHEMA)
            self._add_missing_columns()

    def _add_missing_columns(self) -> None:
        """Bring databases created by older versions up to date (SQLite only needs ADD COLUMN here)."""
        for table, column, ddl in ADDED_COLUMNS:
            have = {r["name"] for r in self.conn.execute(f"PRAGMA table_info({table})").fetchall()}
            if column not in have:
                self.conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")
        self.conn.execute("INSERT INTO settings(key, value) VALUES ('schema_version', ?) "
                          "ON CONFLICT(key) DO UPDATE SET value = excluded.value", (json.dumps(SCHEMA_VERSION),))

    def execute(self, sql: str, params: Iterable[Any] = ()) -> sqlite3.Cursor:
        with self._lock:
            return self.conn.execute(sql, tuple(params))

    def all(self, sql: str, params: Iterable[Any] = ()) -> list[dict]:
        with self._lock:
            return [dict(r) for r in self.conn.execute(sql, tuple(params)).fetchall()]

    def one(self, sql: str, params: Iterable[Any] = ()) -> dict | None:
        with self._lock:
            row = self.conn.execute(sql, tuple(params)).fetchone()
            return dict(row) if row else None

    def insert(self, sql: str, params: Iterable[Any] = ()) -> int:
        with self._lock:
            return self.conn.execute(sql, tuple(params)).lastrowid

    def transaction(self):
        return _Tx(self)

    # settings helpers
    def get_setting(self, key: str, default: Any = None) -> Any:
        row = self.one("SELECT value FROM settings WHERE key = ?", (key,))
        return json.loads(row["value"]) if row else default

    def set_setting(self, key: str, value: Any) -> None:
        self.execute(
            "INSERT INTO settings(key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, json.dumps(value)),
        )

    def close(self) -> None:
        with self._lock:
            self.conn.close()


class _Tx:
    def __init__(self, db: Database):
        self.db = db

    def __enter__(self):
        self.db._lock.acquire()
        self.db.conn.execute("BEGIN")
        return self.db

    def __exit__(self, exc_type, exc, tb):
        try:
            self.db.conn.execute("ROLLBACK" if exc_type else "COMMIT")
        finally:
            self.db._lock.release()
        return False
