"""Web Push: the VAPID key, encrypted delivery, who gets which alert, and the guest endpoints."""
import asyncio
import json
import os
import time

import http_ece
import httpx
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi.testclient import TestClient

from app.config import Settings
from app.db import Database
from app.main import create_app
from app.push import PushService, b64url, unb64url

from .conftest import StubYouTube, add


def phone():
    """A browser's push keys: (private key, subscription keys)."""
    key = ec.generate_private_key(ec.SECP256R1())
    raw = key.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
    auth = os.urandom(16)
    return key, {"p256dh": b64url(raw), "auth": b64url(auth)}


class Inbox:
    """A fake push service: records each delivery and answers with ``status``."""
    def __init__(self, status=201):
        self.status, self.requests = status, []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return httpx.Response(self.status)

    def client(self):
        return httpx.AsyncClient(transport=httpx.MockTransport(self))


def test_vapid_key_is_made_once_and_kept(tmp_path):
    db = Database(tmp_path / "k.db")
    first = PushService(db).public_key
    assert len(unb64url(first)) == 65 and unb64url(first)[0] == 4
    assert PushService(db).public_key == first
    push = PushService(db)
    db.set_setting("vapid_private_pem", "")  # a backup from before push alerts
    push.load_key()
    assert push.public_key != first and db.get_setting("vapid_private_pem")


def test_send_encrypts_for_the_phone_and_signs(engine, make_event):
    ev, (alex, *_) = make_event()
    key, keys = phone()
    engine.save_push(alex["id"], "https://push.example/abc", keys["p256dh"], keys["auth"])
    sub = engine.db.one("SELECT * FROM push_subscriptions")
    inbox = Inbox()
    push = PushService(engine.db, "mailto:host@example.com", client=inbox.client())
    assert asyncio.run(push.send(sub, {"title": "Hi", "body": "There"})) == 201
    req = inbox.requests[0]
    assert req.headers["content-encoding"] == "aes128gcm" and req.headers["ttl"] == "900"
    assert req.headers["authorization"].startswith("vapid t=") and push.public_key in req.headers["authorization"]
    plain = http_ece.decrypt(req.content, private_key=key, auth_secret=unb64url(keys["auth"]), version="aes128gcm")
    assert json.loads(plain) == {"title": "Hi", "body": "There"}


def test_gone_subscription_is_forgotten(engine, make_event):
    ev, (alex, *_) = make_event()
    _, keys = phone()
    engine.save_push(alex["id"], "https://push.example/gone", keys["p256dh"], keys["auth"])
    push = PushService(engine.db, client=Inbox(410).client())
    asyncio.run(push.send(engine.db.one("SELECT * FROM push_subscriptions"), {"title": "x"}))
    assert engine.db.one("SELECT COUNT(*) AS n FROM push_subscriptions")["n"] == 0


def test_unusable_keys_are_dropped_without_sending(engine, make_event):
    ev, (alex, *_) = make_event()
    engine.save_push(alex["id"], "https://push.example/bad", "x" * 30, "y" * 12)
    inbox = Inbox()
    push = PushService(engine.db, client=inbox.client())
    assert asyncio.run(push.send(engine.db.one("SELECT * FROM push_subscriptions"), {"title": "x"})) == 0
    assert not inbox.requests and not engine.db.one("SELECT 1 FROM push_subscriptions")


def subscribe_all(engine, guests):
    for g in guests:
        _, keys = phone()
        engine.save_push(g["id"], f"https://push.example/{g['id']}", keys["p256dh"], keys["auth"])


def targets(engine, jobs):
    return sorted(engine._guest(s["guest_id"])["display_name"] for s, _ in jobs)


def test_turn_alerts_go_to_the_singer_and_respect_prefs(engine, make_event):
    ev, (alex, blake, casey) = make_event()
    subscribe_all(engine, (alex, blake, casey))
    for g in (alex, blake, casey):
        add(engine, g)
    engine.play_next(ev)
    jobs = engine.push_jobs(engine.drain())
    titles = {engine._guest(s["guest_id"])["display_name"]: p["title"] for s, p in jobs}
    assert titles == {"Alex": "🎤 You're up!", "Blake": "You're up next!", "Casey": "🎤 Two songs to go"}
    assert all(p["url"].startswith("/join/") for _, p in jobs)

    engine.set_push_prefs(blake["id"], f"https://push.example/{blake['id']}", {"turn": False})
    engine.player_ended(ev, engine.get_event(ev)["now_playing_item_id"])
    assert "Blake" not in targets(engine, engine.push_jobs(engine.drain()))


