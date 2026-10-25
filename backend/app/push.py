"""Web Push: alerts that reach a phone even when Karoulette isn't open (or the screen is locked).

The server signs each push with its own VAPID key (made on first start and kept in the database, so
backups carry it and phones stay subscribed after a restore) and encrypts the message for that phone
(RFC 8291, aes128gcm). The phone's browser service (Google, Apple, Mozilla) delivers it.
"""
from __future__ import annotations

import base64
import json
import logging
import os
import time
from urllib.parse import urlparse

import http_ece
import httpx
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from py_vapid import Vapid02

from .db import Database

log = logging.getLogger("karoulette.push")
TTL_S = 15 * 60  # an "up next" from more than 15 minutes ago isn't worth delivering


def b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def unb64url(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


class PushService:
    def __init__(self, db: Database, subject: str = "", client: httpx.AsyncClient | None = None):
        self.db = db
        self.subject = subject or "mailto:karoulette@example.com"
        self.client = client or httpx.AsyncClient(timeout=10.0)
        self.load_key()

    def load_key(self) -> None:
        """The key from the database (again after a restore), or a new one."""
        pem = self.db.get_setting("vapid_private_pem")
        if pem:
            self.vapid = Vapid02.from_pem(pem.encode())
        else:
            self.vapid = Vapid02()
            self.vapid.generate_keys()
            self.db.set_setting("vapid_private_pem", self.vapid.private_pem().decode())

    @property
    def public_key(self) -> str:
        """The applicationServerKey phones subscribe with (uncompressed P-256 point, base64url)."""
        raw = self.vapid.public_key.public_bytes(serialization.Encoding.X962,
                                                 serialization.PublicFormat.UncompressedPoint)
        return b64url(raw)

    def encrypt(self, sub: dict, payload: dict) -> bytes:
        return http_ece.encrypt(json.dumps(payload).encode(), salt=os.urandom(16),
                                private_key=ec.generate_private_key(ec.SECP256R1()),
                                dh=unb64url(sub["p256dh"]), auth_secret=unb64url(sub["auth"]), version="aes128gcm")

    async def send(self, sub: dict, payload: dict) -> int:
        """Deliver one push; a subscription the service says is gone (404/410) is forgotten."""
        endpoint = urlparse(sub["endpoint"])
        claims = {"sub": self.subject, "aud": f"{endpoint.scheme}://{endpoint.netloc}", "exp": int(time.time()) + 12 * 3600}
        headers = {**self.vapid.sign(claims), "Content-Encoding": "aes128gcm", "TTL": str(TTL_S),
                   "Urgency": "high", "Content-Type": "application/octet-stream"}
        try:
            body = self.encrypt(sub, payload)
        except Exception:  # keys that can't be right will never work
            log.warning("Dropping a push subscription with unusable keys (%s)", endpoint.netloc)
            self.db.execute("DELETE FROM push_subscriptions WHERE endpoint = ?", (sub["endpoint"],))
            return 0
        try:
            res = await self.client.post(sub["endpoint"], content=body, headers=headers)
        except httpx.HTTPError as exc:
            log.warning("Push to %s failed: %s", endpoint.netloc, type(exc).__name__)
            return 0
        if res.status_code in (404, 410):
            self.db.execute("DELETE FROM push_subscriptions WHERE endpoint = ?", (sub["endpoint"],))
        elif res.status_code >= 400:
            log.warning("Push to %s refused: HTTP %s", endpoint.netloc, res.status_code)
        return res.status_code

    async def aclose(self) -> None:
        await self.client.aclose()
