# Changelog

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
