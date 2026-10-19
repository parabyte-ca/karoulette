import asyncio

import httpx
import pytest

from app.db import Database
from app.youtube import SearchUnavailable, YouTubeService, parse_iso_duration


def test_parse_iso_duration():
    assert parse_iso_duration("PT4M13S") == 253
    assert parse_iso_duration("PT1H2M") == 3720
    assert parse_iso_duration(None) is None


def make_service(handler, **kw):
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return YouTubeService(Database(":memory:"), api_key="k", client=client, **kw)


def test_search_uses_api_then_cache():
    calls = []

    def handler(request):
        calls.append(request.url.path)
        if request.url.path.endswith("/search"):
            assert request.url.params["q"] == "bohemian rhapsody karaoke"
            assert request.url.params["videoEmbeddable"] == "true"
            return httpx.Response(200, json={"items": [{"id": {"videoId": "aaaaaaaaaaa"}, "snippet": {"title": "X"}},
                                                       {"id": {"videoId": "bbbbbbbbbbb"}, "snippet": {"title": "Y"}}]})
        return httpx.Response(200, json={"items": [
            {"id": "aaaaaaaaaaa", "snippet": {"title": "X", "channelTitle": "C"},
             "contentDetails": {"duration": "PT3M"}, "status": {"embeddable": True}},
            {"id": "bbbbbbbbbbb", "snippet": {"title": "Y"}, "contentDetails": {"duration": "PT3M"},
             "status": {"embeddable": False}}]})

    yt = make_service(handler)
    res = asyncio.run(yt.search("Bohemian  Rhapsody"))
    assert [r["video_id"] for r in res["results"]] == ["aaaaaaaaaaa"]
    assert res["results"][0]["duration_s"] == 180
    again = asyncio.run(yt.search("bohemian rhapsody"))
    assert again["cached"] and len(calls) == 2
    assert yt.quota_status()["units_used"] == 101


def test_quota_exceeded_marks_exhausted():
    def handler(request):
        return httpx.Response(403, json={"error": {"errors": [{"reason": "quotaExceeded"}]}})

    yt = make_service(handler, enable_ytdlp=False)
    with pytest.raises(SearchUnavailable):
        asyncio.run(yt.search("anything"))
    q = yt.quota_status()
    assert q["exhausted"] and q["units_remaining"] == 0 and q["mode"] == "unavailable"


def test_quota_exhausted_falls_back_to_ytdlp(monkeypatch):
    def handler(request):
        return httpx.Response(403, json={"error": {"errors": [{"reason": "quotaExceeded"}]}})

    yt = make_service(handler)

    async def fake_ytdlp(query):
        return [{"video_id": "ccccccccccc", "title": "Fallback", "channel": "", "thumbnail": "",
                 "duration_s": 100, "embeddable": True, "verified": False}]

    monkeypatch.setattr(yt, "_ytdlp_search", fake_ytdlp)
    res = asyncio.run(yt.search("song"))
    assert res["source"] == "ytdlp" and res["warning"]
