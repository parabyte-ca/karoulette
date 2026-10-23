"""Database backups: make, list, download and restore them from Host admin.

Backups live in ``<data>/backups`` next to the ones ``update.sh`` makes before every upgrade. They're
made with SQLite's online backup, so they're consistent even mid-event. Restoring first saves a
``pre-restore`` backup of the current database, then copies the chosen one over it in place (no
restart needed) and brings it up to date.
"""
from __future__ import annotations

import re
import sqlite3
import time
from pathlib import Path

from .db import Database

KEEP = 10                                        # per kind: manual-, pre-restore-, uploaded-
NAME_RE = re.compile(r"^[A-Za-z0-9._-]{1,120}\.db$")
REQUIRED_TABLES = {"settings", "events", "guests", "queue_items", "themes"}


class BackupError(Exception):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.message = message
        self.status = status


class Backups:
    def __init__(self, db: Database, data_path: Path, version: str):
        self.db = db
        self.dir = Path(data_path) / "backups"
        self.version = version

    def _path(self, name: str) -> Path:
        if not NAME_RE.match(name or ""):
            raise BackupError("That isn't a backup file name.")
        path = self.dir / name
        if not path.is_file():
            raise BackupError("Backup not found.", 404)
        return path

    def list(self) -> list[dict]:
        if not self.dir.is_dir():
            return []
        files = [p for p in self.dir.glob("*.db") if p.is_file() and NAME_RE.match(p.name)]
        files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
        return [{"name": p.name, "size": p.stat().st_size, "created_at": p.stat().st_mtime,
                 "kind": p.name.split("-")[0] if "-" in p.name else "other"} for p in files]

    def create(self, kind: str = "manual") -> dict:
        self.dir.mkdir(parents=True, exist_ok=True)
        name = f"{kind}-{self.version}-{time.strftime('%Y%m%d-%H%M%S')}.db"
        dest = self.dir / name
        n = 1
        while dest.exists():  # two in the same second
            dest = self.dir / name.replace(".db", f"-{n}.db")
            n += 1
        out = sqlite3.connect(dest)
        try:
            with self.db._lock:
                self.db.conn.backup(out)
        finally:
            out.close()
        self._prune(kind)
        return next(b for b in self.list() if b["name"] == dest.name)

    def _prune(self, kind: str) -> None:
        mine = sorted(self.dir.glob(f"{kind}-*.db"), key=lambda p: p.stat().st_mtime)
        for old in mine[:-KEEP]:
            old.unlink(missing_ok=True)

    def path(self, name: str) -> Path:
        return self._path(name)

    def delete(self, name: str) -> None:
        self._path(name).unlink()

    @staticmethod
    def validate(path: Path) -> None:
        """A readable, intact Karoulette database, or BackupError."""
        try:
            con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
            try:
                if con.execute("PRAGMA quick_check").fetchone()[0] != "ok":
                    raise BackupError("That backup is damaged (SQLite's integrity check failed).")
                tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
            finally:
                con.close()
        except sqlite3.DatabaseError as exc:
            raise BackupError(f"That isn't a Karoulette database ({exc}).") from exc
        missing = REQUIRED_TABLES - tables
        if missing:
            raise BackupError("That isn't a Karoulette database (missing " + ", ".join(sorted(missing)) + ").")

    def restore(self, name: str) -> dict:
        """Replace the live database with a backup. The current one is saved first."""
        src_path = self._path(name)
        self.validate(src_path)
        safety = self.create("pre-restore")
        src = sqlite3.connect(f"file:{src_path}?mode=ro", uri=True)
        try:
            with self.db._lock:
                src.backup(self.db.conn)
        finally:
            src.close()
        self.db.migrate()  # an older backup gets this version's tables and columns
        return {"restored": name, "safety_backup": safety["name"]}

    def save_upload(self, chunks: list[bytes]) -> str:
        self.dir.mkdir(parents=True, exist_ok=True)
        name = f"uploaded-{time.strftime('%Y%m%d-%H%M%S')}.db"
        path = self.dir / name
        path.write_bytes(b"".join(chunks))
        try:
            self.validate(path)
        except BackupError:
            path.unlink(missing_ok=True)
            raise
        self._prune("uploaded")
        return name
