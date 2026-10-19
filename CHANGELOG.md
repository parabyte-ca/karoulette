# Changelog

## [0.2.0] - 2026-10-19
### Added
- Guests can pass ("Let the next singer go first"): exactly one singer goes ahead, then the passer picks, then the rotation continues. Passing again moves them down one more.
- Overtime state when the turn timer runs out, shown on the TV and the singer's phone.
- Singing order on phones shows passed singers in their new spot.

### Changed
- Turn timer default is now 3 minutes (180 s) and is a guide only: singers are no longer skipped when it reaches zero. The host can still use Skip turn. Existing events keep their saved timer; change it in Host admin → Events.

## [0.1.0] - 2026-10-19
### Added
- Initial release of KaraokeQueue.
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
