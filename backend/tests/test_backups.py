"""Backups from Host admin, restoring them (from the list or an upload), and the health check."""
from .test_api import login


def test_health_check_reports_the_database(client):
    body = client.get("/api/health").json()
    assert body["status"] == "ok" and body["database"] == "ok" and "uptime_s" in body


def test_backup_download_and_restore(client):
    login(client)
    client.post("/api/host/events", json={"name": "Keep me"})
    made = client.post("/api/host/backups").json()
    assert made["name"].startswith("manual-") and made["size"] > 0
    assert client.get(f"/api/host/backups/{made['name']}").content[:16] == b"SQLite format 3\x00"

    client.post("/api/host/events", json={"name": "Added after the backup"})
    assert len(client.get("/api/host/events").json()) == 2
    restored = client.post(f"/api/host/backups/{made['name']}/restore").json()
    assert restored["safety_backup"].startswith("pre-restore-")
    assert [e["name"] for e in client.get("/api/host/events").json()] == ["Keep me"]
    assert client.get("/api/host/session").json()["authenticated"]          # still signed in
    names = [b["name"] for b in client.get("/api/host/backups").json()["backups"]]
    assert made["name"] in names and restored["safety_backup"] in names

    # Upload a backup file to restore it (the safety copy from just now brings "Added after…" back).
    data = client.get(f"/api/host/backups/{restored['safety_backup']}").content
    res = client.post("/api/host/backups-upload", content=data, headers={"Content-Type": "application/octet-stream"})
    assert res.status_code == 200, res.text
    assert len(client.get("/api/host/events").json()) == 2


def test_backup_safety_checks(client):
    login(client)
    assert client.get("/api/host/backups/..%2Fsecret.key").status_code in (400, 404)
    assert client.post("/api/host/backups/nope.db/restore").status_code == 404
    bad = client.post("/api/host/backups-upload", content=b"not a database" * 10)
    assert bad.status_code == 400 and "isn't a Karoulette database" in bad.json()["detail"]
    client.post("/api/host/logout")
    assert client.get("/api/host/backups").status_code == 401
    assert client.post("/api/host/backups-upload", content=b"x").status_code == 401
