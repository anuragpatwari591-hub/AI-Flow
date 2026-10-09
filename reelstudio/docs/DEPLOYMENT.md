# Deployment

## Cheapest practical path: one small Ubuntu VPS + free DuckDNS name + Docker Compose + Caddy

### VPS requirements
- **Ubuntu 24.04 LTS** (x86_64 or arm64), public **IPv4**, root/sudo SSH access.
- **1 vCPU, 2 GB RAM, 20 GB disk** (1 GB RAM works only with swap — the setup script adds 2 GB swap automatically — and renders slower).
- Inbound **22, 80, 443** open (also in your provider's cloud firewall, not just the OS). Outbound HTTPS open.
- Any provider works; pick the cheapest small Ubuntu plan (check current prices; free tiers exist but have availability limits).
- Keep the IP stable (use the provider's static/reserved IP if the default one can change) — the DuckDNS name points at it.

### 1. Free hostname (browser, 2 minutes)
1. Sign in at **duckdns.org**, add a subdomain (e.g. `anurag-reels` → `anurag-reels.duckdns.org`).
2. Put your VPS's **IPv4** in the *current ip* box → **update ip**. (The page also shows a DuckDNS *token* — it is secret and **not needed** by Reel Studio; with a static IP no updater is required.)
3. Check: `nslookup anurag-reels.duckdns.org` shows your VPS IP.
Caddy then obtains a Let's Encrypt certificate itself over port 80 (HTTP-01); no DNS plugin or token involved.

### 2. On the VPS (SSH in)
```bash
sudo apt-get update && sudo apt-get install -y git
git clone https://github.com/anuragpatwari591-hub/AI-Flow.git      # private repo: git will ask you to authenticate
cd AI-Flow && git checkout claude/nifty-archimedes-zecxfo
cd reelstudio && bash deploy/setup-vps.sh
```
The script: installs Docker/Compose/ufw (only 22/80/443 open); checks your DuckDNS name resolves to this server; asks for your
subdomain and the **Instagram app ID/secret** (secret typed hidden); generates `RS_SECRET_KEY`, `RS_DASHBOARD_TOKEN` and the
Postgres password **locally** into `.env` (chmod 600, never printed, never overwritten); builds and starts the stack; runs
`reelstudio doctor --live`. It does **not** enable publishing or publish anything.

### 3. Stable hostname = one value
The only hostname setting is `RS_DOMAIN` in `.env`. Compose derives `RS_PUBLIC_BASE_URL=https://<RS_DOMAIN>` and
`RS_META_REDIRECT_URI=https://<RS_DOMAIN>/api/instagram/callback`, so the app, the media URLs and the OAuth redirect cannot disagree.

### 4. Meta OAuth callback (browser, Meta dashboard — you do this)
Meta for Developers → **GenZ Reel Studio** → Instagram → **API setup with Instagram login** → *Business login settings* →
**OAuth redirect URIs** → add **exactly** `https://anurag-reels.duckdns.org/api/instagram/callback` (your name, no trailing slash) → Save.
Menu labels change; the value is what matters. If Meta also requires deauthorize/data-deletion URLs for your mode, tell me and
I will add the endpoints. Then open `https://<name>.duckdns.org/` (token = `RS_DASHBOARD_TOKEN` in `.env`; view it only on the server:
`grep RS_DASHBOARD_TOKEN .env`) → **Account & tokens** → **Connect Instagram**.

### 5. Verify (does not publish)
```bash
sudo docker compose exec api reelstudio doctor --live     # prints OK/FAIL, never secrets, one NEXT action
```
Publishing stays OFF until you click *Enable publishing* (typing the username) and every post still needs approval.

### Operations
`sudo docker compose logs -f api worker` · update: `git pull && sudo docker compose up -d --build` ·
backup: `sudo docker compose exec -T db pg_dump -U reel reelstudio > backup.sql` + back up the `data` volume and `.env`.
Optional IP allow-list for the dashboard: see the commented block in `deploy/Caddyfile`.
**Status:** compose/Dockerfile validated; the container was verified to build, migrate Postgres, serve `/healthz` and run as non-root,
but the apt packages (ffmpeg, fonts) and Let's Encrypt issuance have **not** been exercised outside a real VPS.

## Requirements
Python ≥ 3.11, FFmpeg (libx264 + AAC), PostgreSQL ≥ 14, fonts registered in `config/fonts.yaml`, HTTPS in front of the app.

## Environment
Copy `.env.example` → `.env`; generate secrets with `reelstudio gen-keys`. Inject via your platform's secret store;
never commit `.env`.

## Steps
```bash
python -m venv .venv && . .venv/bin/activate
pip install -e ".[postgres]"
export RS_DATABASE_URL=postgresql+psycopg://user:pass@host:5432/reelstudio
reelstudio migrate
reelstudio serve --host 127.0.0.1 --port 8000      # API + dashboard
reelstudio worker                                  # scheduler / token upkeep / insights (exactly ONE instance)
```
Run both under systemd (examples in `deploy/`) or the provided `Dockerfile`/`docker-compose.yml` (**not built or run
in the authoring environment** — treat as a starting point).

TLS: terminate at nginx/Caddy and proxy to 127.0.0.1:8000. `/media/*` must be reachable by Instagram; `/api/*` is
bearer-protected, but restrict the dashboard by IP/VPN as well if you can.

## Operations
- Backups: `pg_dump` the database + back up `RS_DATA_DIR` (renders). Tokens are encrypted; **keep `RS_SECRET_KEY`
  backed up separately** — without it stored tokens are unreadable (you would simply reconnect).
- Logs are JSON lines on stderr. Set `RS_ALERT_WEBHOOK_URL` for failure/expiry alerts.
- Emergency stop: dashboard **PAUSE EVERYTHING** (or `POST /api/automation/pause`), cancel jobs, or **Revoke access**.
- Single worker: the claim is an atomic UPDATE so accidental duplicates won't double-post, but run one anyway.
- Rendering runs in a background thread in the API process; for heavy use move `render_reel` to the worker.
