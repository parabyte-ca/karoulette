"""Host PIN handling and signed session cookies."""
from __future__ import annotations

import hashlib
import hmac
import logging
import secrets
import time
from pathlib import Path

from .db import Database

log = logging.getLogger("karoulette.auth")

COOKIE_NAME = "kq_host"
SESSION_SECONDS = 24 * 3600
ITERATIONS = 600_000  # OWASP's figure for PBKDF2-HMAC-SHA256
_LEGACY_ITERATIONS = 200_000  # hashes stored as pbkdf2$salt$digest before v0.16


def _digest(pin: str, salt: str, iterations: int) -> str:
    return hashlib.pbkdf2_hmac("sha256", pin.encode(), salt.encode(), iterations).hex()


def hash_pin(pin: str, salt: str | None = None) -> str:
    salt = salt or secrets.token_hex(16)
    return f"pbkdf2${ITERATIONS}${salt}${_digest(pin, salt, ITERATIONS)}"


def verify_pin(pin: str, stored: str) -> bool:
    parts = (stored or "").split("$")
    if len(parts) == 3:  # legacy: pbkdf2$salt$digest
        _, salt, digest = parts
        iterations = _LEGACY_ITERATIONS
    elif len(parts) == 4 and parts[1].isdigit():
        _, iterations_s, salt, digest = parts
        iterations = int(iterations_s)
    else:
        return False
    return hmac.compare_digest(_digest(pin, salt, iterations), digest)


def needs_rehash(stored: str) -> bool:
    parts = (stored or "").split("$")
    return len(parts) != 4 or parts[1] != str(ITERATIONS)


def validate_pin(pin: str) -> str:
    pin = (pin or "").strip()
    if not 4 <= len(pin) <= 64:
        raise ValueError("The PIN or password must be 4 to 64 characters")
    return pin


def init_pin(db: Database, env_pin: str) -> None:
    """HOST_PIN from the environment always wins; otherwise keep the stored one or generate one."""
    if env_pin:
        stored = db.get_setting("host_pin_hash")
        if not stored or not verify_pin(env_pin, stored):
            db.set_setting("host_pin_hash", hash_pin(validate_pin(env_pin)))
        db.set_setting("host_pin_from_env", True)
        if len(env_pin.strip()) < 8:
            log.warning("HOST_PIN is shorter than 8 characters. Use a longer PIN or a passphrase if Karoulette "
                        "is reachable from the internet.")
        return
    db.set_setting("host_pin_from_env", False)
    if not db.get_setting("host_pin_hash"):
        pin = f"{secrets.randbelow(10**6):06d}"
        db.set_setting("host_pin_hash", hash_pin(pin))
        log.warning("=" * 60)
        pin_file = Path(db.path).parent / "generated-host-pin.txt" if db.path != ":memory:" else None
        if pin_file:
            pin_file.write_text(pin + "\n")
            pin_file.chmod(0o600)
            log.warning("No HOST_PIN set. A host PIN was generated and saved to %s", pin_file)
        else:
            log.warning("No HOST_PIN set. Generated host PIN: %s", pin)
        log.warning("Set HOST_PIN in .env or change it in Host admin, then delete that file.")
        log.warning("=" * 60)


def make_session(secret: str, epoch: int = 0) -> str:
    """A signed host session. ``epoch`` goes up when the PIN changes, which signs every old session out."""
    expiry = str(int(time.time()) + SESSION_SECONDS)
    sig = hmac.new(secret.encode(), f"host:{epoch}:{expiry}".encode(), hashlib.sha256).hexdigest()
    return f"{expiry}.{sig}"


def check_session(secret: str, value: str | None, epoch: int = 0) -> bool:
    if not value or "." not in value:
        return False
    expiry, sig = value.split(".", 1)
    if not expiry.isdigit() or int(expiry) < time.time():
        return False
    expected = hmac.new(secret.encode(), f"host:{epoch}:{expiry}".encode(), hashlib.sha256).hexdigest()
    return hmac.compare_digest(sig, expected)
