"""The uploaded banner image: one JPEG, PNG or WebP, stored in the database."""
from __future__ import annotations

import time
from pathlib import Path

MAX_BYTES = 8_000_000
TYPES = {"jpg": "image/jpeg", "png": "image/png", "webp": "image/webp"}


class BannerError(Exception):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.message = message
        self.status = status


def sniff(data: bytes) -> str | None:
    """The image type from its first bytes (never trust the file name or Content-Type)."""
    if data[:3] == b"\xff\xd8\xff":
        return "jpg"
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "png"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    return None


class BannerStore:
    """Kept in the database (the ``files`` table) so every backup and restore carries it."""
    NAME = "banner"

    def __init__(self, db, data_path: Path | None = None):
        self.db = db
        self.legacy_dir = Path(data_path) / "banner" if data_path else None

    def migrate(self) -> None:
        """Before v0.12.0 the banner was a file in <data>/banner/: copy it into the database if it isn't
        there. The file is left in place, so restoring an older backup can still find it."""
        if not self.legacy_dir or self._row():
            return
        for ext in TYPES:
            old = self.legacy_dir / f"banner.{ext}"
            if old.is_file():
                self.db.execute("INSERT OR REPLACE INTO files(name, mime, data, updated_at) VALUES (?, ?, ?, ?)",
                                (self.NAME, TYPES[ext], old.read_bytes(), time.time()))
                return

    def _row(self) -> dict | None:
        return self.db.one("SELECT data, mime FROM files WHERE name = ?", (self.NAME,))

    def save(self, data: bytes) -> str:
        if len(data) > MAX_BYTES:
            raise BannerError(f"That image is over {MAX_BYTES // 1_000_000} MB.", 413)
        ext = sniff(data)
        if not ext:
            raise BannerError("Upload a JPEG, PNG or WebP image.")
        self.db.execute("INSERT OR REPLACE INTO files(name, mime, data, updated_at) VALUES (?, ?, ?, ?)",
                        (self.NAME, TYPES[ext], data, time.time()))
        return ext

    def get(self) -> tuple[bytes, str] | None:
        if not self._row():
            self.migrate()  # e.g. a backup from before v0.12.0 was just restored
        row = self._row()
        return (bytes(row["data"]), row["mime"]) if row else None

    def delete(self) -> None:
        self.db.execute("DELETE FROM files WHERE name = ?", (self.NAME,))
        if self.legacy_dir:  # and any old file, or it would come back
            for ext in TYPES:
                (self.legacy_dir / f"banner.{ext}").unlink(missing_ok=True)
