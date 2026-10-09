# One-command setup: `reelstudio setup`

```bash
reelstudio setup            # resumable; fills only what is missing; never prints secrets
reelstudio setup --check    # read-only: lists the exact remaining blockers (add --json / --offline)
```
On a server deployed with `deploy/setup-vps.sh`, run it inside the stack: `sudo docker compose exec api reelstudio setup`.
The dashboard tab **0 Setup status** shows the same report.

## What it does (in order; each phase is check-then-act, so re-running after an interruption is safe)
1. Python dependencies, FFmpeg (libx264 + AAC), licensed fonts for every template.
2. Detects hosting tools (Docker, flyctl, cloudflared, …). The only **supported** target is Docker Compose + Caddy (automatic
   HTTPS) on a server you control. It never signs you up for hosting, never deploys to paid infrastructure, and only runs
   `docker compose up` on *this* machine if you pass `--deploy` and confirm (or `--yes`).
3. Creates `.env` (chmod 600) and **fills only missing/empty** values: `RS_SECRET_KEY`, `RS_DASHBOARD_TOKEN`; asks (hidden prompt)
   for the Instagram app ID/secret. Existing values are never overwritten or rotated; nothing secret is printed.
4. Creates the data directory, applies migrations (`alembic upgrade head`; stamps an unversioned dev DB).
5. Checks `RS_PUBLIC_BASE_URL` / `RS_META_REDIRECT_URI` (https, exact `/api/instagram/callback`, same host), the public `/healthz`
   and that `/media` is routed to the app through the public URL.
6. Instagram: if not connected it prints the **Connect URL**, opens your browser (interactive only) and waits (default 5 min) while
   *you* sign in to Instagram and approve. Then it verifies the Creator account type, token state, and that
   `instagram_business_basic` + `instagram_business_content_publish` are granted (insights optional), with a read-only live probe.
   Tokens are stored Fernet-encrypted. No password handling, no token import, no bypass of Meta authorization.
7. Publishing is **never enabled by setup** — you do that in Account & tokens (typing the username). Then it checks the worker heartbeat.
Exit code 0 = READY, 1 = BLOCKED, 2 = another setup is running.

## Minimum unavoidable human actions
1. **Hosting** (one time): a small Ubuntu server + free DuckDNS name → `bash deploy/setup-vps.sh` (docs/DEPLOYMENT.md).
2. **Meta dashboard** (one time): the Instagram app ID/secret (typed hidden into setup), register the OAuth redirect URI printed
   by the script, and be an accepted Instagram Tester while the app is in Development mode.
3. **Authorize Instagram** in your browser (Connect URL).
4. **Enable publishing** for your account (explicit, typed confirmation).
5. **Approve every post** in the Approval queue. Nothing publishes during setup or tests.

## Reliability built in
- Before asking Instagram to fetch a video, the worker fetches the signed **public** URL (no redirects, ranged GET) and checks
  status, content-type and size; failures retry with backoff and nothing is sent to Instagram. (It proves the public path from
  the server; only a container reaching `FINISHED` proves Instagram's own fetch.)
- Jobs left `publishing` by a crashed worker are recovered after a 15-minute lease and retried with the same container (no
  duplicate upload); if Instagram already posted it, the retry fails with a note to check Instagram.
- Worker heartbeat file + Docker healthchecks, `restart: unless-stopped`, persistent volumes, JSON logs with secrets redacted.

## Not implemented
**Multi-user.** The app is a single-owner system (one dashboard token; several Instagram accounts can be connected but they are
not isolated per user). Extending to other authorized users needs per-user auth, row-level ownership and per-user OAuth
state/approvals — not built, so nothing here claims it.
