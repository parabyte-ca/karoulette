# Changelog

## [1.0.0] - 2026-10-27
Karoulette is stable. Version numbers now follow semantic versioning: patches fix bugs, minor releases add features and upgrade in place, and a major release will say exactly what you need to change.

### Fixed
- **TV announcements over the video** (BOUCHED!, NEW SINGER!, SUPERSET!):
  - On **Main Stage, Mirror Ball and Northern Lights**, the video was drawn over the announcement and the TV layout jumped while it showed. The same bug knocked toasts, the Remote, Superset and Help dialogs, and the guided tour on those skins into the page under the video. Fixed.
  - **BOUCHED!** no longer tilts its ends out of the band; it shakes sideways instead.
  - Long names and wide skin fonts stay on the solid part of the band, with room above and below, at every TV size from 1024×768 to 4K. Checked on all seven skins over a playing video, and a browser test now guards it.
- Long singer names no longer run out of the TV's join card.

### Changed
- **Content-Security-Policy is enforced by default** (`CSP_MODE=enforce`). `report` (browser console only) and `off` are still there if a screen misbehaves. A new browser test fails if any screen logs a policy violation.
- **README refreshed**: screenshots of the TV, a phone, the recap, Help and Host admin; a quick start; features grouped by who uses them; upgrade and versioning notes; the architecture section brought up to date.

### Added
- `npm run screenshots` (in `frontend/`) regenerates the README screenshots from a running server.
- `update.sh` warns when `.env` still says `CSP_MODE=report`.

### Upgrade notes
- If your `.env` has `CSP_MODE=report`, change it to `enforce` (or delete the line) and run `./update.sh`. During the next night, glance at the TV browser's console (F12): it should show no "Content Security Policy" errors. If the player misbehaves, set it back to `report` and report what the console says.

