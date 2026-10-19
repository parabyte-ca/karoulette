"""SQLite persistence: schema, migrations and a small thread-safe helper."""
from __future__ import annotations

import json
import sqlite3
import threading
from pathlib import Path
from typing import Any, Iterable

SCHEMA_VERSION = 1

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

CREATE TABLE IF NOT EXISTS flags (
    queue_item_id INTEGER NOT NULL REFERENCES queue_items(id) ON DELETE CASCADE,
    flagged_by TEXT NOT NULL,
    created_at REAL NOT NULL,
    PRIMARY KEY (queue_item_id, flagged_by)
);

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

CREATE TABLE IF NOT EXISTS quota_ledger (
    day TEXT PRIMARY KEY,
    units_used INTEGER NOT NULL DEFAULT 0,
    exhausted INTEGER NOT NULL DEFAULT 0
);
"""


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
        self.conn.executescript(SCHEMA)
        self.execute(
            "INSERT OR IGNORE INTO settings(key, value) VALUES ('schema_version', ?)",
            (json.dumps(SCHEMA_VERSION),),
        )

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
