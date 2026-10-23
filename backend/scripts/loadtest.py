"""Load test: a busy party against a running Karoulette server.

Thirty phones join, open their live connections, queue songs and cheer all at once while the host
skips songs. Reports request times and how long a change takes to reach every phone, and exits with an
error if they're slower than the limits (so CI catches slowdowns).

    python -m scripts.loadtest --base http://127.0.0.1:8095 --pin 1234

Run it against a test server (it creates an event called "Load test"). The server should have no
YouTube key and ENABLE_YTDLP=false so queued videos are accepted without lookups.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import sys
import time

import httpx
import websockets


class Phone:
    """One guest: an HTTP client plus a live connection counting the state updates it receives."""

    def __init__(self, base: str, n: int):
        self.n = n
        self.http = httpx.AsyncClient(base_url=base, timeout=30,
                                      headers={"X-Forwarded-For": f"10.0.{n // 250}.{n % 250 + 1}"})
        self.token = ""
        self.states = 0
        self.latest: dict = {}
        self.changed = asyncio.Event()
        self.watch_for = None

    async def listen(self, ws_url: str, ready: asyncio.Event) -> None:
        async with websockets.connect(f"{ws_url}?token={self.token}", max_size=None) as ws:
            ready.set()
            async for raw in ws:
                msg = json.loads(raw)
                if msg.get("type") == "state":
                    self.states += 1
                    self.latest = msg["data"]
                    playing = (self.latest.get("now_playing") or {}).get("id")
                    if self.watch_for is not None and playing != self.watch_for:
                        self.changed.set()


async def timed(times: dict, name: str, coro):
    start = time.perf_counter()
    res = await coro
    times.setdefault(name, []).append((time.perf_counter() - start) * 1000)
    if res.status_code >= 400:
        raise RuntimeError(f"{name} failed: {res.status_code} {res.text[:200]}")
    return res


def summary(values: list[float]) -> str:
    values = sorted(values)
    p95 = values[min(len(values) - 1, int(len(values) * 0.95))]
    return f"n={len(values):4d}  p50={statistics.median(values):7.1f} ms  p95={p95:7.1f} ms  max={values[-1]:7.1f} ms"


async def run(args) -> int:
    base = args.base.rstrip("/")
    ws_base = base.replace("http", "ws", 1)
    host = httpx.AsyncClient(base_url=base, timeout=30)
    (await host.post("/api/host/login", json={"pin": args.pin})).raise_for_status()
    ev = (await host.post("/api/host/events", json={"name": "Load test", "config": {
        "autoplay": True, "ready_seconds": 0, "prevent_duplicates": False}})).json()
    times: dict[str, list[float]] = {}
    phones = [Phone(base, i) for i in range(args.guests)]

    # Everyone joins at once and opens a live connection.
    joins = [timed(times, "join", p.http.post("/api/guest/join", json={"code": ev["join_code"], "name": f"Singer {p.n + 1}"}))
             for p in phones]
    for p, res in zip(phones, await asyncio.gather(*joins)):
        p.token = res.json()["token"]
        p.http.headers["Authorization"] = f"Bearer {p.token}"
    ready = [asyncio.Event() for _ in phones]
    listeners = [asyncio.create_task(p.listen(f"{ws_base}/ws/{ev['join_code']}", r)) for p, r in zip(phones, ready)]
    await asyncio.wait_for(asyncio.gather(*(r.wait() for r in ready)), 30)
    await timed(times, "start", host.post(f"/api/host/events/{ev['id']}/actions/start"))

    # Everyone queues songs at once, then cheers.
    started = time.perf_counter()
    queued = [timed(times, "queue song", p.http.post("/api/guest/queue", json={
        "video_id": f"L{p.n:03d}x{s:02d}abcd"[:11], "title": f"Load song {p.n}-{s}"}))
        for s in range(args.songs) for p in phones]
    await asyncio.gather(*queued)
    cheers = [timed(times, "cheer", p.http.post("/api/guest/react", json={"emoji": "🔥"}))
              for _ in range(args.cheers) for p in phones]
    await asyncio.gather(*cheers)
    burst_s = time.perf_counter() - started
    await asyncio.sleep(1)
    states_after_burst = [p.states for p in phones]

    # How long until a host action reaches every phone.
    fanouts = []
    for _ in range(args.skips):
        current = (await host.get(f"/api/host/events/{ev['id']}/state")).json()["now_playing"]["id"]
        for p in phones:
            p.watch_for, p.changed = current, asyncio.Event()
        start = time.perf_counter()
        await timed(times, "skip song", host.post(f"/api/host/events/{ev['id']}/actions/skip-song"))
        await asyncio.wait_for(asyncio.gather(*(p.changed.wait() for p in phones)), 30)
        fanouts.append((time.perf_counter() - start) * 1000)
    await timed(times, "state", host.get(f"/api/host/events/{ev['id']}/state"))

    for t in listeners:
        t.cancel()
    await host.post(f"/api/host/events/{ev['id']}/actions/end")

    print(f"\nKaroulette load test: {args.guests} phones, {args.songs} songs and {args.cheers} cheers each\n")
    for name, values in times.items():
        print(f"  {name:11s} {summary(values)}")
    print(f"  {'reach all':11s} {summary(fanouts)}   (host skip until every phone has the new state)")
    print(f"\n  Burst of {len(queued)} songs + {len(cheers)} cheers took {burst_s:.2f} s; each phone got "
          f"{statistics.median(states_after_burst):.0f} state updates during it (median).")

    worst = max(sorted(v)[min(len(v) - 1, int(len(v) * 0.95))] for k, v in times.items() if k != "join")
    failed = []
    if worst > args.max_p95_ms:
        failed.append(f"a request type's p95 was {worst:.0f} ms (limit {args.max_p95_ms} ms)")
    if max(fanouts) > args.max_fanout_ms:
        failed.append(f"reaching every phone took {max(fanouts):.0f} ms (limit {args.max_fanout_ms} ms)")
    if failed:
        print("\nFAILED: " + "; ".join(failed))
        return 1
    print("\nPassed.")
    return 0


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--base", default="http://127.0.0.1:8095")
    ap.add_argument("--pin", default="2468")
    ap.add_argument("--guests", type=int, default=30)
    ap.add_argument("--songs", type=int, default=3)
    ap.add_argument("--cheers", type=int, default=5)
    ap.add_argument("--skips", type=int, default=5)
    ap.add_argument("--max-p95-ms", type=float, default=750)
    ap.add_argument("--max-fanout-ms", type=float, default=1500)
    sys.exit(asyncio.run(run(ap.parse_args())))


if __name__ == "__main__":
    main()
