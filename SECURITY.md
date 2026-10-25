# Security policy

## Supported versions

Only the latest release of Karoulette gets security fixes. Update from Host admin > Updates or `./update.sh`.

## Reporting a vulnerability

Please report privately through GitHub: **Security > Report a vulnerability** on this repository
(private vulnerability reporting). Do not open a public issue.

Include what you found, how to reproduce it, and the version (`/api/health` shows it). Expect an
acknowledgement within 7 days and a fix or mitigation plan within 30 days for High and Critical issues.

## Deployment guidance

- Run behind HTTPS (Cloudflare Tunnel or a reverse proxy). Set `PUBLIC_BASE_URL` to the HTTPS address.
- Set `FORWARDED_ALLOW_IPS` to your proxy's address only. Never `*`: it lets anyone fake their IP and
  bypass the login and search rate limits.
- Use a host PIN of at least 8 characters, or a passphrase.
- Put the host pages (`/host`, `/api/host/*`) behind an access policy (Cloudflare Access with MFA) if the
  site is reachable from the internet. Guest pages (`/join`, `/api/guest/*`, `/api/public/*`, `/ws/*`)
  stay public.
- Keep the data folder on a snapshotted dataset with an offsite copy. Backups contain the PIN hash and the
  push signing key.
