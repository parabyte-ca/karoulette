"""Security hardening: login lockout, session revocation, PIN hashing, push endpoint allowlist, headers,
WebSocket origin check and token redaction in logs."""
import logging

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app import auth
from app.config import Settings
from app.main import _RedactTokens, create_app, push_endpoint_allowed

from .test_api import login


def test_wrong_pins_from_anywhere_lock_the_login(client):
    limits = client.app.state.limits
    limits["login"].limit = 1000  # pretend every attempt came from a different address
    for _ in range(20):
        assert client.post("/api/host/login", json={"pin": "0000"}).status_code == 401
    locked = client.post("/api/host/login", json={"pin": "4321"})
    assert locked.status_code == 429 and "Too many wrong PINs" in locked.json()["detail"]


def test_changing_the_pin_signs_out_other_screens(client):
    client.app.state.db.set_setting("host_pin_from_env", False)  # a PIN managed in Host admin
    login(client)
    stolen = dict(client.cookies)
    assert client.post("/api/host/pin", json={"current": "4321", "new": "longer-pin-9"}).status_code == 200
    assert client.get("/api/host/events").status_code == 200  # this screen got a fresh session
    client.cookies.clear()
    client.cookies.update(stolen)
    assert client.get("/api/host/events").status_code == 401


def test_legacy_pin_hash_still_works_and_is_upgraded():
    import hashlib
    legacy = "pbkdf2$abcd$" + hashlib.pbkdf2_hmac("sha256", b"1234", b"abcd", 200_000).hex()
    assert auth.verify_pin("1234", legacy) and not auth.verify_pin("9999", legacy)
    assert auth.needs_rehash(legacy)
    fresh = auth.hash_pin("1234")
    assert fresh.startswith(f"pbkdf2${auth.ITERATIONS}$") and auth.verify_pin("1234", fresh)
    assert not auth.needs_rehash(fresh)


@pytest.mark.parametrize("url, ok", [
    ("https://fcm.googleapis.com/fcm/send/abc", True),
    ("https://updates.push.services.mozilla.com/wpush/v2/abc", True),
    ("https://web.push.apple.com/QGx", True),
    ("https://wns2-bn3p.notify.windows.com/w/?token=x", True),
    ("https://192.168.2.15/api", False),
    ("https://fcm.googleapis.com.evil.example/x", False),
    ("https://fcm.googleapis.com:8443/x", False),
    ("http://fcm.googleapis.com/x", False),
    ("https://localhost/x", False),
])
def test_push_endpoints_must_be_a_push_service(url, ok):
    assert push_endpoint_allowed(url) is ok


def test_push_subscription_to_the_lan_is_refused(client):
    login(client)
    ev = client.post("/api/host/events", json={"name": "Fri"}).json()
    guest = client.post("/api/guest/join", json={"code": ev["join_code"], "name": "Eve"}).json()
    keys = {"p256dh": "B" + "A" * 86, "auth": "A" * 22}
    res = client.post("/api/guest/push", json={"endpoint": "https://192.168.2.15/x", "keys": keys},
                      headers={"Authorization": f"Bearer {guest['token']}"})
    assert res.status_code == 422


def test_security_headers(client):
    plain = client.get("/api/health")
    assert "frame-src https://www.youtube.com" in plain.headers["Content-Security-Policy"]  # enforced by default
    assert "Content-Security-Policy-Report-Only" not in plain.headers
    assert "camera=()" in plain.headers["Permissions-Policy"]
    assert "Strict-Transport-Security" not in plain.headers
    https = client.get("/api/health", headers={"X-Forwarded-Proto": "https"})
    assert https.headers["Strict-Transport-Security"].startswith("max-age=")


@pytest.mark.parametrize("mode,header", [("report", "Content-Security-Policy-Report-Only"), ("off", None)])
def test_csp_can_be_relaxed(tmp_path, monkeypatch, mode, header):
    monkeypatch.setenv("CSP_MODE", mode)
    app = create_app(Settings(data_path=tmp_path, host_pin="4321", static_dir=tmp_path / "static"), start_ticker=False)
    with TestClient(app) as c:
        headers = c.get("/api/health").headers
    assert "Content-Security-Policy" not in headers
    assert (header in headers) if header else not any(h.startswith("content-security-policy") for h in headers)


def test_host_websocket_refuses_other_sites(client):
    login(client)
    ev = client.post("/api/host/events", json={"name": "Fri"}).json()
    with pytest.raises(WebSocketDisconnect) as closed:
        with client.websocket_connect(f"/ws/{ev['join_code']}", headers={"Origin": "https://evil.example"}) as ws:
            ws.receive_json()
    assert closed.value.code == 4403
    with client.websocket_connect(f"/ws/{ev['join_code']}", headers={"Origin": "http://testserver"}) as ws:
        assert ws.receive_json()["type"] == "state"


def test_guest_tokens_are_redacted_from_access_logs():
    rec = logging.LogRecord("uvicorn.access", logging.INFO, "", 0, '%s - "%s %s" %d',
                            ("1.2.3.4", "WebSocket", "/ws/ABCDE?token=s3cr3t-value&x=1", 101), None)
    _RedactTokens().filter(rec)
    assert "s3cr3t" not in rec.getMessage() and "token=[redacted]&x=1" in rec.getMessage()
