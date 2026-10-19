"""Runtime configuration, read from environment variables."""
from __future__ import annotations

import os
import re
import secrets
from dataclasses import dataclass, field
from pathlib import Path


def _read_version() -> str:
    for candidate in (Path(__file__).resolve().parents[2] / "VERSION", Path("/app/VERSION")):
        if candidate.exists():
            return candidate.read_text().strip()
    return "0.0.0"


def normalise_base_url(value: str) -> str:
    """Keep only the site root: people often paste the join or host page URL here."""
    value = (value or "").strip().rstrip("/")
    while True:
        trimmed = re.sub(r"/(join|host)(/[A-Za-z0-9]*)?$", "", value, flags=re.IGNORECASE).rstrip("/")
        if trimmed == value:
            return value
        value = trimmed


@dataclass
class Settings:
    data_path: Path = field(default_factory=lambda: Path(os.getenv("DATA_PATH", "/data")))
    youtube_api_key: str = field(default_factory=lambda: os.getenv("YOUTUBE_API_KEY", "").strip())
    youtube_daily_quota: int = field(default_factory=lambda: int(os.getenv("YOUTUBE_DAILY_QUOTA", "10000")))
    host_pin: str = field(default_factory=lambda: os.getenv("HOST_PIN", "").strip())
    public_base_url: str = field(default_factory=lambda: normalise_base_url(os.getenv("PUBLIC_BASE_URL", "")))
    secret_key: str = field(default_factory=lambda: os.getenv("SECRET_KEY", "").strip())
    static_dir: Path = field(default_factory=lambda: Path(os.getenv("STATIC_DIR", "/app/static")))
    source_repo: str = field(default_factory=lambda: os.getenv("SOURCE_REPO", "parabyte-ca/karoulette").strip())
    update_check: bool = field(default_factory=lambda: os.getenv("UPDATE_CHECK", "true").lower() != "false")
    upgrade_dir: str = field(default_factory=lambda: os.getenv("UPGRADE_DIR", "").strip())
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
