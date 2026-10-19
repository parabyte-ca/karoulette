"""Host PIN handling and signed session cookies."""
from __future__ import annotations

import hashlib
import hmac
import logging
import secrets
import time

from .db import Database

log = logging.getLogger("karaokequeue.auth")

COOKIE_NAME = "kq_host"
SESSION_SECONDS = 24 * 3600
_ITERATIONS = 200_000


def hash_pin(pin: str, salt: str | None = None) -> str:
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", pin.encode(), salt.encode(), _ITERATIONS).hex()
    return f"pbkdf2${salt}${digest}"


def verify_pin(pin: str, stored: str) -> bool:
    try:
        _, salt, _digest = stored.split("$")
    except ValueError:
        return False
    return hmac.compare_digest(hash_pin(pin, salt), stored)


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
        return
    db.set_setting("host_pin_from_env", False)
    if not db.get_setting("host_pin_hash"):
        pin = f"{secrets.randbelow(10**6):06d}"
        db.set_setting("host_pin_hash", hash_pin(pin))
        log.warning("=" * 60)
        log.warning("No HOST_PIN set. Generated host PIN: %s", pin)
        log.warning("Set HOST_PIN in .env or change it in Host admin.")
        log.warning("=" * 60)


def make_session(secret: str) -> str:
    expiry = str(int(time.time()) + SESSION_SECONDS)
    sig = hmac.new(secret.encode(), f"host:{expiry}".encode(), hashlib.sha256).hexdigest()
    return f"{expiry}.{sig}"


def check_session(secret: str, value: str | None) -> bool:
    if not value or "." not in value:
        return False
    expiry, sig = value.split(".", 1)
    if not expiry.isdigit() or int(expiry) < time.time():
        return False
    expected = hmac.new(secret.encode(), f"host:{expiry}".encode(), hashlib.sha256).hexdigest()
    return hmac.compare_digest(sig, expected)
