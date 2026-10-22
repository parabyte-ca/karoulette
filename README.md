# Karoulette
> Karaoke meets roulette. Self-hosted, multi-user karaoke night: guests join by QR code, take turns in a fixed rotation, spin a theme and queue YouTube karaoke videos that play on the TV.

![Version](https://img.shields.io/badge/version-0.6.0-blue)

## Overview
Karoulette runs your karaoke party from one TV and everyone's phones. The TV (host screen) plays YouTube karaoke videos through the official YouTube player in a browser signed into YouTube Premium, so there are no ads. Guests scan a QR code, pick a display name and wait for their turn; when it comes, a theme randomizer spins and they search for a karaoke version that fits. Everything syncs in real time and survives a container restart.

## Features
- **Host / TV screen** (`/host`): full-screen YouTube player, current singer, up next, queue, round and theme, QR code, join URL and code. High-contrast dark layout readable from across the room.
- **YouTube Premium checklist** on first load of the TV screen in each browser session.
- **Host controls**: start event, play/pause video, skip song, re-spin the round's theme, force or cancel a Superset, "play next" or remove any song, move singers up/down the order, remove guests, end event. Keyboard shortcuts on the TV: <kbd>Space</kbd> play/pause, <kbd>N</kbd> skip song, <kbd>S</kbd> re-spin, <kbd>H</kbd> show/hide controls.
- **Guest phone UI** (`/join`): mobile-first, no accounts (session token in `localStorage`), song search that's always open, "My songs" with each song's place in the queue, the round's theme, full queue and singer order, "you're up next" and "you're singing now" prompts with vibration.
- **Add songs any time, as many as you like**: no waiting for a turn. The queue is a fair round-robin: each singer gets one song per round, and every round follows the singer order. A singer with five songs queued sings one per round, interleaved with everyone else.
- **Singer order** is join order. **New singers** who join after singing has started are slotted in **next in line** (right after whoever is on the mic, behind any other newcomers still waiting), and the TV announces them with a "NEW SINGER!" banner when their first song starts. Guests can leave; the host can move singers up or down or remove them.
- **Your songs, your way**: a singer can move one of their songs ahead of their own others, remove it, or, when it's up next, tap **"Not ready? Let the next singer go first"** to let exactly one song go ahead.
- **Themes** with a CRUD admin page (name, description, weight, enabled). No theme repeats back to back; optionally avoid the last _N_ themes. Seeded with 80s, Duets, From a Soundtrack, Canadiana, 90s, Power Ballads, Guilty Pleasures, One-Hit Wonders.
- **One theme per round**: each pass through the singer order spins a theme (animated on the TV and phones) as a suggestion for everyone's picks.
- **Superset rounds**: at the start of each round there is a configurable chance (default 15 %) of a Superset: one theme for everyone that round, a gold banner and sweep animation on the TV and phones, and guests/host can flag off-theme picks. Host can force the next round to be a Superset or cancel one.
- **YouTube search** via the Data API v3 (`type=video`, `videoEmbeddable=true`, `videoSyndicated=true`, configurable SafeSearch), "karaoke" added automatically, 24-hour SQLite cache, quota meter in admin and graceful `quotaExceeded` handling. Falls back to **yt-dlp metadata-only search** (never downloads) when there's no key or the quota is gone.
- **Pre-queue checks** with `videos.list`: duration and embeddability are confirmed before a song is added; optional maximum length.
- **Embed errors** (IFrame codes 101/150 and others) auto-skip the song, notify the singer, and their next pick plays straight away.
- **Real-time sync** over WebSockets; full state persisted in SQLite so a restart resumes the event, queue and all.
- **Multiple events** with a start/end lifecycle and a short join code. Song history per event with **CSV export**.
- **Duplicate prevention** per event (host-configurable).
- **Five colour schemes**, switchable live from Host admin → Appearance (TV, phones and admin repaint instantly, even mid-event): **Neon Night** (original), **On Air** (broadcast studio), **Synthwave Sunset** (80s outrun), **Velvet Lounge** (jazz club) and **Northern Lights** (Canadian aurora). Each has its own background art and display font, and all stay dark and high-contrast.
- **Updates from the admin page** (same model as project-glasshaus): a daily check for new GitHub releases, the running version and any new release shown in Host admin, release notes, and a one-click **Upgrade** that a small host helper carries out with a database backup, health check and automatic rollback.
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
git clone https://github.com/parabyte-ca/karoulette.git karoulette
cd karoulette
./setup.sh
```

`setup.sh` creates `.env` from `.env.example`, asks for the port, data folder, host PIN, YouTube API key and public URL, generates a `SECRET_KEY`, fixes the data folder owner, builds `parabyte-ca/karoulette:<version>` + `:latest`, starts the container and waits for the health check.

Non-interactive (automation friendly):

```bash
HOST_PIN=9731 YOUTUBE_API_KEY=AIza... KQ_DATA_DIR=/mnt/tank/apps/karoulette ./setup.sh -y
```

**TrueNAS SCALE notes**
- Clone into a dataset, e.g. `/mnt/tank/apps/karoulette-src`, and point `KQ_DATA_DIR` at a separate dataset such as `/mnt/tank/apps/karoulette`.
- The container runs as UID/GID `568` (the TrueNAS `apps` user) by default; change `PUID`/`PGID` in `.env` if needed.
- Default port is **8095** (from the parabyte-ca port registry).
- To use prebuilt images instead of building on the NAS, set `KQ_IMAGE=ghcr.io/parabyte-ca/karoulette` in `.env`.

## Update
```bash
./update.sh
```
Pulls the latest code (`git pull --ff-only`), backs up the database (`<data folder>/backups/`, last 10 kept), rebuilds the image (or pulls it when `KQ_IMAGE` points at GHCR), restarts and waits for the health check. If the new version isn't healthy it goes back to the previous image and code. Running events resume where they left off. `./update.sh --no-git` rebuilds the current checkout without pulling.

**Upgrading from KaraokeQueue (0.4.x and earlier)**: the project was renamed to Karoulette in 0.5.0. Just update as usual (admin Upgrade button or `./update.sh`): the container (`karaokequeue` → `karoulette`), image (`parabyte-ca/karaokequeue` → `parabyte-ca/karoulette`, also fixed in `.env`) and database file (`karaokequeue.db` → `karoulette.db`) move over automatically, and the database is backed up first. Your clone folder keeps its old name; that's fine. Prebuilt images are now published as `ghcr.io/parabyte-ca/karoulette`.

### One-click upgrades from Host admin → Updates
Karoulette checks GitHub once a day for a new release and shows it in Host admin (a gold "vX.Y.Z available" badge and the **Updates** tab, with release notes). The app runs in a container and can't rebuild itself, so a small helper on the host does the work:

```bash
sudo ./scripts/upgrade-agent.sh --install   # setup.sh offers this too
```

- On **TrueNAS SCALE** it adds a cron job (System → Advanced Settings → Cron Jobs) through `midclt`, so it survives TrueNAS updates. Elsewhere it uses `/etc/cron.d` or a systemd timer.
- It runs every 15 minutes as root and only acts when you press **Upgrade**: it runs `update.sh` (backup, rebuild, health check, rollback) and reports progress and the log back to the admin page.
- `--print` shows what to schedule by hand, `--uninstall` removes it, `--every N` changes the interval.
- The app and helper talk through the upgrade folder (`KQ_UPGRADE_FOLDER`, default `./upgrade`), using the same protocol as project-glasshaus.

Releases are published automatically by `.github/workflows/release.yml` whenever `VERSION` changes on `main` (tag `vX.Y.Z` plus a GitHub Release with that version's CHANGELOG section). Before the first Release exists, the check reads `VERSION` and `CHANGELOG.md` from `main`.

## Configuration
All settings live in `.env` (see `.env.example`).

| Variable | Default | Purpose |
|---|---|---|
| `KQ_PORT` | `8095` | Host port (container listens on 8000) |
| `KQ_DATA_DIR` | `./data` | Host folder for `karoulette.db` (mounted at `/data`) |
| `PUID` / `PGID` | `568` | User the container runs as |
| `HOST_PIN` | _(required)_ | Host PIN or password, 4+ characters. When set, it always wins over a PIN changed in admin |
| `YOUTUBE_API_KEY` | _(blank)_ | YouTube Data API v3 key. Blank = yt-dlp fallback search |
| `YOUTUBE_DAILY_QUOTA` | `10000` | Daily quota used for the remaining-quota estimate |
| `PUBLIC_BASE_URL` | _(blank)_ | Site address used in the QR code, e.g. `https://karaoke.example.ca` (just the root; a pasted `/join` or `/host` is stripped). Blank = the address the TV used |
| `SECRET_KEY` | _(generated)_ | Signs host session cookies |
| `ENABLE_YTDLP` | `true` | Allow the yt-dlp metadata fallback |
| `UPDATE_CHECK` | `true` | Daily check for new releases (Host admin → Updates) |
| `SOURCE_REPO` | `parabyte-ca/karoulette` | GitHub repository releases are checked against |
| `KQ_UPGRADE_FOLDER` | `./upgrade` | Host folder shared with the upgrade helper |
| `KQ_IMAGE` / `KQ_TAG` | `parabyte-ca/karoulette` / `latest` | Image to run |
| `TZ` | `America/Toronto` | Container time zone |

**Per-event settings** (Host admin → Events): Superset chance (default 15 %), recent-theme window (default 3), prevent duplicate songs (default on), SafeSearch (off / moderate / strict), longest video allowed (default 15 min), autoplay.

**Quota maths**: a new search costs about 101 units (100 for `search.list` + 1 for `videos.list`), so the default 10,000-unit daily quota covers roughly 99 fresh searches; repeated searches within 24 hours are served from the cache for free. Quota resets at midnight Pacific time.

**Reverse proxy** (Nginx Proxy Manager, Cloudflare Tunnel): enable **WebSockets support**, forward to `http://<nas-ip>:8095`, and set `PUBLIC_BASE_URL` so the QR code uses the public address.

## Usage

### First event checklist
1. **Sign in to YouTube Premium** in the browser on the TV (Chrome/Edge). Open youtube.com and confirm the Premium logo.
2. Open `http://<server>:8095/host` on that browser and enter the host PIN.
3. **Create the event** (e.g. "Saturday Singalong"), then tick the Premium checklist and press **Continue** (this click also lets the browser autoplay with sound). Press <kbd>F11</kbd> or the ⛶ button for full screen.
4. **Show the QR code**: it's on the TV with the join URL and a five-character code.
5. **Guests join and add songs**: scan, enter a display name, and search. They can queue as many songs as they like, even before you start; the singer order is the order they joined.
6. Press **▶ Start event**. Round 1's theme spins and the first song plays.
7. Songs play automatically, one per singer per round. Latecomers slot in next in line and get a "NEW SINGER!" welcome. Use the control bar (move the mouse to show it) to skip, re-spin or put a song next.
8. When you're done, **End event**, then export the song history from Host admin → Events → _Export song history (CSV)_.

### Host admin (`/host/admin`)
- **Events**: settings, singer order (move up/down, remove), round themes, CSV export, delete.
- **Themes**: add, edit, weight, enable/disable, delete.
- **YouTube**: search mode and estimated quota left today.
- **Appearance**: live mini-mockups of each colour scheme; one click switches every screen.
- **Updates**: running version, latest release and notes, check now, one-click upgrade with live progress and log.
- **Security**: change the PIN (when not set by `HOST_PIN`), sign out.

### Demo data
```bash
docker exec karoulette python -m scripts.seed_demo
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

- **Backend** (`backend/app`): `engine.py` is the only place event state changes; every mutation runs under one asyncio lock, is written to SQLite, and pushes typed messages (`guest_joined`, `new_singer`, `theme_spun`, `song_queued`, `now_playing`, `round_changed`, `superset`, `notice`…) followed by a full `state` snapshot. `logic.py` holds the pure ordering/theme/Superset rules that the tests target: each song is tagged with the round it belongs to (`assign_round`), and the queue is sorted by priority, round, then the singer's place in the order (`play_order`), so the order is always derived from data that survives a restart.
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

CI (`.github/workflows/docker.yml`) runs the backend tests and frontend build, then builds a multi-arch image and pushes `ghcr.io/parabyte-ca/karoulette:<version>` and `:latest` on `main` (and `:<semver>` on `v*` tags).

## Changelog
See [CHANGELOG.md](CHANGELOG.md).

## License
Proprietary. © 2026 parabyte-ca. All rights reserved.
