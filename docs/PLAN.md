# Karoulette — Build Plan (v0.1.0)

## 1. Architecture

```
 TV browser (/host, signed into YouTube Premium)      Guest phones (/join)
        │  IFrame Player API (YouTube direct)                │
        └───────── HTTP + WebSocket ──────────┬──────────────┘
                                              ▼
                     FastAPI (uvicorn, single process)
                     ├── REST: /api/host/* (PIN), /api/guest/* (token), /api/public/*
                     ├── WS:   /ws/{event_code}?role=host|guest&token=…
                     ├── EventEngine (rotation, rounds, superset, timer)  ← pure logic, unit tested
                     ├── YouTubeService (Data API v3 → yt-dlp fallback, SQLite cache, quota ledger)
                     └── SQLite (DATA_PATH/karoulette.db, WAL)
                     Serves built React SPA (Vite) as static files
```

- One Docker image (multi-stage: Node builds SPA → Python slim runtime with yt-dlp).
- No timers in the event flow (v0.6.0): the play order is derived from stored data (singer order, song rounds, priorities), so a restart resumes exactly.
- All state changes go through the engine → persisted → `broadcast(event_id, message)` to all WS clients of that event. Clients re-fetch a full `state` snapshot on (re)connect, then apply deltas.

## 2. Data model (SQLite)

| Table | Key columns |
|---|---|
| `settings` | `key` PK, `value` (JSON) — host PIN hash (bcrypt), global defaults |
| `events` | `id`, `name`, `join_code` (6 chars, unique, no ambiguous letters), `status` (draft/active/paused/ended), `created_at`, `started_at`, `ended_at`, `config` JSON (turn_seconds=180, superset_chance=0.15, recent_theme_window=3, prevent_duplicates=true, safe_search="moderate"), `current_round`, `current_turn_guest_id`, `turn_deadline`, `turn_state` (announcing/spinning/choosing/overtime/idle), `superset_pending` (null/force/cancel), `rotation_paused`, `now_playing_item_id` |
| `guests` | `id`, `event_id`, `display_name`, `token_hash`, `rotation_pos` (int, join order), `status` (active/left/removed), `joined_at`, `skip_next` bool |
| `themes` | `id`, `name`, `description`, `weight` (default 1), `enabled`, `created_at` (global, shared across events) |
| `rounds` | `id`, `event_id`, `number`, `is_superset`, `superset_theme_id`, `started_at` |
| `turns` | `id`, `event_id`, `round_id`, `guest_id`, `theme_id`, `outcome` (queued/passed/skipped/removed/left), `started_at`, `ended_at` |
| `queue_items` | `id`, `event_id`, `guest_id`, `turn_id`, `video_id`, `title`, `channel`, `duration_s`, `thumbnail`, `position` (float for cheap reorder), `status` (queued/playing/played/skipped/removed/error), `off_theme_flags` int, `added_at`, `played_at` |
| `flags` | `queue_item_id`, `flagged_by` (guest id or "host"), unique pair |
| `search_cache` | `query_norm` PK, `results` JSON, `source` (api/ytdlp), `fetched_at` (24 h TTL) |
| `video_cache` | `video_id` PK, `duration_s`, `embeddable`, `title`, `channel`, `thumbnail`, `fetched_at` |
| `quota_ledger` | `day` (Pacific date — YouTube's reset), `units_used` |

"Theme history" = `turns.theme_id` + `rounds.superset_theme_id`. "Songs sung" = `queue_items` with status `played` → CSV export.

## 3. Core logic

**Singer order and fair queue (v0.6.0):** singers add songs any time. Active guests are ordered by `rotation_pos` (join order). Each song gets a `round_no` when added (`logic.assign_round`): the current round if the singer's slot in it is still ahead of the singer on the mic and they have no song there yet, otherwise the round after their last song. The queue is sorted by (`priority` if set, `round_no`, singer position + `order_bias`). A new round starts (theme spin, Superset roll) when the first song of a higher round plays. Guests who join after singing has started go to the end of the singer order (since v0.7.0; v0.6.0 put them next in line) with `debut_pending`, and are announced (`new_singer`) when their first song plays. Themes are a per-event switch (`themes_enabled`, off by default). A Superset is a bonus set (`superset_sets`, `superset_slots`): one extra song per singer, once round the singer order (`logic.set_order`, carrying on from the rotation), on one theme ("Songs like <the song playing>" when it starts now, otherwise spun). While a set is active, `play_next` plays its next turn, waiting for that singer's pick; set songs (`queue_items.set_id`) stay out of the regular queue, which resumes untouched afterwards. Guests call Supersets by vote (`superset_votes`, `superset_ballots`): everyone else votes, `logic.vote_outcome` decides by majority of votes cast, and the server's one-second tick closes votes at their deadline. `events.paused` holds the queue for a smoke break. "Let the next singer go first" moves one song exactly one place back (`order_bias`, or into the next song's round). An embed error sets `repick_credit`, giving that singer's next song a `priority`. Host "play next" sets a `priority` ahead of all others.

