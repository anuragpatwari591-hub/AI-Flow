# Remaining manual steps & known blockers

**Blockers I could not resolve from the dev environment (exact):**
1. **Instagram/Meta credentials** — need a Meta app, professional IG account, `RS_META_*`, an HTTPS redirect URI and a public HTTPS host for `/media`. Until then, publishing has only been tested against a fake API.
2. **Reference account `@salzr`** — `www.instagram.com` was unreachable from the dev sandbox and scraping is out of scope, so *zero* observations about that account exist. Supply videos you may use (dashboard → Reference library) to get measured stats (duration, cuts, darkness), then add inspected observations.
3. **Live trend data** — no licensed trend provider/API credentials. Supply exports to `data/trend_imports/*.json|csv` (schema in `trends/sources.py`), configure `rss_feeds`, or add a provider adapter (`CredentialedApiSource` is the stub). Until then only the seasonal calendar produces trends.
4. **AI provider** — set `RS_AI_PROVIDER=anthropic` + `RS_ANTHROPIC_API_KEY` for fresh writing. The offline seed writer has only 18 hand-written concepts and caps confidence at 0.4. The Anthropic HTTP contract is tested with a mock, not the live API.
5. **Audio** — supply audio you own/licensed (register in *Audio & rights* with licence ref and permission flags). Beat detection was only validated on synthetic click tracks; check results on real music.
6. **Fonts** — no condensed face is installed. Add e.g. Bebas Neue / Oswald (SIL OFL) to `fonts/` and register with licence in `config/fonts.yaml`.
7. **Docker files / systemd units** were written but not built or run here.

**Ongoing manual duties:** approve every post; do native-audio steps in the Instagram app; launch paid ads in Ads Manager
yourself; review Meta API/permission changes; rotate `RS_SECRET_KEY`/token if leaked (reconnect account); run `pip-audit`.

**Not done / not claimed:** viral predictions (scores are heuristics), follower-attribution per reel, App Review submission,
multi-account/multi-user support, render queue in a separate worker process.
