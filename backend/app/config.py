"""Runtime configuration, read from environment variables."""
from __future__ import annotations

import os
import secrets
from dataclasses import dataclass, field
from pathlib import Path


def _read_version() -> str:
    for candidate in (Path(__file__).resolve().parents[2] / "VERSION", Path("/app/VERSION")):
        if candidate.exists():
            return candidate.read_text().strip()
    return "0.0.0"


@dataclass
class Settings:
    data_path: Path = field(default_factory=lambda: Path(os.getenv("DATA_PATH", "/data")))
    youtube_api_key: str = field(default_factory=lambda: os.getenv("YOUTUBE_API_KEY", "").strip())
    youtube_daily_quota: int = field(default_factory=lambda: int(os.getenv("YOUTUBE_DAILY_QUOTA", "10000")))
    host_pin: str = field(default_factory=lambda: os.getenv("HOST_PIN", "").strip())
    public_base_url: str = field(default_factory=lambda: os.getenv("PUBLIC_BASE_URL", "").rstrip("/"))
    secret_key: str = field(default_factory=lambda: os.getenv("SECRET_KEY", "").strip())
    static_dir: Path = field(default_factory=lambda: Path(os.getenv("STATIC_DIR", "/app/static")))
    enable_ytdlp: bool = field(default_factory=lambda: os.getenv("ENABLE_YTDLP", "true").lower() != "false")
    version: str = field(default_factory=_read_version)

    @property
    def db_path(self) -> Path:
        return self.data_path / "karaokequeue.db"

    def ensure(self) -> None:
        self.data_path.mkdir(parents=True, exist_ok=True)
        if not self.secret_key:
            key_file = self.data_path / "secret.key"
            if not key_file.exists():
                key_file.write_text(secrets.token_urlsafe(48))
                key_file.chmod(0o600)
            self.secret_key = key_file.read_text().strip()
