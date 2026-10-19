"""WebSocket connection registry and broadcast."""
from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field

from fastapi import WebSocket

log = logging.getLogger("karaokequeue.ws")


@dataclass(eq=False)
class Client:
    ws: WebSocket
    role: str              # host | guest | screen
    guest_id: int | None = None
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)


class Hub:
    def __init__(self):
        self.rooms: dict[int, set[Client]] = {}

    def add(self, event_id: int, client: Client) -> None:
        self.rooms.setdefault(event_id, set()).add(client)

    def remove(self, event_id: int, client: Client) -> None:
        room = self.rooms.get(event_id)
        if room:
            room.discard(client)
            if not room:
                self.rooms.pop(event_id, None)

    def count(self, event_id: int) -> int:
        return len(self.rooms.get(event_id, ()))

    async def _send(self, event_id: int, client: Client, text: str) -> None:
        try:
            async with client.lock:
                await asyncio.wait_for(client.ws.send_text(text), timeout=5)
        except Exception:
            self.remove(event_id, client)

    async def send(self, event_id: int, message: dict, guest_id: int | None = None) -> None:
        text = json.dumps(message)
        targets = [c for c in list(self.rooms.get(event_id, ()))
                   if guest_id is None or c.guest_id == guest_id or c.role in ("host", "screen")]
        if guest_id is not None:
            # Personal messages go to the guest; host screens get them too, tagged.
            message = {**message, "for_guest_id": guest_id}
            text = json.dumps(message)
        await asyncio.gather(*(self._send(event_id, c, text) for c in targets))
