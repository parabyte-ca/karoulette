"""YouTube search and video verification.

Primary: YouTube Data API v3 (search.list + videos.list), cached in SQLite with a daily
quota ledger. Fallback: yt-dlp metadata-only search (never downloads media).
The API key never leaves the server.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from datetime import datetime
from zoneinfo import ZoneInfo

import httpx

from . import logic
from .db import Database

log = logging.getLogger("karoulette.youtube")

API_BASE = "https://www.googleapis.com/youtube/v3"
SEARCH_COST = 100
VIDEOS_COST = 1
SEARCH_TTL = 24 * 3600
VIDEO_TTL = 7 * 24 * 3600
MAX_RESULTS = 15
ORIGINAL_RESERVE = 3000  # quota units kept back for guests' searches when finding originals for playlists
NOT_ORIGINAL = re.compile(r"karaoke|instrumental|backing track|cover|sing ?along|nightcore|8d audio|slowed",
                          re.IGNORECASE)
PACIFIC = ZoneInfo("America/Los_Angeles")  # YouTube quotas reset at midnight Pacific
VIDEO_ID_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")


class SearchUnavailable(Exception):
    pass


def parse_iso_duration(value: str | None) -> int | None:
    if not value:
        return None
    m = re.fullmatch(r"P(?:(\d+)D)?T?(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", value)
    if not m:
        return None
    d, h, mi, s = (int(x) if x else 0 for x in m.groups())
    return d * 86400 + h * 3600 + mi * 60 + s


class YouTubeService:
    def __init__(self, db: Database, api_key: str, daily_quota: int = 10000, enable_ytdlp: bool = True,
                 client: httpx.AsyncClient | None = None):
        self.db = db
        self.api_key = api_key
        self.daily_quota = daily_quota
        self.enable_ytdlp = enable_ytdlp
        self.client = client or httpx.AsyncClient(timeout=10.0)

    # ------------------------------------------------------------------ quota

    @staticmethod
    def _day() -> str:
        return datetime.now(PACIFIC).strftime("%Y-%m-%d")

    def quota_status(self) -> dict:
        row = self.db.one("SELECT * FROM quota_ledger WHERE day = ?", (self._day(),)) or {"units_used": 0, "exhausted": 0}
        used = row["units_used"]
        return {
            "api_key_configured": bool(self.api_key),
            "day": self._day(),
            "daily_quota": self.daily_quota,
            "units_used": used,
            "units_remaining": 0 if row["exhausted"] else max(0, self.daily_quota - used),
            "searches_remaining": 0 if row["exhausted"] else max(0, (self.daily_quota - used) // (SEARCH_COST + VIDEOS_COST)),
            "exhausted": bool(row["exhausted"]),
            "fallback_enabled": self.enable_ytdlp,
            "mode": "api" if self.api_key and not row["exhausted"] else ("ytdlp" if self.enable_ytdlp else "unavailable"),
        }

    def _spend(self, units: int) -> None:
        self.db.execute("INSERT INTO quota_ledger(day, units_used) VALUES (?, ?) "
                        "ON CONFLICT(day) DO UPDATE SET units_used = units_used + excluded.units_used",
                        (self._day(), units))

    def _mark_exhausted(self) -> None:
        self.db.execute("INSERT INTO quota_ledger(day, units_used, exhausted) VALUES (?, 0, 1) "
                        "ON CONFLICT(day) DO UPDATE SET exhausted = 1", (self._day(),))

    def _can_spend(self, units: int) -> bool:
        q = self.quota_status()
        return q["api_key_configured"] and not q["exhausted"] and q["units_remaining"] >= units

    # ------------------------------------------------------------------ API calls

    async def _api_get(self, path: str, params: dict, cost: int) -> dict:
        self._spend(cost)
        resp = await self.client.get(f"{API_BASE}/{path}", params={**params, "key": self.api_key})
        if resp.status_code == 403:
            try:
                reasons = {e.get("reason") for e in resp.json().get("error", {}).get("errors", [])}
            except ValueError:
                reasons = set()
            if reasons & {"quotaExceeded", "dailyLimitExceeded", "rateLimitExceeded"}:
                self._mark_exhausted()
                raise SearchUnavailable("quota")
        if resp.status_code >= 400:
            # Never log the full URL: it contains the API key.
            raise SearchUnavailable(f"YouTube API HTTP {resp.status_code}")
        return resp.json()

    async def _api_videos(self, ids: list[str]) -> dict[str, dict]:
        if not ids:
            return {}
        data = await self._api_get("videos", {"part": "contentDetails,status,snippet", "id": ",".join(ids),
                                              "maxResults": 50}, VIDEOS_COST)
        out = {}
        for item in data.get("items", []):
            sn = item.get("snippet", {})
            thumbs = sn.get("thumbnails", {})
            out[item["id"]] = {
                "video_id": item["id"],
                "title": sn.get("title", ""),
                "channel": sn.get("channelTitle", ""),
                "thumbnail": (thumbs.get("medium") or thumbs.get("default") or {}).get("url", ""),
                "duration_s": parse_iso_duration(item.get("contentDetails", {}).get("duration")),
                "embeddable": bool(item.get("status", {}).get("embeddable", False)),
                "live": sn.get("liveBroadcastContent", "none") != "none",
                "verified": True,
            }
        now = time.time()
        for vid, v in out.items():
            self.db.execute("INSERT OR REPLACE INTO video_cache(video_id, data, fetched_at) VALUES (?, ?, ?)",
                            (vid, json.dumps(v), now))
        return out

    async def _api_search(self, query: str, safe_search: str) -> list[dict]:
        data = await self._api_get("search", {
            "part": "snippet", "q": query, "type": "video", "videoEmbeddable": "true",
            "videoSyndicated": "true", "safeSearch": safe_search, "maxResults": MAX_RESULTS,
        }, SEARCH_COST)
        ids = [i["id"]["videoId"] for i in data.get("items", []) if i.get("id", {}).get("videoId")]
        details = await self._api_videos(ids) if self._can_spend(VIDEOS_COST) else {}
        results = []
        for item in data.get("items", []):
            vid = item.get("id", {}).get("videoId")
            if not vid:
                continue
            d = details.get(vid)
            if d and (not d["embeddable"] or d["live"]):
                continue
            sn = item.get("snippet", {})
            thumbs = sn.get("thumbnails", {})
            results.append(d or {
                "video_id": vid, "title": sn.get("title", ""), "channel": sn.get("channelTitle", ""),
                "thumbnail": (thumbs.get("medium") or thumbs.get("default") or {}).get("url", ""),
                "duration_s": None, "embeddable": True, "verified": False,
            })
        return results

    # ------------------------------------------------------------------ yt-dlp fallback

    @staticmethod
    def _ytdlp_extract(target: str, flat: bool) -> dict:
        import yt_dlp  # imported lazily: heavy module

        opts = {"quiet": True, "no_warnings": True, "skip_download": True, "noplaylist": True,
                "extract_flat": "in_playlist" if flat else False, "socket_timeout": 10}
        with yt_dlp.YoutubeDL(opts) as ydl:
            return ydl.extract_info(target, download=False) or {}

    async def _ytdlp_search(self, query: str) -> list[dict]:
        info = await asyncio.to_thread(self._ytdlp_extract, f"ytsearch{MAX_RESULTS}:{query}", True)
        results = []
        for e in info.get("entries") or []:
            vid = e.get("id")
            if not vid or not VIDEO_ID_RE.match(vid) or e.get("live_status") in ("is_live", "is_upcoming"):
                continue
            thumbs = e.get("thumbnails") or []
            results.append({
                "video_id": vid, "title": e.get("title") or "", "channel": e.get("channel") or e.get("uploader") or "",
                "thumbnail": f"https://i.ytimg.com/vi/{vid}/mqdefault.jpg" if not thumbs else thumbs[-1].get("url", ""),
                "duration_s": int(e["duration"]) if e.get("duration") else None,
                "embeddable": True, "verified": False,
            })
        return results

    async def _ytdlp_video(self, video_id: str) -> dict | None:
        info = await asyncio.to_thread(self._ytdlp_extract, f"https://www.youtube.com/watch?v={video_id}", False)
        if not info:
            return None
        v = {
            "video_id": video_id, "title": info.get("title") or "", "channel": info.get("channel") or info.get("uploader") or "",
            "thumbnail": f"https://i.ytimg.com/vi/{video_id}/mqdefault.jpg",
            "duration_s": int(info["duration"]) if info.get("duration") else None,
            "embeddable": info.get("playable_in_embed", True) is not False,
            "live": info.get("is_live") or False, "verified": True,
        }
        self.db.execute("INSERT OR REPLACE INTO video_cache(video_id, data, fetched_at) VALUES (?, ?, ?)",
                        (video_id, json.dumps(v), time.time()))
        return v

    # ------------------------------------------------------------------ public

    async def search(self, raw_query: str, safe_search: str = "moderate") -> dict:
        query = logic.karaoke_query(raw_query)
        key = f"{safe_search}|{query}"
        cached = self.db.one("SELECT * FROM search_cache WHERE query_key = ?", (key,))
        if cached and time.time() - cached["fetched_at"] < SEARCH_TTL:
            return {"query": query, "source": cached["source"], "cached": True, "results": json.loads(cached["results"])}

        results, source, warning = None, None, None
        if self._can_spend(SEARCH_COST + VIDEOS_COST):
            try:
                results, source = await self._api_search(query, safe_search), "api"
            except SearchUnavailable as exc:
                warning = "YouTube quota reached for today, using backup search." if str(exc) == "quota" \
                    else "YouTube search is having trouble, using backup search."
                log.warning("YouTube API search failed: %s", exc)
            except httpx.HTTPError as exc:
                warning = "YouTube search is having trouble, using backup search."
                log.warning("YouTube API request error: %s", type(exc).__name__)
        if results is None:
            if not self.enable_ytdlp:
                raise SearchUnavailable("Search is unavailable right now. Ask the host to check the YouTube API key.")
            try:
                results, source = await self._ytdlp_search(query), "ytdlp"
            except Exception as exc:  # yt-dlp raises many types
                log.warning("yt-dlp search failed: %s", exc)
                raise SearchUnavailable("Search is unavailable right now. Please try again in a moment.") from exc
        self.db.execute("INSERT OR REPLACE INTO search_cache(query_key, results, source, fetched_at) VALUES (?, ?, ?, ?)",
                        (key, json.dumps(results), source, time.time()))
        return {"query": query, "source": source, "cached": False, "results": results, "warning": warning}

    async def verify(self, video_id: str) -> dict | None:
        """Return verified metadata (duration, embeddable) or None if the video doesn't exist."""
        if not VIDEO_ID_RE.match(video_id or ""):
            return None
        cached = self.db.one("SELECT * FROM video_cache WHERE video_id = ?", (video_id,))
        if cached and time.time() - cached["fetched_at"] < VIDEO_TTL:
            return json.loads(cached["data"])
        if self._can_spend(VIDEOS_COST):
            try:
                found = await self._api_videos([video_id])
                return found.get(video_id)
            except (SearchUnavailable, httpx.HTTPError) as exc:
                log.warning("videos.list failed: %s", exc)
        if self.enable_ytdlp:
            try:
                return await self._ytdlp_video(video_id)
            except Exception as exc:
                log.warning("yt-dlp verify failed: %s", exc)
                if "unavailable" in str(exc).lower() or "private" in str(exc).lower():
                    return None
        # Could not verify: allow it; the host player's error handler is the safety net.
        return {"video_id": video_id, "embeddable": True, "duration_s": None, "verified": False}

    async def find_original(self, song: str) -> str | None:
        """The original recording of a song (for playlists), cached for good. yt-dlp first since it's free;
        the API only while plenty of quota is left for guests' searches. None if it can't be found."""
        key = song.casefold()
        cached = self.db.one("SELECT video_id FROM song_originals WHERE song_key = ?", (key,))
        if cached:
            return cached["video_id"]
        query = f"{song} official audio"
        results, source = None, None
        if self.enable_ytdlp:
            try:
                results, source = await self._ytdlp_search(query), "ytdlp"
            except Exception as exc:  # yt-dlp raises many types
                log.warning("yt-dlp original lookup failed: %s", exc)
        if results is None and self._can_spend(SEARCH_COST + ORIGINAL_RESERVE):
            try:
                data = await self._api_get("search", {"part": "snippet", "q": query, "type": "video",
                                                      "videoCategoryId": "10", "maxResults": 5}, SEARCH_COST)
                results = [{"video_id": i["id"]["videoId"], "title": i.get("snippet", {}).get("title", "")}
                           for i in data.get("items", []) if i.get("id", {}).get("videoId")]
                source = "api"
            except (SearchUnavailable, httpx.HTTPError) as exc:
                log.warning("Original lookup failed: %s", exc)
        if results is None:
            return None  # nothing to ask right now: try again next time
        pick = next((r["video_id"] for r in results if not NOT_ORIGINAL.search(r.get("title", ""))), None)
        self.db.execute("INSERT OR REPLACE INTO song_originals(song_key, video_id, source, found_at) VALUES (?, ?, ?, ?)",
                        (key, pick, source, time.time()))
        return pick

    def purge_cache(self) -> None:
        self.db.execute("DELETE FROM search_cache WHERE fetched_at < ?", (time.time() - SEARCH_TTL,))
        self.db.execute("DELETE FROM video_cache WHERE fetched_at < ?", (time.time() - VIDEO_TTL,))

    async def aclose(self) -> None:
        await self.client.aclose()
