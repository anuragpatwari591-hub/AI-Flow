# Deployment

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
