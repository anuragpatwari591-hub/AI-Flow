# Security & safety review (Stage 8)

Reviewed by reading the code paths below and adding regression tests (`tests/test_security.py`, `test_queue.py`, `test_ads.py`).

| Area | Finding / control | Status |
|---|---|---|
| Credentials | No Instagram password anywhere. Tokens Fernet-encrypted at rest; refuses to store without `RS_SECRET_KEY`; `.env` git-ignored; secrets only from env | tested |
| Log leakage | **Found:** httpx INFO logs print request URLs incl. `access_token=`. **Fixed:** httpx/httpcore silenced + regex redaction in formatter; audit rows verified token-free | tested |
| Signing keys | **Found:** media/OAuth-state HMAC fell back to a fixed key if no secret. **Fixed:** refuses to sign (503) | tested |
| Path access | **Found:** API accepted arbitrary `local_file` / footage paths. **Fixed:** must be under `RS_DATA_DIR`; upload names stripped with `Path.name`; 200 MB cap | tested |
| XSS / links | Dashboard builds DOM with `textContent` only (test forbids `innerHTML`); **Fixed:** manual permalink must be `https://www.instagram.com/…` (blocks `javascript:`); CSP, nosniff, frame-deny, no-store on `/api` | tested |
| AuthN | Single bearer token, constant-time compare, 10-failures/min throttle per IP (in-memory, per process), API locked (503) if unset. No cookies → no CSRF | tested |
| Media exposure | Only `/media/<id>/<kind>/<hmac>` public; HMAC binds file hash | tested |
| OAuth | `state` signed + 10-min expiry. Residual: state is not bound to a browser session (login-CSRF); mitigated because a newly connected account has publishing OFF and enabling requires typing its username | documented |
| Publishing safety | Human approval mandatory (system/auto actors rejected); preflight at approve **and** publish; hash check; duplicate key; atomic claim; pause; revoke cancels queue; rate limits → 1 h backoff, never evaded; no private endpoints | tested |
| Auto-publish | Off by default; needs ≥3 human-approved successes, category allow-list, daily cap, score floor, clean preflight | tested |
| Audio rights | Unverified audio can't be rendered, published or used in ads; native audio is a manual step | tested |
| Ads | No Ads API code exists; 5 named approvals; editing budget/destination/audience/account voids that approval; ad reels can't enter organic queue | tested |
| SQL | ORM only | n/a |
| Dependencies | Not audited (`pip-audit` not run). Pin & scan before production | **open** |
| Rate limit on API beyond auth | None | **open** |
| Multi-user / roles | Single owner model by design | **open** |
| Live-account behaviour | Never exercised against real Instagram | **open** |
