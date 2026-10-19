"""Tiny in-memory sliding-window rate limiter (single process is all we run)."""
from __future__ import annotations

import time
from collections import defaultdict, deque


class RateLimiter:
    def __init__(self, limit: int, window_s: float):
        self.limit = limit
        self.window = window_s
        self.hits: dict[str, deque] = defaultdict(deque)

    def allow(self, key: str, now: float | None = None) -> bool:
        now = time.monotonic() if now is None else now
        q = self.hits[key]
        while q and now - q[0] > self.window:
            q.popleft()
        if len(q) >= self.limit:
            return False
        q.append(now)
        if len(self.hits) > 5000:  # keep memory bounded
            for k in [k for k, v in self.hits.items() if not v]:
                del self.hits[k]
        return True

    def retry_after(self, key: str) -> int:
        q = self.hits.get(key)
        if not q:
            return 0
        return max(1, int(self.window - (time.monotonic() - q[0])) + 1)
