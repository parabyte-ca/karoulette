# Changelog

## [0.12.0] - 2026-10-25
### Added
- **Archive events** (Host admin → Events): hides an event from the TV's event list and the admin list (tick "Show archived events" to see them) while keeping its songs in the Song history and playlists. Unarchive any time. Running events must be ended first.
- **Event timeline** (Host admin → Events, under each event): everything that happened, newest first, with the time and who did it (the host, a singer by name, or "automatic" for what Karoulette did itself). Covers starts, ends and smoke breaks; joins, leaves, Bouche! and moves; songs added (with the round they landed in), removed, put first, re-picked or swapped; skips, stops and songs that couldn't play; what played next and new rounds; Supersets called, voted, started, picked, sat out, skipped and finished; last call; duplicate and last-call refusals; settings changes. Filter by type or person, search, and export to CSV.

### Changed
- **Delete for good** replaces Delete and asks you to type the event's name, since it erases the event's songs from the history too (Archive keeps them).
- **The uploaded banner is stored in the database**, so backups and restores include it. An existing banner file is copied in on upgrade (and still found if you restore an older backup).

## [0.11.2] - 2026-10-25
### Fixed
- **Stronger duplicate detection.** It used to catch only the exact same YouTube video, so the same song from another karaoke channel got through (e.g. "Stuck With You" from Reekies and from Party Tyme in one Superset). Songs now match by artist and title whatever the channel or wording: capitals, accents, punctuation, "&"/"and"/commas, "The", "ft. ...", "(Karaoke Version)", "In the Style of ..." and artist/title order are all ignored.
  - Applies to the regular queue and Superset picks, against songs played, playing or waiting. Skipped songs and songs that couldn't play don't count, so a bad video can be picked again.
  - Phones mark search results already sung or queued tonight ("Taken"), and the refusal says who picked it.

## [0.11.1] - 2026-10-24
### Fixed
- Song history: long Superset themes squeezed into a stretched pill. Superset songs now get a short "★ Superset" badge with the theme as a note underneath (two lines at most; the full theme shows on hover).

## [0.11.0] - 2026-10-24
### Added
- **Playlists from events**: turn the night's songs into a playlist of the **original recordings** (not the karaoke versions).
  - **YouTube**: one tap makes a YouTube playlist link; longer nights are split into parts of 50 songs. Nothing to set up.
  - **Spotify**: saves a private playlist to the listener's own Spotify (they sign in with Spotify; Karoulette never sees their login). The host connects a free Spotify developer app once in Host admin → Song history → Playlists.
  - **Where**: each event's playlist page (`/playlist/<code>`), a QR code on the TV's end-of-night recap, a "Take the night home" card on guests' phones after the event (and a "Tonight's playlist so far" link during it), a **🎶 Playlist** button for each event in Host admin, and the Song history (admin and `/history`), which makes a playlist of whatever the filters show.
  - Originals are found with the free backup search first, then the YouTube API only while at least 3,000 units are left for guests' searches. Each song is looked up once and remembered; if no original turns up, the karaoke video stands in.
- `SPOTIFY_CLIENT_ID` environment variable (optional), as an alternative to setting the Spotify app in Host admin.

## [0.10.0] - 2026-10-24
### Added
- **Song history** (Host admin → Song history): every song sung or skipped at every event, newest first, with who sang it (and any duet partner), the date and time, and the event.
  - Filter by event, singer, date range and played/skipped, or search songs, singers and events. Click a bar in a chart to filter by it.
  - Stats: songs, singers, events and hours of music, plus top singers, most-sung songs and songs per event.
  - Song details: duet partner, Superset and theme, cheers, and a link to the YouTube video.
  - **Export as CSV**: downloads whatever the filters show (or everything).
  - **Merge singer names**: the same name with different capitals or spaces already counts as one singer; tick names that are really one person ("Al" and "Alan") to merge them, and unmerge any time.
- **Public song history** at `/history`: a read-only copy of the dashboard for guests. On by default; switch it off in Host admin → Song history.

### Changed
- Deleting an event warns that its songs leave the song history too.

