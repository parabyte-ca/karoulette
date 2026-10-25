"""FastAPI application: REST API, WebSockets, background ticker and the built SPA."""
from __future__ import annotations

import asyncio
import contextlib
import html
import csv
import io
import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import segno
from fastapi import Depends, FastAPI, HTTPException, Request, Response, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import auth
from .backups import BackupError, Backups
from .banner import BannerError, BannerStore
from .config import Settings
from .db import Database
from .engine import REACTIONS, Engine, EngineError
from .engine.core import ACTOR
from .push import PushService
from .ratelimit import RateLimiter
from .updates import UpdateError, UpdateService
from .ws import Client, Hub
from .youtube import SearchUnavailable, YouTubeService

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("karoulette")


# --------------------------------------------------------------------------- request models

class JoinIn(BaseModel):
    code: str = Field(min_length=3, max_length=10)
    name: str = Field(min_length=1, max_length=40)
    singer_code: str | None = Field(default=None, max_length=10)
    known_tokens: list[str] = Field(default_factory=list, max_length=30)


class RejoinIn(BaseModel):
    code: str = Field(min_length=3, max_length=10)
    rejoin_code: str = Field(min_length=1, max_length=12)


class QueueIn(BaseModel):
    video_id: str = Field(pattern=r"^[A-Za-z0-9_-]{11}$")
    title: str | None = Field(default=None, max_length=300)
    channel: str | None = Field(default=None, max_length=200)
    thumbnail: str | None = Field(default=None, max_length=500)
    duet_guest_id: int | None = None


class VoteIn(BaseModel):
    yes: bool


class CallIn(BaseModel):
    mode: str = Field(default="after", pattern=r"^(now|after)$")


class ReactionIn(BaseModel):
    emoji: str = Field(min_length=1, max_length=8)


class AppearanceIn(BaseModel):
    scheme: str = Field(min_length=1, max_length=20)


class BannerAllIn(BaseModel):
    on: bool


class MergeIn(BaseModel):
    names: list[str] = Field(min_length=1, max_length=50)
    into: str = Field(min_length=1, max_length=40)


class SingerNameIn(BaseModel):
    name: str = Field(min_length=1, max_length=40)


class SwitchIn(BaseModel):
    on: bool


class SuggestIn(BaseModel):
    to_guest_id: int
    video_id: str = Field(pattern=r"^[A-Za-z0-9_-]{11}$")
    title: str | None = Field(default=None, max_length=300)
    channel: str | None = Field(default=None, max_length=200)


class SingerCodeIn(BaseModel):
    code: str = Field(min_length=1, max_length=10)


class ClaimIn(BaseModel):
    names: list[str] = Field(min_length=1, max_length=20)


class AssignIn(BaseModel):
    guest_id: int
    singer_id: int | None = None


class DecideIn(BaseModel):
    approve: bool


class OriginalsIn(BaseModel):
    item_ids: list[int] = Field(min_length=1, max_length=10)
    code: str | None = Field(default=None, max_length=10)


class SpotifyIn(BaseModel):
    client_id: str = Field(max_length=64, pattern=r"^[A-Za-z0-9]*$")


class PinIn(BaseModel):
    pin: str = Field(min_length=1, max_length=64)


class PinChangeIn(BaseModel):
    current: str = Field(min_length=1, max_length=64)
    new: str = Field(min_length=4, max_length=64)


class EventIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    config: dict[str, Any] | None = None


class EventPatch(BaseModel):
    name: str | None = Field(default=None, max_length=80)
    config: dict[str, Any] | None = None


