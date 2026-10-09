# Zero-cost Windows 11 laptop deployment

Runs the whole app on your own laptop (no VPS, no domain): Docker Desktop (WSL 2) + a free HTTPS tunnel.

## Prerequisites (the script checks each one and tells you the single fix)
- Windows 11 (build 19041+ works), virtualization enabled in BIOS/UEFI.
- **Docker Desktop** with the **WSL 2 engine** (free for personal use). `winget install -e --id Docker.DockerDesktop`, reboot, start it.
- The laptop must stay **on, awake and online** for scheduled posts and for Instagram to download videos.
- Nothing else to install: FFmpeg, fonts, Postgres, the tunnel and the web gate all run in containers.

## The command (PowerShell, from the repo folder)
```powershell
powershell -ExecutionPolicy Bypass -File .\reelstudio\deploy\windows\setup-laptop.ps1
```
Re-runnable; it only fills missing values and never overwrites a credential. Extras: `-InstallDocker`, `-Tunnel Ngrok`,
`-CopyToken` (dashboard token to clipboard, never printed), `-Status` (read-only readiness), `-Stop` (stop; data kept).

What it does: checks Docker/WSL 2/Compose -> creates `.env` (secrets generated locally, BOM-free, restricted to your user, never
printed; asks hidden for the Instagram app ID/secret) -> starts `db`, `api`, `worker`, `gate` and a tunnel with persistent Docker
volumes -> verifies the API, FFmpeg, the public HTTPS address and that the **dashboard is NOT public** -> prints the exact Meta
callback -> waits for you -> opens the Instagram authorization page -> runs `reelstudio setup` to verify the account, token and the
`instagram_business_basic` + `instagram_business_content_publish` permissions. It never publishes, never enables publishing,
never touches your Instagram password, and never calls any approve/enable API.

## Tunnel options
| | Quick (default) | ngrok (`-Tunnel Ngrok`) |
|---|---|---|
| Cost / account | free, no account | free account (authtoken + free domain) |
| URL | **random, changes every start** | stable `*.ngrok-free.app` (if your free plan includes a static domain; sources conflict, check your ngrok dashboard) |
| Browser warning page | none | ngrok shows an interstitial to browsers on free plans (API clients unaffected); not verified against Instagram's fetcher |
| Meta redirect URI | must be re-saved in Meta each time you connect | save once |

With the Quick tunnel the changing URL only matters while **connecting** Instagram. The token is stored encrypted and survives
restarts; the media URL is re-derived from the current tunnel address on every start. If the URL changed, re-run the script
(it recreates api/worker with the new address). A post scheduled while the tunnel is down retries with backoff.

## Security model
- Tunnels point only at the **gate** (Caddy), which forwards just `GET/HEAD /healthz`, `/media/*` (HMAC-signed) and
  `/api/instagram/callback`. Everything else returns 404. Verified against the real Caddy + app: `/`, `/api/*`, `/docs`,
  `/openapi.json`, POSTs and path-traversal attempts are all refused.
- The dashboard is only on `http://localhost:8000` (loopback-bound). Log in with `RS_DASHBOARD_TOKEN` (`-CopyToken`, or open `.env`).
- The ngrok authtoken lives in `.env.tunnel` and is never passed to the app containers. `.env*` are git-ignored.
- App safeguards unchanged: review-required, per-post approval, publishing OFF until you enable it, audio-rights gating, audit log.

## Meta callback
The script prints it: `https://<tunnel-host>/api/instagram/callback`. Add it exactly under Meta for Developers -> GenZ Reel Studio ->
Instagram -> API setup with Instagram login -> Business login settings -> OAuth redirect URIs. You must also be an accepted
Instagram Tester while the app is in Development mode.

## Verification status (honest)
Tested: PowerShell parses; helper functions run (PowerShell 7 on Linux); the whole script flow ran against a fake `docker` with
stubbed prompts/network: happy path (Quick and ngrok) and every failure mode (no Docker, engine stopped, not WSL 2, stack
unhealthy, no FFmpeg, gate not filtering); the real Caddy gate in front of the real app; `docker compose config` for both
profiles; the Python side (`connect-url`, HEAD/Range media, setup). **Not tested:** Windows PowerShell 5.1 itself, Docker Desktop,
real cloudflared/ngrok tunnels, the full image build (apt is blocked in the authoring sandbox), and Instagram/Meta live.