## [0.9.2] - 2026-10-24
### Fixed
- **Singers losing their turn and sliding to the bottom of the queue.** Three cases are fixed:
  - When a singer's song couldn't play (blocked from embedding), their replacement song was counted in the next round, so they skipped a round and their next song landed at the very end. The replacement now takes the failed song's turn.
  - While a song the host put first (**Play next**) was playing, anyone still to sing in that round who added a song was pushed to the next round.
  - The same happened during a Superset turn.

## [0.9.1] - 2026-10-23
### Fixed
- TV screen on a phone or narrow window: the "Scan to join" box, smoke break and recap were cut off between songs. The box now grows to fit them.

## [0.9.0] - 2026-10-23
### Added
- **Main Stage** colour scheme: a summer festival headliner. A band photo runs across the top of the TV like a marquee (with chasing bulbs), in midnight stage blue, smoke red and amber spotlights, with bold concert-poster lettering and a slow stage haze.
- **Banner photo** (Host admin → Appearance): Main Stage comes with a band photo, or upload your own (JPEG, PNG or WebP, up to 8 MB) and optionally show it with every skin. The banner appears:
  - across the top of the TV, and behind its QR, smoke break and get-ready screens (darkened so text stays readable);
  - at the top of the end-of-night recap on the TV and phones;
  - as the picture on the join page and behind the header on guests' phones;
  - in the **link preview** when the join link is shared (WhatsApp, Messages, Slack…), with the title "Join ⟨event⟩ on Karoulette".