**(Superseded in v0.6.0) Turn lifecycle:** `announcing` (3 s, host shows "Up: Alex") → `spinning` (theme spin, ~4 s animation; result pushed to phone) → `choosing` (deadline = now + turn_seconds) → `overtime` when the 3-minute guide timer runs out (no skip; notice only) → song queued, guest **passes**, or host skips → next guest. A pass adds a `deferred` entry to `bonus_queue` (`after_guest_id` = whoever picks next); once that singer's turn starts the entry is ready and the passer picks next, without moving the rotation cursor. Rotation paused = timer frozen (remaining time stored), no advance.

**Theme pick:** weighted random over enabled themes, excluding the previous theme (hard) and the last *N* themes (soft — relaxed if it would leave nothing).

**Superset:** at each new round start, roll `random() < superset_chance` unless host set `force`/`cancel` on the pending flag. Superset round: one spin at round start, theme locked for all turns, distinct banner + animation, guests/host can flag off-theme (host sees flag count, may remove). Non-superset round: spin per turn.

**Queue:** play order = `position` ascending among `queued`. Host can reorder (drag / up-down), remove. Auto-advance on `ENDED`; on IFrame errors 101/150 (also 100 / 2 / 5) mark `error`, auto-skip, notify the singer and grant them a re-pick (a bonus turn inserted ahead of the normal rotation).

**Duplicates:** if enabled, reject a `video_id` already queued/played in this event.

## 4. YouTube

- `search.list` (`type=video, videoEmbeddable=true, videoSyndicated=true, safeSearch=<cfg>, maxResults=15`, query + " karaoke") = 100 units; `videos.list` (contentDetails,status) for durations + embeddable = 1 unit. Ledger tracks units, shows remaining of `YOUTUBE_DAILY_QUOTA` (default 10 000) in admin.
- Cache: normalised query → results, 24 h TTL.
- `quotaExceeded` / missing key / API failure → yt-dlp `ytsearch15:` metadata only (`extract_flat`, no downloads). Results are marked "unverified" and embeddability checked via `videos.list` if possible, otherwise via the oEmbed endpoint.
- Before queuing: re-check video via `videos.list` (cached) — must be embeddable and ≤ 15 min (configurable).
- API key lives server-side only; no endpoint ever returns it.

## 5. API surface (abridged)

Public: `GET /api/public/event/{code}` (name, status), `GET /api/health`.
Guest (Bearer token): `POST /api/guest/join` → token, `POST /leave`, `GET /state`, `GET /search?q=` (rate-limited 10/min/guest + 60/min/IP), `POST /queue` (only when it is your turn), `POST /flag/{item}`.
Host (PIN → signed session cookie, HttpOnly): `POST /api/host/login`, events CRUD + start/end, `POST /turn/{start|pause|resume|skip}`, `POST /theme/spin`, `POST /superset/{force|cancel}`, queue `reorder|remove`, guest `remove|skip`, `POST /player/{ended|error|playing}`, themes CRUD, settings, quota, `GET /events/{id}/history.csv`.

WebSocket messages (server → client): `state` (snapshot), `guest_joined`, `guest_left`, `turn_changed`, `theme_spun`, `song_queued`, `song_removed`, `queue_reordered`, `now_playing`, `round_changed`, `superset`, `notice`, `event_ended`. Client → server: `ping` only (mutations go via REST for validation/rate limiting).

## 6. Frontend (React + Vite, no UI framework, CSS variables, dark, high-contrast)

- `/host` — PIN login → Premium checklist (persisted per browser) → event picker/creator → TV screen: player (≈65 % width), now singing, up next, queue, round/theme banner, QR + join URL + code, spin overlay, superset banner. Collapsible host control bar (keyboard shortcuts: Space pause, N skip, S spin).
- `/host/admin` — themes CRUD, event settings, guest list, quota meter, history + CSV export.
- `/join` (and `/join/:code`) — name entry → status card ("You're up!" / "3 turns until you"), theme, search + results (thumb, title, channel, duration), queue view with flag button in supersets, leave.

## 7. Repo layout

```
backend/app/{main,config,db,models,engine,youtube,auth,ws,ratelimit,routes/*}.py
backend/tests/{test_rotation,test_superset,test_queue,test_api}.py
backend/scripts/seed_demo.py
frontend/src/{pages/Host*,pages/Join*,pages/Admin*,components/*,lib/{api,ws}.ts}
Dockerfile, docker-compose.yml, .env.example, setup.sh, update.sh
VERSION, CHANGELOG.md, README.md (+ First event checklist), .github/workflows/docker.yml
```

## 8. Config (env)

`KQ_PORT` (host port, default **8095**), `YOUTUBE_API_KEY`, `DATA_PATH` (default `/data`; TrueNAS: `/mnt/<pool>/apps/karoulette`), `HOST_PIN` (first-run only; hashed into DB, changeable in admin), `SECRET_KEY` (auto-generated into DATA_PATH if unset), `PUBLIC_BASE_URL` (for QR; defaults to request host), `YOUTUBE_DAILY_QUOTA`, `TZ`.

## 9. Testing / CI

- pytest: rotation (order, late join, leave mid-turn, wrap → round++), superset (chance, force, cancel, theme locked, flags), queue ordering (reorder, remove, duplicates, auto-advance, error re-pick), theme picker (no repeat, recent window, weights).
- GH Actions: test job → build + push `ghcr.io/parabyte-ca/karoulette:{version,latest}` on main/tags.
