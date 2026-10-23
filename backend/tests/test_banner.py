"""The Main Stage skin's banner, uploaded banners and link previews for join links."""
import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app

from .conftest import StubYouTube
from .test_api import login

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64


def test_main_stage_has_a_built_in_banner(engine):
    assert engine.appearance()["banner"] is None
    look = engine.set_scheme("stage")
    assert look["banner"] == "/banners/main-stage.jpg" and look["og_image"] == "/banners/main-stage-og.jpg"


def test_uploaded_banner_replaces_it_and_can_show_on_every_skin(engine):
    engine.set_scheme("stage")
    look = engine.set_banner("png")
    assert look["custom_banner"] and look["banner"].startswith("/api/public/banner?v=")
    engine.set_scheme("neon")
    assert engine.appearance()["banner"] is None          # other skins only when asked
    assert engine.set_banner_all(True)["banner"].startswith("/api/public/banner")
    engine.set_banner(None)
    assert engine.appearance()["banner"] is None          # neon has no built-in banner


@pytest.fixture
def site(tmp_path):
    static = tmp_path / "static"
    (static / "banners").mkdir(parents=True)
    (static / "index.html").write_text("<html><head><title>Karoulette</title></head><body></body></html>")
    (static / "banners" / "main-stage-og.jpg").write_bytes(b"\xff\xd8\xff" + b"\x00" * 16)
    settings = Settings(data_path=tmp_path / "data", host_pin="4321", static_dir=static,
                        public_base_url="https://karaoke.example.ca")
    from app.db import Database
    app = create_app(settings, start_ticker=False, youtube=StubYouTube(Database(":memory:")))
    with TestClient(app) as c:
        yield c


def test_banner_upload_endpoints(site):
    assert site.put("/api/host/appearance/banner", content=PNG).status_code == 401
    login(site)
    bad = site.put("/api/host/appearance/banner", content=b"<svg onload=alert(1)>")
    assert bad.status_code == 400 and "JPEG, PNG or WebP" in bad.json()["detail"]
    assert site.put("/api/host/appearance/banner", content=b"\xff\xd8\xff" + b"0" * 8_000_001).status_code == 413
    look = site.put("/api/host/appearance/banner", content=PNG).json()
    assert look["custom_banner"] and look["banner"] is None   # neon: not shown until asked
    assert look["custom_url"].startswith("/api/public/banner?v=")
    look = site.put("/api/host/appearance/banner-all", json={"on": True}).json()
    got = site.get(look["banner"])
    assert got.status_code == 200 and got.headers["content-type"] == "image/png" and got.content == PNG
    assert "immutable" in got.headers["cache-control"]
    assert site.delete("/api/host/appearance/banner").json()["custom_banner"] is False
    assert site.get("/api/public/banner").status_code == 404


def test_join_links_get_a_preview_with_the_event_and_banner(site):
    login(site)
    site.put("/api/host/appearance", json={"scheme": "stage"})
    code = site.post("/api/host/events", json={"name": "Friday <Singalong>"}).json()["join_code"]
    page = site.get(f"/join/{code}").text
    assert '<meta property="og:title" content="Join Friday &lt;Singalong&gt; on Karoulette" />' in page
    assert f"code {code}" in page
    assert 'content="https://karaoke.example.ca/banners/main-stage-og.jpg"' in page
    assert site.get("/banners/main-stage-og.jpg").status_code == 200
    plain = site.get("/join/NOPE1").text                      # unknown code: the generic preview
    assert '<meta property="og:title" content="Karoulette" />' in plain
    assert "og:image" in site.get("/host/admin").text         # every app page gets the tags
