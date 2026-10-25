# Karoulette
> Karaoke meets roulette. Self-hosted, multi-user karaoke night: guests join by QR code, queue YouTube karaoke videos from their phones, and sing one song per round in a fair rotation while a theme roulette spins each round.

![Version](https://img.shields.io/badge/version-0.8.0-blue)

## Overview
Karoulette runs your karaoke party from one TV and everyone's phones. The TV (host screen) plays YouTube karaoke videos through the official YouTube player in a browser signed into YouTube Premium, so there are no ads. Guests scan a QR code, pick a display name and add as many songs as they like; the queue plays one song per singer per round, and each round spins a theme for everyone's picks. Everything syncs in real time and survives a container restart.

## Features
- **Host / TV screen** (`/host`): full-screen YouTube player, current singer, up next, queue, round and theme, QR code, join URL and code. High-contrast dark layout readable from across the room.
- **YouTube Premium checklist** on first load of the TV screen in each browser session.
- **Host controls**: start event, play/pause video, skip song, re-spin the round's theme, force or cancel a Superset, "play next" or remove any song, move singers up/down the order, **Bouche!** a singer (removes them, and the TV announces "[singer] has been BOUCHED!"), end event. Keyboard shortcuts on the TV: <kbd>Space</kbd> play/pause, <kbd>N</kbd> skip song, <kbd>S</kbd> re-spin, <kbd>G</kbd> start the song now, <kbd>P</kbd> pause/resume the queue, <kbd>H</kbd> show/hide controls.
- **Smoke break!** **🚬 Pause queue** (TV or remote) stops the song, puts it back at the front and holds the queue; the TV shows "Smoke break!" and phones say the music's on hold until **Resume**. Guests can keep adding songs.
- **"Get ready" screen**: before each song the TV shows the singer's name, the song and a countdown (default 5 seconds, set per event in Host admin; 0 turns it off) so they can reach the mic. **Start now** skips the rest.
- **Host remote** (`/host/remote/<event>`): control the night from your phone: pause/play, volume up/down, skip, stop, smoke break, start the song now, re-spin, Supersets, play next and remove. Scan the QR code from the TV's **📱 Remote** button and sign in with the host PIN.
- **Guest phone UI** (`/join`): mobile-first, no accounts (session token in `localStorage`), song search that's always open, "My songs" with each song's place in the queue and an **estimated wait** ("≈ 8 min"), the round's theme, full queue and singer order.
- **Nearly-up alerts**: phones show and vibrate "two songs to go", "you're up next" and "you're up!". Tap **🔔 Buzz me when I'm nearly up** for **push alerts** that reach the phone even when it's locked or Karoulette is closed: pick from up next / you're up, Superset turns and votes, duet invites and songs that couldn't play, and the end-of-night playlist. Needs HTTPS and outbound internet; on iPhone, add Karoulette to the Home Screen first (iOS 16.4+).
- **Duets**: when adding a song, pick "As a duet with …" to sing it with another guest. Both names show on the TV, both phones get the alerts, and the partner can step out. The song counts as the picker's turn.
- **Crowd reactions and the crowd meter**: while someone sings, phones get a row of 👏 🔥 😂 ❤️ 🎉 🤘 buttons; each tap floats up the TV with the sender's name and fills the 🔥 **crowd meter** beside the song (rate limited).
- **End-of-night recap** on the TV and every phone: songs sung, singers, minutes of music, rounds, duets, the **crowd favourite** (most-cheered song) and **most cheered singer**, most songs, top themes, Superset stars, who opened and closed the night, and each guest's own count.
- **Last call** (optional): set a closing time per event. The TV shows "Closing 11:30 p.m. · room for about 3 more songs"; once the queue would run past it, new songs (and guest Supersets) are refused, and everyone's told "Last call!".
- **Need ideas?** Themes carry search ideas (artists or songs; the starter themes come with some). Phones show them as buttons under the round's theme and on Superset turns; a "Songs like ⟨song⟩" Superset suggests that song's artist and title.
- **Singer codes**: each singer gets a personal code that their phone remembers, so the next event says "Welcome back", fills in their name and offers their past songs. Singers can claim past nights (automatically for nights their phone was at, or by name on the honour system); claims on nights already linked to someone else go to the host in Host admin → Song history → Singers and codes.
- **Rejoin code**: each guest gets a six-character code (bottom of their phone screen, and beside their name in Host admin). On a new phone, "Switched phones? Rejoin with your code" brings back their name, place and songs, and signs the old phone out.
- **Installable app**: phones can add Karoulette to the home screen (web app manifest, icons and a small service worker that never caches live data). Needs HTTPS, e.g. through your reverse proxy.
- **Add songs any time, as many as you like**: no waiting for a turn. The queue is a fair round-robin: each singer gets one song per round, and every round follows the singer order. A singer with five songs queued sings one per round, interleaved with everyone else.
- **Singer order** is join order. **New singers** who join after singing has started go to the **end of the singer order** (no jumping the line: their first song plays at the end of the current round), and the TV announces them with a "NEW SINGER!" banner when it starts. Guests can leave; the host can move singers up or down or bouche them.
- **Your songs, your way**: a singer can move one of their songs ahead of their own others, remove it, or, when it's up next, tap **"Not ready? Let the next singer go first"** to let exactly one song go ahead.
- **Themes are optional**: a per-event switch (Host admin → Events, **off by default**, so singers pick freely). When on, each pass through the singer order spins a theme (animated on the TV and phones) as a suggestion. The theme list has a CRUD admin page (name, description, weight, enabled); no theme repeats back to back, and the last _N_ can be avoided. Seeded with 80s, Duets, From a Soundtrack, Canadiana, 90s, Power Ballads, Guilty Pleasures, One-Hit Wonders.
- **Supersets**: a bonus set where everyone picks one extra song that fits one theme, sung once round the singer order (carrying on from the rotation), then the regular queue picks up exactly where it left off.
  - **Any singer can call one** from their phone; everyone else votes (60 seconds by default, tally live on the TV) and the majority of votes wins. Each singer can call one per round. The host can declare or cancel one from the TV or remote, and an optional random chance per round (default 0 %) is in Host admin.
  - Whoever calls it chooses: **Start now**: the song playing kicks it off and the theme becomes "Songs like ⟨that song⟩"; or **After this song**: a theme is spun from the list.
  - Every phone shows the theme and the line-up; a singer's next pick becomes their Superset song (a bonus outside the song limit). The set **waits** for each singer to pick when their turn comes (the TV shows "Waiting for … to pick"); singers can **sit it out** and the host can skip a turn. Off-theme Superset songs can be flagged.
- **YouTube search** via the Data API v3 (`type=video`, `videoEmbeddable=true`, `videoSyndicated=true`, configurable SafeSearch), "karaoke" added automatically, 24-hour SQLite cache, quota meter in admin and graceful `quotaExceeded` handling. Falls back to **yt-dlp metadata-only search** (never downloads) when there's no key or the quota is gone.
- **Pre-queue checks** with `videos.list`: duration and embeddability are confirmed before a song is added; optional maximum length.
- **Embed errors** (IFrame codes 101/150 and others) auto-skip the song, notify the singer, and their next pick plays straight away.
- **Real-time sync** over WebSockets; full state persisted in SQLite so a restart resumes the event, queue and all.
- **Multiple events** with a start/end lifecycle and a short join code. Song history per event with **CSV export**.
- **Duplicate prevention** per event (host-configurable): the same song from any karaoke channel counts, and phones mark search results already sung or queued tonight.
- **Seven colour schemes**, switchable live from Host admin → Appearance (TV, phones and admin repaint instantly, even mid-event): **Neon Night** (original), **On Air** (broadcast studio), **Synthwave Sunset** (80s outrun), **Velvet Lounge** (jazz club), **Northern Lights** (Canadian aurora), **Mirror Ball** (70s disco, with light flecks sweeping the room) and **Main Stage** (a festival headliner with a band photo across the top like a marquee). Each has its own background art and display font, and all stay dark and high-contrast.
- **Banner photo**: Main Stage's band photo, or upload your own and show it with any skin. It runs across the top of the TV, behind the QR and smoke break screens, on the recap, on guests' phones and in the preview when the join link is shared.
- **Backups in Host admin**: make and download a backup any time, restore one from the list (including the automatic pre-upgrade backups) or from a file. The current database is saved first, so a restore can be undone.
- **Health check** at `/api/health` that checks the database (for Docker and monitors like Uptime Kuma; see below).
- **Updates from the admin page** (same model as project-glasshaus): a daily check for new GitHub releases, the running version and any new release shown in Host admin, release notes, and a one-click **Upgrade** that a small host helper carries out with a database backup, health check and automatic rollback.
- **Security**: host PIN (PBKDF2-hashed, HttpOnly signed session cookie), rate-limited search/join/login, validated inputs, API key never sent to browsers.
- Automated tests: backend unit and API tests, plus **browser tests** (Playwright) that drive a TV, phones and the host remote against a real server on every pull request. Demo seed script included.

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
| `SPOTIFY_CLIENT_ID` | _(blank)_ | Optional: the Client ID of your Spotify app, for Spotify playlists (or set it in Host admin → Song history → Playlists) |
| `PUBLIC_BASE_URL` | _(blank)_ | Site address used in the QR code and join link previews, e.g. `https://karaoke.example.ca` (just the root; a pasted `/join` or `/host` is stripped). Blank = the address the TV used |
| `VAPID_SUBJECT` | _(blank)_ | Optional contact for push alert services, e.g. `mailto:you@example.ca`. Blank = `PUBLIC_BASE_URL` when it's HTTPS |
| `SECRET_KEY` | _(generated)_ | Signs host session cookies |
| `ENABLE_YTDLP` | `true` | Allow the yt-dlp metadata fallback |
| `UPDATE_CHECK` | `true` | Daily check for new releases (Host admin → Updates) |
| `SOURCE_REPO` | `parabyte-ca/karoulette` | GitHub repository releases are checked against |
| `KQ_UPGRADE_FOLDER` | `./upgrade` | Host folder shared with the upgrade helper |
| `KQ_IMAGE` / `KQ_TAG` | `parabyte-ca/karoulette` / `latest` | Image to run |
| `TZ` | `America/Toronto` | Container time zone (last call times use it) |
| `STATE_COALESCE_MS` | `60` | How long the server gathers a burst of changes before sending everyone one update |

**Per-event settings** (Host admin → Events): **themes on/off** (default off), random Superset chance per round (default 0 %), Superset vote length (default 60 s), recent-theme window (default 3), prevent duplicate songs (default on), SafeSearch (off / moderate / strict), longest video allowed (default 15 min), autoplay, **"Get ready" countdown** (default 5 s, 0 = off) and **songs each singer can have waiting** (default 0 = no limit) and **last call** (a closing time, blank = none).

**Quota maths**: a new search costs about 101 units (100 for `search.list` + 1 for `videos.list`), so the default 10,000-unit daily quota covers roughly 99 fresh searches; repeated searches within 24 hours are served from the cache for free. Quota resets at midnight Pacific time.

**Reverse proxy** (Nginx Proxy Manager, Cloudflare Tunnel): enable **WebSockets support**, forward to `http://<nas-ip>:8095`, and set `PUBLIC_BASE_URL` so the QR code uses the public address. Make sure the proxy passes `X-Forwarded-For` (both do by default): join and search limits are per guest address.

**Monitoring with Uptime Kuma**: add a monitor of type **HTTP(s) - Keyword**, URL `http://<nas-ip>:8095/api/health`, keyword `"status":"ok"`, interval 60 seconds. It returns 200 only when the app and its database answer, and 503 otherwise. The response also lists the version, active events and live connections (or use a **HTTP(s) - Json Query** monitor with `status` = `ok`). Docker's own health check uses the same endpoint.

## Usage

### First event checklist
1. **Sign in to YouTube Premium** in the browser on the TV (Chrome/Edge). Open youtube.com and confirm the Premium logo.
2. Open `http://<server>:8095/host` on that browser and enter the host PIN.
3. **Create the event** (e.g. "Saturday Singalong"), then tick the Premium checklist and press **Continue** (this click also lets the browser autoplay with sound). Press <kbd>F11</kbd> or the ⛶ button for full screen.
4. **Show the QR code**: it's on the TV with the join URL and a five-character code.
5. **Guests join and add songs**: scan, enter a display name, and search. They can queue as many songs as they like, even before you start; the singer order is the order they joined.
6. Press **▶ Start event**. Round 1's theme spins and the first song plays.
7. Songs play automatically, one per singer per round, each after a short "Get ready" countdown. Latecomers join the end of the order and get a "NEW SINGER!" welcome. Use the control bar (move the mouse to show it) to skip, re-spin, put a song next or call a **Smoke break!**, or press **📱 Remote** and scan the code to do it all from your phone.
8. When you're done, **End event**: the TV and phones show the night's recap. Export the song history from Host admin → Events → _Export song history (CSV)_.

### Host admin (`/host/admin`)
- **Playlists** (Song history → Playlists): YouTube playlists of the original songs work straight away. For Spotify, create a free app at developer.spotify.com, add the redirect URI shown there (your HTTPS address + `/spotify`), and paste its Client ID. In Spotify's development mode, only accounts added under User Management can sign in.
- **Song history**: every song from every event, with filters, stats (top singers, most-sung songs, songs per event), CSV export of what's showing, and merging the names one singer has used. Guests can see a read-only copy at `/history` unless you switch sharing off.
- **Events**: settings, singer order (move up/down, **Bouche!**, rejoin codes), round themes, phone remote, CSV export, the event **timeline** (who did what, filterable, CSV), **archive** (hide an event, keep its songs) and delete for good.
- **Themes**: add, edit, weight, enable/disable, delete.
- **YouTube**: search mode and estimated quota left today.
- **Appearance**: live mini-mockups of each colour scheme; one click switches every screen. Upload a banner photo (JPEG, PNG or WebP, up to 8 MB), remove it, or show it with every skin.
- **Updates**: running version, latest release and notes, check now, one-click upgrade with live progress and log.
- **Backups**: make and download a backup, restore from the list or a file, delete old ones. Backups include the uploaded banner.
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
            ├─ Engine: rotation, rounds, Supersets, queue, duets, recap (persisted state)
            ├─ YouTube service: Data API v3 → yt-dlp fallback, SQLite cache, quota ledger
            └─ SQLite (WAL) in /data  ·  serves the built React SPA
```

- **Backend** (`backend/app`): the `engine` package is the only place event state changes. It's one `Engine` class built from a mixin per area: `events`, `guests`, `themes`, `queue`, `playback`, `supersets`, `lastcall` and `views` (snapshot, recap, CSV). Every mutation runs under one asyncio lock, is written to SQLite, and pushes typed messages (`guest_joined`, `new_singer`, `theme_spun`, `song_queued`, `now_playing`, `round_changed`, `superset`, `superset_vote`, `bouched`, `queue_paused`, `last_call`, `notice`…). The full `state` snapshot follows once per burst of changes (`STATE_COALESCE_MS`), so thirty phones queuing at once cost a handful of updates, not thirty. Reactions go only to the TV and remote, with no snapshot. `logic.py` holds the pure ordering/theme/Superset rules that the tests target: each song is tagged with the round it belongs to (`assign_round`), and the queue is sorted by priority, round, then the singer's place in the order (`play_order`), so the order is always derived from data that survives a restart. `vote_outcome` decides Superset votes and `set_order` lays out a Superset's turns; a one-second server tick closes votes whose time is up. A Superset's songs (`queue_items.set_id`) sit outside the regular queue until the set is done.
- **Frontend** (`frontend/src`): React + Vite, no UI framework. `HostScreen` (TV), `HostRemote` (host's phone), `HostAdmin`, `JoinApp` (guest phone). `useEventSocket` reconnects with backoff and corrects for clock skew. `public/` holds the web app manifest, icons and service worker (`sw.js`, version-stamped by the server).
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

# Browser tests (starts its own server on :8097 with a throwaway database)
cd frontend && npm run build && npx playwright install chromium
KQ_PYTHON=../backend/.venv/bin/python npm run test:e2e

# Load test: 30 phones join, queue and cheer at once against a running test server
cd backend && python -m scripts.loadtest --base http://127.0.0.1:8095 --pin 1234
```

The frontend loads the host pages (TV, remote, admin) only when they're opened, and keeps React in its own long-cached file, so guests' phones download less and re-download only the app code after an upgrade.

CI (`.github/workflows/docker.yml`) runs the backend tests, the frontend build, the browser tests and the load test (fails if a request type's p95 passes 750 ms or an update takes over 1.5 s to reach every phone), then builds a multi-arch image and pushes `ghcr.io/parabyte-ca/karoulette:<version>` and `:latest` on `main` (and `:<semver>` on `v*` tags).

## Changelog
See [CHANGELOG.md](CHANGELOG.md).

## License
Proprietary. © 2026 parabyte-ca. All rights reserved.