class ThemeIn(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    description: str | None = Field(default="", max_length=280)
    weight: float | None = Field(default=1, ge=0, le=100)
    enabled: bool = True
    ideas: str | None = Field(default="", max_length=400)


class UpgradeIn(BaseModel):
    version: str = Field(pattern=r"^\d+\.\d+\.\d+$")


class PushKeysIn(BaseModel):
    p256dh: str = Field(min_length=20, max_length=200)
    auth: str = Field(min_length=8, max_length=100)


class PushIn(BaseModel):
    endpoint: str = Field(pattern=r"^https://", max_length=1000)
    keys: PushKeysIn
    prefs: dict[str, bool] = Field(default_factory=dict)


class PushPrefsIn(BaseModel):
    endpoint: str = Field(max_length=1000)
    prefs: dict[str, bool]


class PushEndpointIn(BaseModel):
    endpoint: str = Field(max_length=1000)


class PlayerIn(BaseModel):
    item_id: int
    state: str = Field(pattern=r"^(ended|error)$")
    code: int | None = None


EVENT_ACTIONS: dict[str, str] = {
    "start": "start_event", "end": "end_event", "spin": "force_spin", "superset-cancel": "cancel_superset",
    "superset-skip-turn": "skip_superset_turn", "play-next": "play_next", "skip-song": "skip_song",
    "stop-playback": "stop_playback", "start-now": "start_now", "pause-queue": "pause_queue",
    "resume-queue": "resume_queue",
}
MAX_UPLOAD_BYTES = 200_000_000
VIDEO_ACTIONS: dict[str, str] = {"video-toggle": "toggle", "volume-up": "volume_up", "volume-down": "volume_down"}
STATIC_FILES: dict[str, str | None] = {  # files served from the site root, with their media type
    "favicon.svg": None, "robots.txt": None, "manifest.webmanifest": "application/manifest+json",
    "sw.js": "text/javascript", "icon-192.png": None, "icon-512.png": None, "icon-maskable-512.png": None,
    "apple-touch-icon.png": None,
}


# --------------------------------------------------------------------------- app factory

def create_app(settings: Settings | None = None, start_ticker: bool = True,
               youtube: YouTubeService | None = None, updates: UpdateService | None = None,
               push: PushService | None = None) -> FastAPI:
    settings = settings or Settings()
    settings.ensure()
    db = Database(settings.db_path)
    engine = Engine(db)
    engine.seed_themes()
    engine.upgrade_event_configs()
    auth.init_pin(db, settings.host_pin)
    yt = youtube or YouTubeService(db, settings.youtube_api_key, settings.youtube_daily_quota, settings.enable_ytdlp)
    upd = updates or UpdateService(db, settings.version, settings.source_repo, settings.upgrade_dir)
    backups = Backups(db, settings.data_path, settings.version)
    banners = BannerStore(db, settings.data_path)
    banners.migrate()
    site = settings.public_base_url if settings.public_base_url.startswith("https://") else ""
    pusher = push or PushService(db, settings.vapid_subject or site)
    push_tasks: set[asyncio.Task] = set()
    started_at = time.time()
    hub = Hub()
    lock = asyncio.Lock()
    limits = {
        "search_guest": RateLimiter(10, 60), "search_ip": RateLimiter(60, 60),
        "join": RateLimiter(15, 60), "login": RateLimiter(8, 60), "queue": RateLimiter(10, 60),
        "react": RateLimiter(20, 10), "originals": RateLimiter(60, 60), "like": RateLimiter(30, 10),
    }

    pending_state: dict[int, asyncio.Task] = {}
    state_locks: dict[int, asyncio.Lock] = {}

    async def broadcast(messages: list[dict], extra_events: set[int] = frozenset()) -> None:
        """Send typed messages now; the full state follows shortly, once per burst of changes."""
        event_ids = {m["event_id"] for m in messages} | set(extra_events)
        for m in messages:
            await hub.send(m["event_id"], m["message"], m["guest_id"])
        try:
            jobs = engine.push_jobs(messages)
        except Exception:  # an alert must never break the queue
            log.exception("Push alerts failed")
            jobs = []
        for sub, payload in jobs:
            task = asyncio.create_task(pusher.send(sub, payload))
            push_tasks.add(task)
            task.add_done_callback(push_tasks.discard)
        for eid in event_ids:
            if hub.count(eid) and eid not in pending_state:
                pending_state[eid] = asyncio.create_task(send_state(eid))

    async def send_state(eid: int) -> None:
        # Thirty phones queuing at once would otherwise mean thirty full snapshots to thirty phones.
        # Wait a moment to gather the burst; one lock per event keeps snapshots in order.
        await asyncio.sleep(settings.state_coalesce_s)
        async with state_locks.setdefault(eid, asyncio.Lock()):
            pending_state.pop(eid, None)  # changes from here on schedule a fresh snapshot
            async with lock:
                try:
                    snap = engine.snapshot(eid)
                except EngineError:
                    return
            await hub.send(eid, {"type": "state", "data": snap})

    async def run(fn: Callable, *args, event_id: int | None = None):
        async with lock:
            try:
                result = fn(*args)
            except EngineError as exc:
                engine.drain()
                raise HTTPException(exc.status, exc.message) from exc
            messages = engine.drain()
        await broadcast(messages, {event_id} if event_id else set())
        return result

    async def ticker():
        purge_at = asyncio.get_running_loop().time() + 30
        while True:
            await asyncio.sleep(1)
            try:
                await run(engine.tick)  # Superset votes that have run out of time
                loop_time = asyncio.get_running_loop().time()
                if loop_time > purge_at:
                    yt.purge_cache()
                    if settings.update_check:
                        await upd.daily_check()
                    purge_at = loop_time + 3600
            except Exception:  # keep the ticker alive no matter what
                log.exception("Ticker error")

    @contextlib.asynccontextmanager
    async def lifespan(_app: FastAPI):
        task = asyncio.create_task(ticker()) if start_ticker else None
        log.info("Karoulette v%s ready. Data: %s. Search mode: %s", settings.version, settings.data_path,
                 yt.quota_status()["mode"])
        yield
        if task:
            task.cancel()
        for pending in list(pending_state.values()):
            pending.cancel()
        for pending in list(push_tasks):
            pending.cancel()
        await yt.aclose()
        await upd.aclose()
        await pusher.aclose()
        db.close()

    app = FastAPI(title="Karoulette", version=settings.version, lifespan=lifespan,
                  docs_url=None, redoc_url=None, openapi_url=None)
    app.state.engine, app.state.db, app.state.settings, app.state.hub = engine, db, settings, hub
    app.state.push = pusher

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        resp = await call_next(request)
        resp.headers.setdefault("X-Content-Type-Options", "nosniff")
        resp.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        resp.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
        if request.url.path.startswith("/api/"):
            resp.headers.setdefault("Cache-Control", "no-store")
        return resp

    # ------------------------------------------------------------------ helpers

    def client_ip(request: Request) -> str:
        return request.client.host if request.client else "unknown"

    def limit(name: str, key: str) -> None:
        lim = limits[name]
        if not lim.allow(key):
            raise HTTPException(429, f"Slow down a little. Try again in {lim.retry_after(key)} seconds.")

    # These are async so they run in the request's own task: the actor they set reaches the engine's timeline.
    async def require_host(request: Request) -> None:
        if not auth.check_session(settings.secret_key, request.cookies.get(auth.COOKIE_NAME)):
            raise HTTPException(401, "Host login required")
        ACTOR.set(("host", None, "Host"))

    async def current_guest(request: Request) -> dict:
        header = request.headers.get("authorization", "")
        token = header[7:] if header.lower().startswith("bearer ") else ""
        try:
            guest = engine.guest_by_token(token)
        except EngineError as exc:
            raise HTTPException(exc.status, exc.message) from exc
        ACTOR.set(("guest", guest["id"], guest["display_name"]))
        return guest

    def base_url(request: Request) -> str:
        return settings.public_base_url or str(request.base_url).rstrip("/")

    def get_event_or_404(event_id: int) -> dict:
        try:
            return engine.get_event(event_id)
        except EngineError as exc:
            raise HTTPException(exc.status, exc.message) from exc

    # ------------------------------------------------------------------ public

    @app.get("/api/health")
    async def health():
        """For Docker's health check and monitors like Uptime Kuma: 200 + "ok" only if the database answers."""
        try:
            db.one("SELECT 1 AS ok")
            active = db.one("SELECT COUNT(*) AS n FROM events WHERE status = 'active'")["n"]
        except Exception as exc:  # noqa: BLE001  (any database failure means unhealthy)
            log.error("Health check: database error: %s", exc)
            return JSONResponse({"status": "error", "version": settings.version, "database": "error"},
                                status_code=503)
        return {"status": "ok", "version": settings.version, "database": "ok", "active_events": active,
                "connections": sum(len(c) for c in hub.rooms.values()), "uptime_s": int(time.time() - started_at)}

    @app.get("/api/public/events/{code}")
    async def public_event(code: str):
        try:
            ev = engine.event_by_code(code)
        except EngineError as exc:
            raise HTTPException(exc.status, exc.message) from exc
        return {"id": ev["id"], "name": ev["name"], "join_code": ev["join_code"], "status": ev["status"]}

    @app.get("/api/public/join-url")
    async def join_url(request: Request, code: str):
        return {"url": f"{base_url(request)}/join/{code.strip().upper()}"}

    def qr_svg(url: str) -> Response:
        out = io.BytesIO()
        segno.make(url, error="m").save(out, kind="svg", scale=10, border=2, dark="#000000", light="#ffffff")
        return Response(out.getvalue(), media_type="image/svg+xml")

    @app.get("/api/public/qr.svg")
    async def qr(request: Request, code: str, page: str = "join"):
        if not code.isalnum() or len(code) > 10 or page not in ("join", "playlist"):
            raise HTTPException(400, "Invalid code")
        return qr_svg(f"{base_url(request)}/{page}/{code.upper()}")

    # ------------------------------------------------------------------ guest

    @app.post("/api/guest/join")
    async def guest_join(body: JoinIn, request: Request):
        limit("join", client_ip(request))
        ACTOR.set(("guest", None, body.name.strip()[:24]))
        try:
            ev = engine.event_by_code(body.code)
        except EngineError as exc:
            raise HTTPException(exc.status, exc.message) from exc
        guest, token = await run(engine.join, ev["id"], body.name, event_id=ev["id"])
        ACTOR.set(("guest", guest["id"], guest["display_name"]))
        attached = await run(engine.attach_singer, guest["id"], body.singer_code,
                             [t[:100] for t in body.known_tokens], event_id=ev["id"])
        return {"token": token,
                "guest": {"id": guest["id"], "name": guest["display_name"], "rejoin_code": guest["rejoin_code"]},
                "event": {"id": ev["id"], "name": ev["name"], "join_code": ev["join_code"]}, **attached}

    @app.post("/api/guest/rejoin")
    async def guest_rejoin(body: RejoinIn, request: Request):
        limit("join", client_ip(request))
        try:
            ev = engine.event_by_code(body.code)
        except EngineError as exc:
            raise HTTPException(exc.status, exc.message) from exc
        guest, token = await run(engine.rejoin, ev["id"], body.rejoin_code, event_id=ev["id"])
        return {"token": token,
                "guest": {"id": guest["id"], "name": guest["display_name"], "rejoin_code": guest["rejoin_code"]},
                "event": {"id": ev["id"], "name": ev["name"], "join_code": ev["join_code"]},
                "singer": engine.singer_info(engine._singer(guest["singer_id"]))}

    @app.get("/api/guest/me")
    async def guest_me(guest: dict = Depends(current_guest)):
        ev = engine.get_event(guest["event_id"])
        async with lock:
            code = engine.rejoin_code(guest["id"])
        return {"guest": {"id": guest["id"], "name": guest["display_name"], "rejoin_code": code},
                "event": {"id": ev["id"], "name": ev["name"], "join_code": ev["join_code"], "status": ev["status"]},
                "singer": engine.singer_info(engine._singer(guest["singer_id"]))}

    # ------------------------------------------------------------------ returning singers

    def my_singer(guest: dict) -> dict:
        singer = engine._singer(guest["singer_id"])
        if not singer:
            raise HTTPException(409, "You don't have a singer code yet.")
        return singer

    @app.post("/api/public/singer-check")
    async def singer_check(body: SingerCodeIn, request: Request):
        """The join page's "I have a singer code": whose code is it?"""
        limit("join", client_ip(request))
        try:
            singer = engine.singer_by_code(body.code)
        except EngineError as exc:
            raise HTTPException(exc.status, exc.message) from exc
        return {"name": singer["display_name"], "code": singer["code"]}

    # ------------------------------------------------------------------ push alerts

    @app.get("/api/public/push-key")
    async def push_key():
        return {"key": pusher.public_key}

    @app.post("/api/guest/push")
    async def guest_push(body: PushIn, guest: dict = Depends(current_guest)):
        async with lock:
            prefs = engine.save_push(guest["id"], body.endpoint, body.keys.p256dh, body.keys.auth, body.prefs)
        return {"prefs": prefs}

    @app.put("/api/guest/push/prefs")
    async def guest_push_prefs(body: PushPrefsIn, guest: dict = Depends(current_guest)):
        async with lock:
            prefs = engine.set_push_prefs(guest["id"], body.endpoint, body.prefs)
        if not prefs:
            raise HTTPException(404, "Alerts aren't on for this phone. Turn them on again.")
        return {"prefs": prefs}

    @app.post("/api/guest/push/off")
    async def guest_push_off(body: PushEndpointIn, guest: dict = Depends(current_guest)):
        async with lock:
            engine.delete_push(guest["id"], body.endpoint)
        return {"ok": True}

    @app.post("/api/guest/singer-code")
    async def guest_singer_code(body: SingerCodeIn, request: Request, guest: dict = Depends(current_guest)):
        limit("join", client_ip(request))
        return {"singer": await run(engine.use_singer_code, guest["id"], body.code, event_id=guest["event_id"])}

    @app.post("/api/guest/singer/new")
    async def guest_new_singer(guest: dict = Depends(current_guest)):
        """After the host reset this phone's code: start a fresh one for tonight."""
        return await run(engine.attach_singer, guest["id"], None, [], event_id=guest["event_id"])

    @app.get("/api/guest/claimable")
    async def guest_claimable(guest: dict = Depends(current_guest)):
        return engine.claimable_names(my_singer(guest)["code"])

    @app.post("/api/guest/claim")
    async def guest_claim(body: ClaimIn, guest: dict = Depends(current_guest)):
        return await run(engine.claim_names, my_singer(guest)["code"], body.names, event_id=guest["event_id"])

    @app.get("/api/guest/past-songs")
    async def guest_past_songs(guest: dict = Depends(current_guest)):
        singer = engine._singer(guest["singer_id"])
        return engine.past_songs(singer["code"]) if singer else []

    @app.get("/api/guest/state")
    async def guest_state(guest: dict = Depends(current_guest)):
        async with lock:
            return engine.snapshot(guest["event_id"])

    @app.post("/api/guest/leave")
    async def guest_leave(guest: dict = Depends(current_guest)):
        await run(engine.leave, guest["id"], event_id=guest["event_id"])
        return {"ok": True}

    @app.get("/api/guest/search")
    async def guest_search(request: Request, q: str = "", guest: dict = Depends(current_guest)):
        q = q.strip()
        if not 1 <= len(q) <= 100:
            raise HTTPException(422, "Search must be 1 to 100 characters")
        limit("search_guest", f"g{guest['id']}")
        limit("search_ip", client_ip(request))
        ev = engine.get_event(guest["event_id"])
        try:
            found = await yt.search(q, ev["config"]["safe_search"])
        except SearchUnavailable as exc:
            raise HTTPException(503, str(exc)) from exc
        return {**found, "results": engine.mark_duplicates(ev["id"], found["results"])}

    async def checked_video(video_id: str, title: str | None, channel: str | None) -> dict:
        info = await yt.verify(video_id)
        if info is None:
            raise HTTPException(404, "That video isn't available on YouTube.")
        if not info.get("embeddable", True) or info.get("live"):
            raise HTTPException(422, "That video can't be played here (embedding is turned off). Pick another!")
        return {
            "video_id": video_id,
            "title": info.get("title") or (title or "").strip() or "Untitled",
            "channel": info.get("channel") or (channel or "").strip(),
            "thumbnail": info.get("thumbnail") or f"https://i.ytimg.com/vi/{video_id}/mqdefault.jpg",
            "duration_s": info.get("duration_s"),
        }

    @app.post("/api/guest/queue")
    async def guest_queue(body: QueueIn, guest: dict = Depends(current_guest)):
        limit("queue", f"g{guest['id']}")
        video = await checked_video(body.video_id, body.title, body.channel)
        item = await run(engine.queue_song, guest["id"], video, body.duet_guest_id, event_id=guest["event_id"])
        return {"ok": True, "item_id": item["id"]}

    @app.post("/api/guest/like/{item_id}")
    async def guest_like(item_id: int, guest: dict = Depends(current_guest)):
        limit("like", f"g{guest['id']}")
        return await run(engine.toggle_like, guest["id"], item_id, event_id=guest["event_id"])

    @app.post("/api/guest/suggest")
    async def guest_suggest(body: SuggestIn, guest: dict = Depends(current_guest)):
        limit("queue", f"g{guest['id']}")
        video = await checked_video(body.video_id, body.title, body.channel)
        return await run(engine.suggest_song, guest["id"], body.to_guest_id, video, event_id=guest["event_id"])

    @app.get("/api/guest/suggestions")
    async def guest_suggestions(guest: dict = Depends(current_guest)):
        return engine.song_requests_for(guest["id"])

    @app.post("/api/guest/suggestions/{request_id}/add")
    async def guest_add_suggestion(request_id: int, guest: dict = Depends(current_guest)):
        item = await run(engine.accept_request, guest["id"], request_id, event_id=guest["event_id"])
        return {"ok": True, "item_id": item["id"]}

    @app.post("/api/guest/suggestions/{request_id}/dismiss")
    async def guest_dismiss_suggestion(request_id: int, guest: dict = Depends(current_guest)):
        await run(engine.dismiss_request, guest["id"], request_id)
        return {"ok": True}

    @app.get("/api/guest/awards")
    async def guest_awards(guest: dict = Depends(current_guest)):
        return {"awards": engine.personal_awards(guest["id"])}

    @app.post("/api/guest/queue/{item_id}/leave-duet")
    async def guest_leave_duet(item_id: int, guest: dict = Depends(current_guest)):
        await run(engine.leave_duet, guest["id"], item_id, event_id=guest["event_id"])
        return {"ok": True}

    @app.post("/api/guest/superset/call")
    async def guest_call_superset(body: CallIn | None = None, guest: dict = Depends(current_guest)):
        await run(engine.call_superset_vote, guest["id"], (body or CallIn()).mode, event_id=guest["event_id"])
        return {"ok": True}

    @app.post("/api/guest/superset/pass")
    async def guest_pass_superset(guest: dict = Depends(current_guest)):
        await run(engine.pass_superset, guest["id"], event_id=guest["event_id"])
        return {"ok": True}

    @app.post("/api/guest/superset/vote")
    async def guest_vote_superset(body: VoteIn, guest: dict = Depends(current_guest)):
        await run(engine.vote_superset, guest["id"], body.yes, event_id=guest["event_id"])
        return {"ok": True}

    @app.post("/api/guest/react")
    async def guest_react(body: ReactionIn, guest: dict = Depends(current_guest)):
        if body.emoji not in REACTIONS:
            raise HTTPException(422, "Pick one of the reaction buttons.")
        limit("react", f"g{guest['id']}")
        # Each cheer counts towards the song playing (the crowd meter and "Crowd favourite"); only the TV
        # and remote are sent the reaction itself, and no full state update follows.
        counted = await run(engine.cheer, guest["id"])
        await hub.send_screens(guest["event_id"], {"type": "reaction", "data": {
            "emoji": body.emoji, "name": guest["display_name"],
            "item_id": counted[0] if counted else None, "cheers": counted[1] if counted else 0}})
        return {"ok": True}

    @app.post("/api/guest/queue/{item_id}/let-next-go-first")
    async def guest_let_next_go_first(item_id: int, guest: dict = Depends(current_guest)):
        await run(engine.let_next_go_first, guest["id"], item_id, event_id=guest["event_id"])
        return {"ok": True}

    @app.post("/api/guest/queue/{item_id}/up")
    async def guest_song_up(item_id: int, guest: dict = Depends(current_guest)):
        await run(engine.move_my_song_up, guest["id"], item_id, event_id=guest["event_id"])
        return {"ok": True}

    @app.delete("/api/guest/queue/{item_id}")
    async def guest_remove(item_id: int, guest: dict = Depends(current_guest)):
        await run(engine.remove_item, guest["event_id"], item_id, guest["id"], event_id=guest["event_id"])
        return {"ok": True}

    @app.post("/api/guest/flag/{item_id}")
    async def guest_flag(item_id: int, guest: dict = Depends(current_guest)):
        count = await run(engine.flag_item, guest["event_id"], item_id, f"guest:{guest['id']}",
                          event_id=guest["event_id"])
        return {"ok": True, "count": count}

    # ------------------------------------------------------------------ host auth

    @app.post("/api/host/login")
    async def host_login(body: PinIn, request: Request, response: Response):
        limit("login", client_ip(request))
        if not auth.verify_pin(body.pin.strip(), db.get_setting("host_pin_hash", "")):
            raise HTTPException(401, "That PIN didn't match.")
        secure = request.headers.get("x-forwarded-proto", request.url.scheme) == "https"
        response.set_cookie(auth.COOKIE_NAME, auth.make_session(settings.secret_key), max_age=auth.SESSION_SECONDS,
                            httponly=True, samesite="lax", secure=secure, path="/")
        return {"ok": True}

    @app.post("/api/host/logout")
    async def host_logout(response: Response):
        response.delete_cookie(auth.COOKIE_NAME, path="/")
        return {"ok": True}

    @app.get("/api/host/session")
    async def host_session(request: Request):
        return {"authenticated": auth.check_session(settings.secret_key, request.cookies.get(auth.COOKIE_NAME)),
                "pin_from_env": bool(db.get_setting("host_pin_from_env")), "version": settings.version}

    @app.post("/api/host/pin", dependencies=[Depends(require_host)])
    async def host_pin(body: PinChangeIn):
        if db.get_setting("host_pin_from_env"):
            raise HTTPException(409, "The PIN is set by HOST_PIN in your .env file. Change it there.")
        if not auth.verify_pin(body.current.strip(), db.get_setting("host_pin_hash", "")):
            raise HTTPException(401, "Current PIN is incorrect.")
        try:
            db.set_setting("host_pin_hash", auth.hash_pin(auth.validate_pin(body.new)))
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        return {"ok": True}

    # ------------------------------------------------------------------ host: events

    host = [Depends(require_host)]

    @app.get("/api/host/events", dependencies=host)
    async def list_events():
        return engine.list_events()

    @app.post("/api/host/events", dependencies=host)
    async def create_event(body: EventIn):
        ev = await run(engine.create_event, body.name, body.config)
        return {"id": ev["id"], "join_code": ev["join_code"]}

    @app.get("/api/host/events/{event_id}/state", dependencies=host)
    async def event_state(event_id: int):
        get_event_or_404(event_id)
        async with lock:
            return engine.snapshot(event_id)

    @app.patch("/api/host/events/{event_id}", dependencies=host)
    async def patch_event(event_id: int, body: EventPatch):
        await run(engine.update_event, event_id, body.name, body.config, event_id=event_id)
        return {"ok": True}

    @app.post("/api/host/events/{event_id}/archive", dependencies=host)
    async def archive_event(event_id: int, body: SwitchIn):
        return await run(engine.archive_event, event_id, body.on, event_id=event_id)

    @app.get("/api/host/events/{event_id}/timeline", dependencies=host)
    async def event_timeline(event_id: int):
        try:
            return engine.event_timeline(event_id)
        except EngineError as exc:
            raise HTTPException(exc.status, exc.message) from exc

    @app.get("/api/host/events/{event_id}/timeline.csv", dependencies=host)
    async def event_timeline_csv(event_id: int):
        ev = get_event_or_404(event_id)
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(["time_utc", "kind", "who", "what"])
        for r in engine.event_timeline(event_id):
            w.writerow([datetime.fromtimestamp(r["at"], tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
                        r["kind"], r["actor_name"], r["text"]])
        safe = "".join(c if c.isalnum() else "-" for c in ev["name"]).strip("-")[:40] or "event"
        return PlainTextResponse(buf.getvalue(), media_type="text/csv",
                                 headers={"Content-Disposition": f'attachment; filename="karoulette-{safe}-timeline.csv"'})

    @app.delete("/api/host/events/{event_id}", dependencies=host)
    async def delete_event(event_id: int):
        await run(engine.delete_event, event_id)
        return {"ok": True}

    @app.post("/api/host/events/{event_id}/actions/{action}", dependencies=host)
    async def event_action(event_id: int, action: str):
        if action in VIDEO_ACTIONS:
            await run(engine.video_command, event_id, VIDEO_ACTIONS[action])
            return {"ok": True}
        if action in ("superset-now", "superset-after"):  # "now": this song kicks the set off
            await run(engine.force_superset, event_id, action.split("-")[1], event_id=event_id)
            return {"ok": True}
        method = EVENT_ACTIONS.get(action)
        if not method:
            raise HTTPException(404, "Unknown action")
        await run(getattr(engine, method), event_id, event_id=event_id)
        return {"ok": True}

    @app.get("/api/host/events/{event_id}/guests", dependencies=host)
    async def event_guests(event_id: int):
        get_event_or_404(event_id)
        async with lock:
            return engine.guest_codes(event_id)

    @app.get("/api/host/events/{event_id}/remote-qr.svg", dependencies=host)
    async def remote_qr(request: Request, event_id: int):
        get_event_or_404(event_id)
        return qr_svg(f"{base_url(request)}/host/remote/{event_id}")

    @app.post("/api/host/events/{event_id}/queue/{item_id}/play-next", dependencies=host)
    async def play_item_next(event_id: int, item_id: int):
        await run(engine.play_item_next, event_id, item_id, event_id=event_id)
        return {"ok": True}

    @app.delete("/api/host/events/{event_id}/queue/{item_id}", dependencies=host)
    async def remove_item(event_id: int, item_id: int):
        await run(engine.remove_item, event_id, item_id, event_id=event_id)
        return {"ok": True}

    @app.post("/api/host/events/{event_id}/queue/{item_id}/flag", dependencies=host)
    async def host_flag(event_id: int, item_id: int):
        count = await run(engine.flag_item, event_id, item_id, "host", event_id=event_id)
        return {"ok": True, "count": count}

    @app.post("/api/host/events/{event_id}/guests/{guest_id}/{action}", dependencies=host)
    async def guest_action(event_id: int, guest_id: int, action: str):
        g = db.one("SELECT event_id FROM guests WHERE id = ?", (guest_id,))
        if not g or g["event_id"] != event_id:
            raise HTTPException(404, "Guest not found")
        fn = {"remove": engine.remove_guest,
              "up": lambda gid: engine.move_guest(gid, -1),
              "down": lambda gid: engine.move_guest(gid, 1)}.get(action)
        if not fn:
            raise HTTPException(404, "Unknown action")
        await run(fn, guest_id, event_id=event_id)
        return {"ok": True}

    @app.post("/api/host/events/{event_id}/player", dependencies=host)
    async def player(event_id: int, body: PlayerIn):
        ACTOR.set(None)  # the TV reporting the end of a song: what follows is automatic, not the host
        if body.state == "ended":
            await run(engine.player_ended, event_id, body.item_id, event_id=event_id)
        else:
            await run(engine.player_error, event_id, body.item_id, int(body.code or 0), event_id=event_id)
        return {"ok": True}

    @app.get("/api/host/events/{event_id}/history.csv", dependencies=host)
    async def history_csv(event_id: int):
        ev = get_event_or_404(event_id)
        safe = "".join(c if c.isalnum() else "-" for c in ev["name"]).strip("-")[:40] or "event"
        return PlainTextResponse(engine.history_csv(event_id), media_type="text/csv",
                                 headers={"Content-Disposition": f'attachment; filename="karoulette-{safe}.csv"'})

    # ------------------------------------------------------------------ song history (every event)

    @app.get("/api/host/history", dependencies=host)
    async def host_history():
        return {**engine.history(), "names": engine.singer_names(),
                "spotify": {"client_id": engine.spotify_client_id(settings.spotify_client_id),
                            "from_env": bool(settings.spotify_client_id),
                            "redirect_uri": f"{settings.public_base_url}/spotify" if settings.public_base_url else None}}

    @app.get("/api/public/history")
    async def public_history():
        if not engine.history_public():
            raise HTTPException(404, "The host hasn't shared the song history.")
        return engine.history()

    @app.put("/api/host/history/public", dependencies=host)
    async def history_public(body: SwitchIn):
        return {"public": await run(engine.set_history_public, body.on)}

    @app.post("/api/host/history/merge", dependencies=host)
    async def merge_singers(body: MergeIn):
        return await run(engine.merge_singers, body.names, body.into)

    @app.post("/api/host/history/unmerge", dependencies=host)
    async def unmerge_singer(body: SingerNameIn):
        return await run(engine.unmerge_singer, body.name)

    # ------------------------------------------------------------------ host: singers

    @app.get("/api/host/singers", dependencies=host)
    async def host_singers():
        return engine.singers_admin()

    @app.post("/api/host/singers/assign", dependencies=host)
    async def host_assign_night(body: AssignIn):
        return await run(engine.assign_night, body.guest_id, body.singer_id)

    @app.post("/api/host/singers/{singer_id}/reset-code", dependencies=host)
    async def host_reset_code(singer_id: int):
        return await run(engine.reset_singer_code, singer_id)

    @app.post("/api/host/singer-claims/{claim_id}", dependencies=host)
    async def host_decide_claim(claim_id: int, body: DecideIn):
        return await run(engine.decide_claim, claim_id, body.approve)

    # ------------------------------------------------------------------ playlists

    @app.get("/api/public/events/{code}/playlist")
    async def event_playlist(code: str):
        try:
            return engine.event_playlist(code)
        except EngineError as exc:
            raise HTTPException(exc.status, exc.message) from exc

    @app.get("/api/public/playlist-config")
    async def playlist_config():
        return {"spotify_client_id": engine.spotify_client_id(settings.spotify_client_id)}

    @app.put("/api/host/playlists/spotify", dependencies=host)
    async def set_spotify(body: SpotifyIn):
        if settings.spotify_client_id:
            raise HTTPException(409, "The Spotify client ID is set by SPOTIFY_CLIENT_ID in the container settings.")
        return {"spotify_client_id": await run(engine.set_spotify_client_id, body.client_id)}

    @app.post("/api/public/playlist/originals")
    async def playlist_originals(body: OriginalsIn, request: Request):
        """The original recording of each sung song, for a YouTube playlist: from one event (with its join
        code), from the song history (when it's shared), or anything for the host. Falls back to the
        karaoke video when the original can't be found."""
        is_host = auth.check_session(settings.secret_key, request.cookies.get(auth.COOKIE_NAME))
        if not body.code and not is_host and not engine.history_public():
            raise HTTPException(403, "The host hasn't shared the song history.")
        items = engine.playlist_items(body.item_ids, None if is_host and not body.code else body.code)
        out = []
        for item in items:
            known = db.one("SELECT video_id FROM song_originals WHERE song_key = ?", (item["track"].casefold(),))
            if known is None and not is_host:
                limit("originals", client_ip(request))
            video_id = await yt.find_original(item["track"])
            out.append({"item_id": item["item_id"], "track": item["track"],
                        "video_id": video_id or item["karaoke_video_id"], "original": bool(video_id)})
        return out

    # ------------------------------------------------------------------ host: themes & quota

    @app.get("/api/host/themes", dependencies=host)
    async def themes():
        return engine.list_themes()

    @app.post("/api/host/themes", dependencies=host)
    async def create_theme(body: ThemeIn):
        return await run(engine.save_theme, body.model_dump())

    @app.put("/api/host/themes/{theme_id}", dependencies=host)
    async def update_theme(theme_id: int, body: ThemeIn):
        return await run(engine.save_theme, body.model_dump(), theme_id)

    @app.delete("/api/host/themes/{theme_id}", dependencies=host)
    async def delete_theme(theme_id: int):
        await run(engine.delete_theme, theme_id)
        return {"ok": True}

    @app.get("/api/host/quota", dependencies=host)
    async def quota():
        return yt.quota_status()

    # ------------------------------------------------------------------ host: backups

    def backup_call(fn, *args):
        try:
            return fn(*args)
        except BackupError as exc:
            raise HTTPException(exc.status, exc.message) from exc

    @app.get("/api/host/backups", dependencies=host)
    async def list_backups():
        return {"folder": str(backups.dir), "backups": backups.list()}

    @app.post("/api/host/backups", dependencies=host)
    async def create_backup():
        return backup_call(backups.create, "manual")

    @app.get("/api/host/backups/{name}", dependencies=host)
    async def download_backup(name: str):
        return FileResponse(backup_call(backups.path, name), media_type="application/vnd.sqlite3", filename=name)

    @app.delete("/api/host/backups/{name}", dependencies=host)
    async def delete_backup(name: str):
        backup_call(backups.delete, name)
        return {"ok": True}

    async def after_restore(result: dict) -> dict:
        engine.seed_themes()
        engine.upgrade_event_configs()
        auth.init_pin(db, settings.host_pin)  # a PIN set in .env still works after restoring
        pusher.load_key()  # phones restored with the backup subscribed with its key
        await broadcast([], set(hub.rooms))
        log.info("Restored %s (saved the previous database as %s)", result["restored"], result["safety_backup"])
        return result

    @app.post("/api/host/backups/{name}/restore", dependencies=host)
    async def restore_backup(name: str):
        async with lock:
            result = backup_call(backups.restore, name)
        return await after_restore(result)

    @app.post("/api/host/backups-upload", dependencies=host)
    async def upload_backup(request: Request):
        """Restore from a .db file sent as the raw request body (no multipart needed)."""
        chunks, size = [], 0
        async for chunk in request.stream():
            size += len(chunk)
            if size > MAX_UPLOAD_BYTES:
                raise HTTPException(413, f"That file is over {MAX_UPLOAD_BYTES // 1_000_000} MB.")
            chunks.append(chunk)
        name = backup_call(backups.save_upload, chunks)
        async with lock:
            result = backup_call(backups.restore, name)
        return await after_restore(result)

    @app.get("/api/host/updates", dependencies=host)
    async def updates_status():
        return upd.status()

    @app.post("/api/host/updates/check", dependencies=host)
    async def updates_check():
        return await upd.check_now()

    @app.post("/api/host/updates/upgrade", dependencies=host)
    async def updates_upgrade(body: UpgradeIn):
        try:
            return upd.request_upgrade(body.version)
        except UpdateError as exc:
            raise HTTPException(exc.status, exc.message) from exc

    @app.get("/api/public/appearance")
    async def public_appearance():
        return engine.appearance()

    @app.put("/api/host/appearance", dependencies=host)
    async def set_appearance(body: AppearanceIn):
        result = await run(engine.set_scheme, body.scheme)
        await broadcast([], set(hub.rooms))  # repaint every TV and phone right away
        return result

    @app.get("/api/public/banner")
    async def public_banner():
        stored = banners.get() if db.get_setting("banner_custom") else None
        if not stored:
            raise HTTPException(404, "No banner uploaded")
        # The URL carries a version, so browsers can keep it until a new banner is uploaded.
        return Response(stored[0], media_type=stored[1],
                        headers={"Cache-Control": "public, max-age=31536000, immutable"})

    @app.put("/api/host/appearance/banner", dependencies=host)
    async def upload_banner(request: Request):
        """A new banner image, sent as the raw request body."""
        chunks, size = [], 0
        async for chunk in request.stream():
            size += len(chunk)
            if size > 8_000_000:
                raise HTTPException(413, "That image is over 8 MB.")
            chunks.append(chunk)
        try:
            ext = banners.save(b"".join(chunks))
        except BannerError as exc:
            raise HTTPException(exc.status, exc.message) from exc
        result = await run(engine.set_banner, ext)
        await broadcast([], set(hub.rooms))
        return result

    @app.delete("/api/host/appearance/banner", dependencies=host)
    async def delete_banner():
        banners.delete()
        result = await run(engine.set_banner, None)
        await broadcast([], set(hub.rooms))
        return result

    @app.put("/api/host/appearance/banner-all", dependencies=host)
    async def banner_on_all(body: BannerAllIn):
        result = await run(engine.set_banner_all, body.on)
        await broadcast([], set(hub.rooms))
        return result

    @app.get("/api/public/themes")
    async def public_themes():
        return [t["name"] for t in engine.list_themes() if t["enabled"]]

    # ------------------------------------------------------------------ websocket

    @app.websocket("/ws/{code}")
    async def websocket(ws: WebSocket, code: str):
        try:
            ev = engine.event_by_code(code)
        except EngineError:
            await ws.close(code=4404)
            return
        token = ws.query_params.get("token")
        if token:
            try:
                guest = engine.guest_by_token(token)
            except EngineError:
                await ws.close(code=4401)
                return
            if guest["event_id"] != ev["id"]:
                await ws.close(code=4403)
                return
            client = Client(ws, "guest", guest["id"])
        elif auth.check_session(settings.secret_key, ws.cookies.get(auth.COOKIE_NAME)):
            client = Client(ws, "host")
        else:
            await ws.close(code=4401)
            return
        await ws.accept()
        hub.add(ev["id"], client)
        try:
            async with lock:
                snap = engine.snapshot(ev["id"])
            async with client.lock:
                await ws.send_json({"type": "state", "data": snap})
            while True:
                msg = await ws.receive_text()
                if msg == "ping":
                    async with client.lock:
                        await ws.send_text('{"type":"pong"}')
        except (WebSocketDisconnect, RuntimeError):
            pass
        finally:
            hub.remove(ev["id"], client)

    # ------------------------------------------------------------------ SPA

    def spa_page(request: Request, code: str | None = None, playlist: bool = False) -> Response:
        """The app's index.html, with link-preview tags so a shared join link shows the event and banner."""
        index = settings.static_dir / "index.html"
        if not index.exists():
            return JSONResponse({"detail": "Frontend not built. API is at /api."}, status_code=404)
        title, description = "Karoulette", "Karaoke night: queue songs from your phone and watch the line-up live."
        if code:
            try:
                ev = engine.event_by_code(code)
                if playlist:
                    title = f"{ev['name']}: the playlist · Karoulette"
                    description = "Every song from the night, as a YouTube or Spotify playlist. 🎶"
                elif ev["status"] != "ended":
                    title = f"Join {ev['name']} on Karoulette"
                    description = f"Tap to join with code {ev['join_code']}, then queue your songs from your phone. 🎤"
            except EngineError:
                pass
        look = engine.appearance()
        image = f"{base_url(request)}{look['og_image'] or '/icon-512.png'}"
        tags = "".join(
            f'<meta property="{p}" content="{html.escape(v, quote=True)}" />' for p, v in (
                ("og:type", "website"), ("og:site_name", "Karoulette"), ("og:title", title),
                ("og:description", description), ("og:image", image)))
        tags += ('<meta name="twitter:card" content="summary_large_image" />'
                 f'<meta name="description" content="{html.escape(description, quote=True)}" />')
        page = index.read_text().replace("</head>", tags + "</head>", 1)
        return Response(page, media_type="text/html")

    @app.exception_handler(404)
    async def not_found(request: Request, exc):
        if request.url.path.startswith(("/api/", "/ws/")):
            detail = getattr(exc, "detail", "Not found")
            return JSONResponse({"detail": detail}, status_code=404)
        return spa_page(request)

    @app.get("/join")
    async def join_page(request: Request):
        return spa_page(request)

    @app.get("/playlist/{code}")
    async def playlist_page(request: Request, code: str):
        return spa_page(request, code, playlist=True)

    @app.get("/join/{code}")
    async def join_code_page(request: Request, code: str):
        return spa_page(request, code)

    if (settings.static_dir / "assets").exists():
        app.mount("/assets", StaticFiles(directory=settings.static_dir / "assets"), name="assets")
    if (settings.static_dir / "banners").exists():
        app.mount("/banners", StaticFiles(directory=settings.static_dir / "banners"), name="banners")

    @app.get("/")
    async def root(request: Request):
        return spa_page(request)

    for static_file, media_type in STATIC_FILES.items():
        path: Path = settings.static_dir / static_file
        if not path.exists():
            continue
        if static_file == "sw.js":
            # Stamp the version so each release gets a fresh cache, and never let browsers cache the worker
            # itself, so new releases reach installed phones.
            worker = path.read_text().replace("__KAROULETTE_VERSION__", settings.version)
            app.add_api_route("/sw.js", (lambda body=worker, m=media_type: Response(
                body, media_type=m, headers={"Cache-Control": "no-cache"})), methods=["GET"])
        else:
            app.add_api_route(f"/{static_file}", (lambda p=path, m=media_type: FileResponse(p, media_type=m)),
                              methods=["GET"])

    return app