## [0.17.0] - 2026-10-27
### Added
- **Help page** at `/help` (also linked from the landing page, join form, phone footer, TV, remote, event list and Host admin): 61 questions and answers for **singers** (joining, when you'll sing, duets and suggestions, Supersets, alerts on iPhone, switching phones, singer codes, privacy) and **hosts** (first night, YouTube Premium, PIN, QR address, https, shortcuts, remote, no sound, rules, last call, quota, backups, updates). Search box, collapsible answers, and links straight to one answer (`/help#switch`).
- **Singer tour**: the first time a phone joins, a short spotlight tour shows the status card, search, My songs and Queue, cheers, the rejoin code and Help. Skip any time; replay with **🧭 Show me around** at the bottom of the phone or from Help.
- **Host tour**: the first visit to the event list points out creating an event, open events, Host admin and Help; the first time a browser opens the TV screen (after the Premium checklist), it walks through the QR code, queue, theme, controls (held open during the tour), remote, admin and help. The TV's shortcuts are paused while the tour is open.
- **❓ on the TV**: keyboard shortcuts, replay the tour, and the Help page. Press <kbd>?</kbd> to open it.

## [0.16.0] - 2026-10-25
### Security
- **Real client addresses only from your proxy.** Karoulette used to believe `X-Forwarded-For` from anyone, so a visitor could fake their address and get past the login, join and search limits. It now trusts it only from `KQ_TRUSTED_PROXIES` (default: this host and Docker networks, which covers Cloudflare Tunnel and Nginx Proxy Manager). The address list is logged at start-up.
- **Host login lockout**: after 20 wrong PINs in 15 minutes, from any number of addresses, the login locks for the rest of that window. Failed and successful logins are logged with the address. The PIN check no longer pauses the TV and phones while it runs.
- **Stronger PIN hashing** (PBKDF2 600,000 iterations). Existing PINs keep working and are upgraded on the next login. A warning is logged if `HOST_PIN` is shorter than 8 characters.
- **Changing the PIN signs out every other screen.**
- **Push alerts only go to real push services** (Google, Mozilla, Apple, Microsoft), so a phone can't point the server at addresses inside your network.
- **Security headers**: Content-Security-Policy (report-only by default; set `CSP_MODE=enforce` once the browser console on the TV is clean), Permissions-Policy, and HSTS over HTTPS. Host WebSocket connections must come from this site.
- Guest tokens are hidden in the access log. A generated host PIN goes to `generated-host-pin.txt` in the data folder (readable by the app user only) instead of the log.
- **Container hardening** (docker-compose): read-only filesystem with a small `/tmp`, no Linux capabilities, `no-new-privileges`, 1 GB memory and 256-process limits, and `KQ_BIND` to publish on `127.0.0.1` only. pip is removed from the image (its bundled libraries had known vulnerabilities).
- **Signed images**: GHCR images now carry provenance and SBOM attestations and a cosign signature; the CI token is read-only except for the job that publishes.
- **Automated security checks**: a Security workflow (gitleaks, CodeQL, Semgrep, Trivy, pip-audit, npm audit, SBOM) on every PR and weekly, Dependabot updates, `SECURITY.md`, `CODEOWNERS`, and `scripts/github-harden.sh` to switch on branch protection and secret scanning.

### Upgrade notes
- Updates apply the new `docker-compose.yml` automatically. If your reverse proxy connects from an address outside `127.0.0.1` or `172.16.0.0/12`, set `KQ_TRUSTED_PROXIES` in `.env`, or every guest shares one rate limit. Check with `docker logs karoulette | grep "signed in from"`.
- If anything fails to start because of the read-only filesystem, `update.sh` rolls back automatically; please report what the log says.

## [0.15.0] - 2026-10-25
### Added
- **❤️ Likes**: guests tap the heart on anyone else's song, waiting or singing, on their phone's Queue tab. The count shows on the TV's up-next list and on the singer's own phone. Likes are just love: they never move a song.
- **Suggest a song for someone**: under the search box, "Sing it" now also offers **🎁 Suggest it to …**. The suggestion lands on their phone ("Suggested for you") to add with one tap or pass on. The suggester hears when it's added. It counts as a duet-type alert for push (now "Duets, suggestions and song issues"). Up to 3 suggestions from one guest can wait on another.
- **Awards** (Song history in Host admin, and `/history`):
  - **All-time records**: most songs ever, most cheers ever, most songs in one night, most-sung song, and the crowd favourite of the year;
  - **Regulars** and **Perfect attendance** (sang at every night, once there have been 3);
  - **Streaks** (3 nights in a row or more);
  - **Newest voices**.
  - Singers count the way the Song history counts them: singer code first, then name, with your merges on top.
- **Recap additions**: **❤️ Most loved** (the song with the most likes), **🎉 First night!** for first-timers, and **🏅 Milestones** (5th, 10th, 25th… night, or 3+ nights in a row).
- **🏅 Your personal bests** on phones with a singer code: nights, songs, most songs in a night, most-cheered song, go-to song, longest streak and first night, with a line for anything beaten tonight.

### Changed
- The TV recap gives the playlist QR a narrow column, so the highlights fit in two columns.

## [0.14.0] - 2026-10-25
### Added
- **Push alerts**: alerts now reach a phone even when Karoulette is closed or the screen is locked. Guests tap **🔔 Buzz me when I'm nearly up**, tick what they'd like, then allow notifications:
  - **Up next and you're up**: two songs to go, up next, and grab the mic;
  - **Superset turns and votes**: your Superset pick, and when someone calls a vote (not sent to whoever called it);
  - **Duet invites and song issues**: someone added you to a duet, or your song couldn't play;
  - **End-of-night playlist**: tonight's songs as a playlist when the event ends (only if songs were sung).
  - Change the ticks or turn alerts off any time from **🔔 Alerts are on** in the phone's footer. Alerts follow the phone to the next event by themselves.
  - Tapping an alert opens the event (or the playlist). When Karoulette is open on screen, the in-page message shows instead of a second notification.
  - **iPhone**: alerts need Karoulette on the Home Screen (iOS 16.4 or later); the phone explains how.
  - Needs HTTPS and outbound internet (alerts go through Google, Apple or Mozilla's push service). The server makes its own signing key on first start; it's kept in the database, so backups carry it and phones stay subscribed after a restore.
- `VAPID_SUBJECT` environment variable (optional): a contact for push services, e.g. `mailto:you@example.ca`. Defaults to `PUBLIC_BASE_URL` when that's HTTPS.

## [0.13.0] - 2026-10-25
### Added
- **Singer codes**: every singer gets a personal six-character code the first time they join. It's saved on their phone, so at the next event their name is filled in ("Welcome back!") and their **past songs** are one tap away. On another phone, "Have a singer code?" brings their name and history along. The code is in the phone's footer with a Copy button.
- **Claim your past nights**: right after getting a code (and any time from the footer), singers can claim earlier nights:
  - nights this phone was at are claimed automatically;
  - on the honour system, they tick the names they sang under, and every night under that name (with its merged spellings) becomes theirs.
  - Each night belongs to one singer code and the first claim wins. A claim on a night that's already linked to another code goes to the host to decide.
- **Singers and codes** (Host admin → Song history): every code with the nights it owns, claims to decide (approve moves the night, Keep leaves it), moving or unclaiming any night, giving unclaimed nights to a singer, and resetting a code that was shared or lost (that phone is asked for the new code next time).
- Song history counts songs by singer code first (so "Al" and "Alan" on one code are one singer); your name merges still apply on top.

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
