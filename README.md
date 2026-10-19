# KaraokeQueue
> Self-hosted, multi-user karaoke night: guests join by QR code, take turns in a fixed rotation, spin a theme and queue YouTube karaoke videos that play on the TV.

![Version](https://img.shields.io/badge/version-0.1.0-blue)

## Overview
KaraokeQueue runs your karaoke party from one TV and everyone's phones. The TV (host screen) plays YouTube karaoke videos through the official YouTube player in a browser signed into YouTube Premium, so there are no ads. Guests scan a QR code, pick a display name and wait for their turn; when it comes, a theme randomizer spins and they search for a karaoke version that fits. Everything syncs in real time and survives a container restart.

## Features
- **Host / TV screen** (`/host`): full-screen YouTube player, current singer, up next, queue, round and theme, QR code, join URL and code. High-contrast dark layout readable from across the room.
- **YouTube Premium checklist** on first load of the TV screen in each browser session.
- **Host controls**: start event, pause/resume rotation, play/pause video, skip song, skip turn, force a theme spin, force or cancel a Superset, reorder or remove songs, remove or skip guests, end event. Keyboard shortcuts on the TV: <kbd>Space</kbd> play/pause, <kbd>N</kbd> skip song, <kbd>S</kbd> spin, <kbd>P</kbd> pause rotation, <kbd>H</kbd> show/hide controls.
- **Guest phone UI** (`/join`): mobile-first, no accounts (session token in `localStorage`), turn status ("3 turns until you pick", "Your turn!"), current theme, song search, full queue, "you're up next" and "you're singing now" prompts with vibration.
- **Fixed rotation** in join order. Late joiners go to the end. Guests can leave; the host can remove or skip them.
- **Turn flow**: announce the singer → animated theme spin → pick within the turn timer (default 90 s) → next singer. Timeouts skip with a notice.
- **Themes** with a CRUD admin page (name, description, weight, enabled). No theme repeats back to back; optionally avoid the last _N_ themes. Seeded with 80s, Duets, From a Soundtrack, Canadiana, 90s, Power Ballads, Guilty Pleasures, One-Hit Wonders.
- **Superset rounds**: at the start of each round there is a configurable chance (default 15 %) of a Superset: one theme for everyone that round, a gold banner and sweep animation on the TV and phones, and guests/host can flag off-theme picks. Host can force the next round to be a Superset or cancel one.
- **YouTube search** via the Data API v3 (`type=video`, `videoEmbeddable=true`, `videoSyndicated=true`, configurable SafeSearch), "karaoke" added automatically, 24-hour SQLite cache, quota meter in admin and graceful `quotaExceeded` handling. Falls back to **yt-dlp metadata-only search** (never downloads) when there's no key or the quota is gone.
- **Pre-queue checks** with `videos.list`: duration and embeddability are confirmed before a song is added; optional maximum length.
- **Embed errors** (IFrame codes 101/150 and others) auto-skip the song, notify the singer and give them a bonus re-pick ahead of the rotation.
- **Real-time sync** over WebSockets; full state persisted in SQLite so a restart resumes the event, including the turn timer.
- **Multiple events** with a start/end lifecycle and a short join code. Song history per event with **CSV export**.
- **Duplicate prevention** per event (host-configurable).
- **Security**: host PIN (PBKDF2-hashed, HttpOnly signed session cookie), rate-limited search/join/login, validated inputs, API key never sent to browsers.
- Automated tests for rotation, Superset and queue logic, plus a demo seed script.

## Requirements
- Docker with Compose v2 (TrueNAS SCALE 24.10+ works out of the box)
- A browser on the TV signed into **YouTube Premium** (Chrome or Edge recommended)
- Optional but recommended: a **YouTube Data API v3** key ([create one](https://console.cloud.google.com/apis/library/youtube.googleapis.com), then _Credentials → Create credentials → API key_; restrict it to the YouTube Data API v3)
- Guests' phones on a network that can reach the server (same Wi-Fi, or a reverse proxy / tunnel)

## Setup
Run once on first deployment. It is safe to re-run.

```bash
git clone https://github.com/parabyte-ca/karoulette.git karaokequeue
cd karaokequeue
./setup.sh
```

`setup.sh` creates `.env` from `.env.example`, asks for the port, data folder, host PIN, YouTube API key and public URL, generates a `SECRET_KEY`, fixes the data folder owner, builds `parabyte-ca/karaokequeue:<version>` + `:latest`, starts the container and waits for the health check.

Non-interactive (automation friendly):

```bash
HOST_PIN=9731 YOUTUBE_API_KEY=AIza... KQ_DATA_DIR=/mnt/tank/apps/karaokequeue ./setup.sh -y
```

**TrueNAS SCALE notes**
- Clone into a dataset, e.g. `/mnt/tank/apps/karaokequeue-src`, and point `KQ_DATA_DIR` at a separate dataset such as `/mnt/tank/apps/karaokequeue`.
- The container runs as UID/GID `568` (the TrueNAS `apps` user) by default; change `PUID`/`PGID` in `.env` if needed.
- Default port is **8095** (from the parabyte-ca port registry).
- To use prebuilt images instead of building on the NAS, set `KQ_IMAGE=ghcr.io/parabyte-ca/karaokequeue` in `.env`.

## Update
```bash
./update.sh
```
Pulls the latest code (`git pull --ff-only`), rebuilds the image (or pulls it when `KQ_IMAGE` points at GHCR), restarts with `docker compose up -d` and waits for the health check. The database lives in `KQ_DATA_DIR`, so running events resume where they left off.

## Configuration
All settings live in `.env` (see `.env.example`).

| Variable | Default | Purpose |
|---|---|---|
| `KQ_PORT` | `8095` | Host port (container listens on 8000) |
| `KQ_DATA_DIR` | `./data` | Host folder for `karaokequeue.db` (mounted at `/data`) |
| `PUID` / `PGID` | `568` | User the container runs as |
| `HOST_PIN` | _(required)_ | Host PIN or password, 4+ characters. When set, it always wins over a PIN changed in admin |
| `YOUTUBE_API_KEY` | _(blank)_ | YouTube Data API v3 key. Blank = yt-dlp fallback search |
| `YOUTUBE_DAILY_QUOTA` | `10000` | Daily quota used for the remaining-quota estimate |
| `PUBLIC_BASE_URL` | _(blank)_ | URL used in the QR code, e.g. `https://karaoke.example.ca`. Blank = the address the TV used |
| `SECRET_KEY` | _(generated)_ | Signs host session cookies |
| `ENABLE_YTDLP` | `true` | Allow the yt-dlp metadata fallback |
| `KQ_IMAGE` / `KQ_TAG` | `parabyte-ca/karaokequeue` / `latest` | Image to run |
| `TZ` | `America/Toronto` | Container time zone |

**Per-event settings** (Host admin → Events): turn timer (15 to 600 s, default 90), Superset chance (default 15 %), recent-theme window (default 3), prevent duplicate songs (default on), SafeSearch (off / moderate / strict), longest video allowed (default 15 min), autoplay.

**Quota maths**: a new search costs about 101 units (100 for `search.list` + 1 for `videos.list`), so the default 10,000-unit daily quota covers roughly 99 fresh searches; repeated searches within 24 hours are served from the cache for free. Quota resets at midnight Pacific time.

**Reverse proxy** (Nginx Proxy Manager, Cloudflare Tunnel): enable **WebSockets support**, forward to `http://<nas-ip>:8095`, and set `PUBLIC_BASE_URL` so the QR code uses the public address.

## Usage

### First event checklist
1. **Sign in to YouTube Premium** in the browser on the TV (Chrome/Edge). Open youtube.com and confirm the Premium logo.
2. Open `http://<server>:8095/host` on that browser and enter the host PIN.
3. **Create the event** (e.g. "Saturday Singalong"), then tick the Premium checklist and press **Continue** (this click also lets the browser autoplay with sound). Press <kbd>F11</kbd> or the ⛶ button for full screen.
4. **Show the QR code**: it's on the TV with the join URL and a five-character code.
5. **Guests join**: scan, enter a display name, done. They sing in the order they joined.
6. Press **▶ Start event**. The first singer is announced, the theme spins, and they pick a song on their phone.
7. Songs play automatically in order. Use the control bar (move the mouse to show it) to skip, pause or spin.
8. When you're done, **End event**, then export the song history from Host admin → Events → _Export song history (CSV)_.

### Host admin (`/host/admin`)
- **Events**: settings, singers (skip/remove), theme history, CSV export, delete.
- **Themes**: add, edit, weight, enable/disable, delete.
- **YouTube**: search mode and estimated quota left today.
- **Security**: change the PIN (when not set by `HOST_PIN`), sign out.

### Demo data
```bash
docker exec karaokequeue python -m scripts.seed_demo
```
Creates a "Demo Night" event with six guests, a few queued songs and history, and prints guest tokens. Demo video IDs are examples and may not all be embeddable; the embed error handler will skip any that aren't.

## Architecture

```
 TV browser (/host, YouTube Premium)          Guest phones (/join)
   │ YouTube IFrame Player (direct)                │
   └──────────── HTTPS + WebSocket ────────────────┘
                         │
            FastAPI (uvicorn, single process)
            ├─ REST  /api/public · /api/guest (bearer token) · /api/host (PIN cookie)
            ├─ WS    /ws/{join_code}  → full state snapshot + typed events
            ├─ Engine: rotation, rounds, Supersets, queue, timers (persisted deadlines)
            ├─ YouTube service: Data API v3 → yt-dlp fallback, SQLite cache, quota ledger
            └─ SQLite (WAL) in /data  ·  serves the built React SPA
```

- **Backend** (`backend/app`): `engine.py` is the only place event state changes; every mutation runs under one asyncio lock, is written to SQLite, and pushes typed messages (`guest_joined`, `turn_changed`, `theme_spun`, `song_queued`, `now_playing`, `round_changed`, `superset`, `notice`…) followed by a full `state` snapshot. `logic.py` holds the pure rotation/theme/Superset/queue rules that the tests target. A 0.5 s ticker advances phases (announce → spin → choose → timeout) from persisted deadlines, so a restart picks up exactly where it stopped.
- **Frontend** (`frontend/src`): React + Vite, no UI framework. `HostScreen` (TV), `HostAdmin`, `JoinApp` (phone). `useEventSocket` reconnects with backoff and corrects for clock skew.
- **YouTube**: playback only through the official IFrame Player on the host page; nothing is downloaded, proxied or ripped. Ad-free playback relies on the TV browser's Premium sign-in. Guests never play video.
- **Data model**: `events`, `guests`, `themes`, `rounds`, `turns` (theme history), `queue_items` (song history), `flags`, `search_cache`, `video_cache`, `quota_ledger`, `settings`. See [`docs/PLAN.md`](docs/PLAN.md).
- **Single worker by design**: timers and WebSocket rooms live in one process. One venue per instance is the target.

### Development
```bash
# Backend (http://localhost:8095)
cd backend && python -m venv .venv && . .venv/bin/activate
pip install -r requirements-dev.txt
DATA_PATH=./data HOST_PIN=1234 uvicorn --factory app.main:create_app --reload --port 8095
python -m pytest -q

# Frontend (http://localhost:5173, proxies /api and /ws to :8095)
cd frontend && npm install && npm run dev
```

CI (`.github/workflows/docker.yml`) runs the backend tests and frontend build, then builds a multi-arch image and pushes `ghcr.io/parabyte-ca/karaokequeue:<version>` and `:latest` on `main` (and `:<semver>` on `v*` tags).

## Changelog
See [CHANGELOG.md](CHANGELOG.md).

## License
Proprietary. © 2026 parabyte-ca. All rights reserved.
