"""The uploaded banner image: one JPEG, PNG or WebP kept in ``<data>/banner/``."""
from __future__ import annotations

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
    def __init__(self, data_path: Path):
        self.dir = Path(data_path) / "banner"

    def save(self, data: bytes) -> str:
        if len(data) > MAX_BYTES:
            raise BannerError(f"That image is over {MAX_BYTES // 1_000_000} MB.", 413)
        ext = sniff(data)
        if not ext:
            raise BannerError("Upload a JPEG, PNG or WebP image.")
        self.dir.mkdir(parents=True, exist_ok=True)
        self.delete()
        tmp = self.dir / f"banner.{ext}.tmp"
        tmp.write_bytes(data)
        tmp.replace(self.dir / f"banner.{ext}")
        return ext

    def path(self, ext: str) -> Path | None:
        path = self.dir / f"banner.{ext}"
        return path if ext in TYPES and path.is_file() else None

    def delete(self) -> None:
        for ext in TYPES:
            (self.dir / f"banner.{ext}").unlink(missing_ok=True)