def test_two_to_go_skips_whoever_was_just_told(engine, make_event):
    ev, (alex, blake) = make_event(names=("Alex", "Blake"))
    for _ in range(2):
        add(engine, alex)
        add(engine, blake)
    engine.play_next(ev)  # Alex sings, Blake next, then Alex again
    kinds = [(m["message"]["type"], engine._guest(m["guest_id"])["display_name"]) for m in engine.drain() if m["guest_id"]]
    assert ("two_to_go", "Alex") not in kinds and ("you_are_next", "Blake") in kinds


def test_superset_vote_skips_the_caller_and_playlist_needs_songs(engine, make_event):
    ev, (alex, blake, casey) = make_event()
    subscribe_all(engine, (alex, blake, casey))
    msg = {"event_id": ev, "guest_id": None,
           "message": {"type": "superset_vote", "data": {"status": "open", "name": "Alex", "guest_id": alex["id"]}}}
    assert targets(engine, engine.push_jobs([msg])) == ["Blake", "Casey"]

    ended = {"event_id": ev, "guest_id": None, "message": {"type": "event_ended", "data": {}}}
    assert engine.push_jobs([ended]) == []
    add(engine, alex)
    engine.play_next(ev)
    engine.player_ended(ev, engine.get_event(ev)["now_playing_item_id"])
    jobs = engine.push_jobs([ended])
    assert targets(engine, jobs) == ["Alex", "Blake", "Casey"] and jobs[0][1]["url"].startswith("/playlist/")


def test_guest_push_endpoints_and_delivery(tmp_path):
    settings = Settings(data_path=tmp_path, host_pin="4321", static_dir=tmp_path / "static")
    inbox = Inbox()
    db_path = tmp_path / "karoulette.db"
    push = PushService(Database(db_path), client=inbox.client())
    app = create_app(settings, start_ticker=False, youtube=StubYouTube(Database(db_path)), push=push)
    with TestClient(app) as c:
        assert c.get("/api/public/push-key").json()["key"] == push.public_key
        c.post("/api/host/login", json={"pin": "4321"})
        ev = c.post("/api/host/events", json={"name": "Fri", "config": {"superset_chance": 0}}).json()
        guest = c.post("/api/guest/join", json={"code": ev["join_code"], "name": "Alex"}).json()
        h = {"Authorization": f"Bearer {guest['token']}"}
        key, keys = phone()
        assert c.post("/api/guest/push", json={"endpoint": "http://bad", "keys": keys}, headers=h).status_code == 422
        r = c.post("/api/guest/push", json={"endpoint": "https://push.example/1", "keys": keys,
                                            "prefs": {"playlist": False}}, headers=h)
        assert r.json()["prefs"] == {"turn": True, "superset": True, "duet": True, "playlist": False}
        r = c.put("/api/guest/push/prefs", json={"endpoint": "https://push.example/1", "prefs": {"duet": False}}, headers=h)
        assert r.json()["prefs"]["duet"] is False and r.json()["prefs"]["playlist"] is False

        c.post(f"/api/host/events/{ev['id']}/actions/start")
        assert c.post("/api/guest/queue", json={"video_id": "abcdefghijk"}, headers=h).status_code == 200
        for _ in range(100):  # pushes go out in the background
            if inbox.requests:
                break
            time.sleep(0.02)
        plain = http_ece.decrypt(inbox.requests[0].content, private_key=key,
                                 auth_secret=unb64url(keys["auth"]), version="aes128gcm")
        assert json.loads(plain)["title"] == "🎤 You're up!"

        assert c.post("/api/guest/push/off", json={"endpoint": "https://push.example/1"}, headers=h).json()["ok"]
        assert c.put("/api/guest/push/prefs", json={"endpoint": "https://push.example/1", "prefs": {}},
                     headers=h).status_code == 404


def test_song_suggestions_alert_under_duets(engine, make_event):
    ev, (alex, blake, _) = make_event()
    subscribe_all(engine, (blake,))
    engine.suggest_song(alex["id"], blake["id"], {"video_id": "abcdefghijk", "title": "ABBA - Waterloo (Karaoke)"})
    [(sub, payload)] = engine.push_jobs(engine.drain())
    assert payload["title"] == "🎁 Song suggestion" and "Alex suggests" in payload["body"]
    engine.set_push_prefs(blake["id"], sub["endpoint"], {"duet": False})
    engine.suggest_song(alex["id"], blake["id"], {"video_id": "abcdefghij2", "title": "Queen - Bohemian Rhapsody"})
    assert engine.push_jobs(engine.drain()) == []