## [0.8.0] - 2026-10-23
### Added
- **Crowd meter and crowd favourite**: every reaction counts towards the song playing. A 🔥 meter beside the song on the TV fills up as the cheers come in, and the recap crowns the **crowd favourite** (most-cheered song) and the **most cheered singer**. The CSV history has a cheers column.
- **Need ideas?** Themes carry search ideas (Host admin → Themes; the starter themes come with some, e.g. 80s: Bon Jovi, Whitney Houston, a-ha…). Phones show them as buttons under the round's theme and on Superset turns; tapping one searches for it. "Songs like ⟨song⟩" Supersets suggest that song's artist and title.
- **Last call**: an optional closing time per event (Host admin → Events). The TV shows the closing time and roughly how many more songs fit; songs that would run past it are refused, guests can't call a Superset any more (the host still can), and everyone is told "Last call!" once.
- **Backups tab** in Host admin: make and download a backup, restore one from the list (including the automatic pre-upgrade ones) or from a file, and delete old ones. A restore saves the current database first and needs no restart.
- **Health check** for Uptime Kuma and Docker: `/api/health` now checks the database (503 if it can't answer) and reports the version, active events, live connections and uptime. README has the Uptime Kuma set-up.
- **Load test** (`python -m scripts.loadtest`): 30 phones join, queue and cheer at once. It runs in CI and fails if requests or live updates get slow.

### Changed
- **Faster with a full room**: the server now sends one live update per burst of changes instead of one per change. With 30 phones queuing at once, adding a song went from 914 ms to 325 ms (95th percentile) and each phone received 6 updates instead of 92. Updates are sent as compact JSON, and new database indexes help the queue.
- **Lighter phones**: the TV, remote and admin pages load only when opened, and React sits in its own long-cached file, so a guest's phone downloads about 11 % less on first visit and only about 36 KB of app code after an upgrade (was 347 KB).
- The engine is split into one module per area (events, guests, themes, queue, playback, Supersets, last call, views); behaviour is unchanged.
- Browser tests give each test phone its own address, as on real Wi-Fi.

## [0.7.0] - 2026-10-22
### Added
- **"Get ready" screen** before every song: the TV shows the singer, the song and a countdown so they can reach the mic. Set the length per event in Host admin → Events (default 5 seconds, 0 turns it off); **Start now** (or <kbd>G</kbd>) skips it.
- **Host remote** for your phone (`/host/remote/<event>`, or scan the TV's **📱 Remote** QR code): pause/play, volume, skip, stop, start now, re-spin, Supersets, play next and remove.
- **Nearly-up alerts** on phones ("two songs to go", "up next", "you're up!") with vibration, optional system notifications, and an estimated wait beside every queued song.
- **Song limit per singer**: an optional cap on how many songs each singer can have waiting (Host admin → Events; 0 = no limit).
- **Duets**: sing a song with another guest. Both names show on the TV and both phones get the alerts; the partner can step out.
- **Crowd reactions**: 👏 🔥 😂 ❤️ 🎉 🤘 buttons on phones float up the TV while someone sings.
- **End-of-night recap** on the TV and phones: songs, singers, minutes, duets, most songs, top themes, Superset stars, first and last songs, and each guest's own count.
- **Rejoin code** for switching phones: keeps your name, place and songs, and signs the old phone out. Hosts can see every code in Host admin.
- **Install as an app**: web app manifest, icons and a service worker, plus an "Install Karoulette" button on phones (HTTPS needed).
- **Supersets are now a bonus set**: everyone picks one extra song that fits, sung once round the singer order (carrying on from the rotation), and then the regular queue carries on exactly where it left off.
  - **Any singer can call one**: everyone else votes on their phones (60 seconds by default, set per event) and the majority wins. The TV shows the vote live. One call per singer per round.
  - The caller (or the host) chooses **Start now**, where the song playing kicks it off and the theme becomes "Songs like ⟨that song⟩", or **After this song**, which spins a theme.
  - The set waits for each singer to pick when it's their turn; singers can sit it out and the host can skip a turn. A singer's Superset song is a bonus outside the song limit.
  - The host can declare or cancel one any time from the TV or remote.
- **Bouche!**: the singer "Remove" button in Host admin is now **Bouche!**, and the TV announces "[singer] has been BOUCHED!".
- **Smoke break!**: **Pause queue** on the TV or remote stops the song (it goes back to the front) and holds the queue; the TV shows "Smoke break!" and phones say the music's on hold until **Resume**. Shortcut <kbd>P</kbd>.
- **Mirror Ball** colour scheme: a 70s disco with a mirror ball, light rays and flecks of pink, ice blue and gold sweeping the room.
- **Browser tests** (Playwright) for the TV, phones and remote, run in CI on every pull request.

### Changed
- **Themes are optional**: a per-event switch, off by default, so singers pick freely. Events created before this version keep their themes. Supersets still spin (or borrow) a theme.
- The random Superset chance per round now defaults to 0 % (set it per event in Host admin).
- Admin pages fit phone screens: the Themes table becomes one card per theme, and buttons wrap instead of running off the side.
- **New singers no longer jump the line**: anyone joining after singing has started goes to the end of the singer order, so their first song plays at the end of the current round. They're still announced with the "NEW SINGER!" banner.
- At most three pop-up messages show at once, so they don't bury the phone screen.
- Database columns and tables for the countdown, duets, rejoin codes, Superset votes and sets, and smoke breaks are added automatically on upgrade.
- The "Avoid themes" setting now says rounds instead of turns.

## [0.6.0] - 2026-10-22
### Changed
- **Singers add songs any time, as many as they like**: no more waiting for a turn. The queue is a fair round-robin: one song per singer per round, each round in singer order, so the order is kept however many songs people queue. Songs can be added before the event starts.
- **One theme spin per round** (each pass through the singer order) instead of per turn; Supersets still lock a round's theme, and only songs in the current Superset round can be flagged.
- The picking turn, its 3-minute timer, overtime, Skip turn and Pause rotation are gone (nothing to time any more). Embed errors now give the singer's next pick a place at the front of the queue instead of a bonus turn.

### Added
- **New singers go next in line**: anyone joining after singing has started is slotted right after whoever is on the mic (behind other newcomers still waiting), and the TV shows a "NEW SINGER! Please welcome …" banner when their first song plays. A notice and a "New" tag mark them in the queue until then.
- Phone "My songs": each song's place and round, move a song ahead of your own others, remove it, and "Not ready? Let the next singer go first" on your up-next song (exactly one song goes ahead).
- Host: "Play next" on any queued song, move singers up/down the order in admin, round theme history.
- Database columns for round, priority and newcomers are added automatically on upgrade.

## [0.5.0] - 2026-10-19
### Changed
- Renamed the project from KaraokeQueue to **Karoulette** (karaoke + roulette) everywhere: UI, page titles, docs, scripts, Docker image (`parabyte-ca/karoulette`, `ghcr.io/parabyte-ca/karoulette`), container (`karoulette`), database file (`karoulette.db`), release names and the upgrade helper's schedule.
- Brand mark is now Kar**oulette**, with the accent on the roulette half.

### Added
- Automatic migration for existing installs: on startup the old `karaokequeue.db` (and its WAL files) is renamed; `update.sh` backs up from whichever container is running, renames `KQ_IMAGE` in `.env`, keeps a rollback image from the old name, and Compose swaps the old container for the new one. `upgrade-agent.sh --install` removes the old-named schedule so there are no duplicates.

## [0.4.0] - 2026-10-19
### Added
- Five colour schemes, chosen in Host admin → Appearance and pushed live to the TV and every phone: Neon Night (the original), On Air, Synthwave Sunset, Velvet Lounge and Northern Lights. Each has its own background treatment (studio key light and scanlines, sun-and-grid horizon, velvet curtains, drifting aurora) and display font.
- Appearance tab with a live mini-mockup of the TV and phone for each scheme.
- `GET /api/public/appearance`, `PUT /api/host/appearance`; the scheme is also part of the live event state.

### Changed
- The stylesheet now uses semantic design tokens (`schemes.css`), so new schemes are a single token block.
- The "Scan to join" text on the idle TV sits on its own panel so it stays readable over any background.

## [0.3.0] - 2026-10-19
### Added
- Host admin shows the running version, plus a gold badge when a newer release is out.
- Updates tab (modelled on project-glasshaus): daily GitHub release check, release notes, Check now, and one-click Upgrade with live progress and the upgrade log.
- `scripts/upgrade-agent.sh`: host helper that carries out upgrades requested from the admin page. Installs as a TrueNAS cron job (via `midclt`), `/etc/cron.d` entry or systemd timer.
- `.github/workflows/release.yml`: tags `vX.Y.Z` and publishes a GitHub Release with the CHANGELOG notes whenever `VERSION` changes on `main`.
- `update.sh` now backs up the database first (last 10 kept in `<data>/backups/`) and rolls back to the previous image and code if the new version isn't healthy.

### Changed
- TV sidebar: "Up next" is now the highlighted first row of the queue, and the picking panel is more compact, so the join QR code stays visible on smaller screens.
- `setup.sh` and `update.sh` share `scripts/lib.sh`; setup creates the upgrade folder and offers to install the helper.

### Fixed
- Join URL showed `/join/join/<code>` when `PUBLIC_BASE_URL` included `/join`. The setting is now reduced to the site root.
- "Queue (n)" heading overflowed its card when the sidebar ran out of room.

## [0.2.0] - 2026-10-19
### Added
- Guests can pass ("Let the next singer go first"): exactly one singer goes ahead, then the passer picks, then the rotation continues. Passing again moves them down one more.
- Overtime state when the turn timer runs out, shown on the TV and the singer's phone.
- Singing order on phones shows passed singers in their new spot.

### Changed
- Turn timer default is now 3 minutes (180 s) and is a guide only: singers are no longer skipped when it reaches zero. The host can still use Skip turn. Existing events keep their saved timer; change it in Host admin → Events.

## [0.1.0] - 2026-10-19
### Added
- Initial release of Karoulette.
- Host/TV screen with YouTube IFrame Player, YouTube Premium checklist, queue, round/theme display, QR code and join URL, host controls and keyboard shortcuts.
- Mobile guest UI: join by code or QR, turn status, theme spin, karaoke search, queue view, off-theme flagging, leave.
- Fixed join-order rotation with late joiners appended, turn timer with timeout skip, pause/resume, host skip/remove.
- Weighted theme randomizer with no back-to-back repeats and a configurable recent-theme window; theme CRUD admin with eight seeded themes.
- Superset rounds with configurable chance, host force/cancel, single locked theme, banners and animations.
- YouTube Data API v3 search with 24-hour SQLite cache, quota ledger and `quotaExceeded` handling; yt-dlp metadata-only fallback; `videos.list` verification before queueing.
- Embed error handling (101/150): auto-skip, singer notification and bonus re-pick.
- WebSocket real-time sync; SQLite persistence with restart resume; multiple events with join codes; CSV song history export; duplicate prevention.
- Host PIN auth, rate limiting, input validation.
- Tests for rotation, Superset, queue, API and YouTube service; demo seed script.
- Dockerfile, docker-compose.yml, setup.sh, update.sh, GitHub Actions workflow publishing to GHCR.
