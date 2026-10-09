# Reel Studio — review-first Gen Z Reel automation

Research trends → write original text-led Reels → render 1080×1920 H.264/AAC with FFmpeg → check rights & media →
approval queue → publish through **official** Instagram APIs → measure against your own baseline → feed results back.
Default mode is **REVIEW REQUIRED**: nothing is published or spent without a named human approval.

> Lives in `reelstudio/` inside the AI-Flow repo (independent of the browser extension in the repo root).

## One command
`reelstudio setup` (resumable) and `reelstudio setup --check` (read-only blockers report) — see `docs/SETUP.md`.

## Quick start (dev, SQLite)
```bash
cd reelstudio
python -m venv .venv && . .venv/bin/activate && pip install -e ".[dev]"
cp .env.example .env && reelstudio gen-keys    # paste RS_SECRET_KEY / RS_DASHBOARD_TOKEN into .env
reelstudio generate --per-category 1           # offline seed writer works without any API key
reelstudio render 1                            # -> data/renders/reel_1/{preview.mp4,reel.mp4,cover.jpg}
reelstudio serve                               # dashboard at http://127.0.0.1:8000  (token from .env)
pytest                                         # whole suite; RS_TEST_DATABASE_URL=postgresql+psycopg://… for Postgres
```
Production: PostgreSQL + `reelstudio migrate` + `reelstudio worker` — see `docs/DEPLOYMENT.md`.
FFmpeg must be on PATH. (Playwright's bundled Chromium can't play H.264 previews; use a normal browser.)

## What exists (and how far it is verified)
| Stage | Module | Verified |
|---|---|---|
| 1 Trends, reference library | `trends/`, `reference/` | unit tests; measured/estimate/unavailable signals; unverified audio capped; observations require inspection |
| 2 Writing + scoring | `writing/`, `config/voice_guide.yaml` | tests; repetition DB, banned phrases, timing; Anthropic provider vs mock only |
| 3 Rendering | `render/`, `config/templates/*.yaml`, `config/fonts.yaml` | real FFmpeg renders at 1080×1920 + QA; visually inspected frames/covers |
| Audio & rights | `audio/` | rights gating tested; beats tested on synthetic clicks only |
| 4 DB + dashboard | `db.py`, `api/`, `migrations/` | suite passes on SQLite **and** PostgreSQL 16; `alembic check` clean; dashboard driven in Chromium, no console errors |
| 5 Instagram | `instagram/` | **fake Graph API only — not tested on a live account** (`docs/INSTAGRAM_SETUP.md`) |
| 6 Queue/scheduling | `publishing/` | tested: approval, retry/backoff, rate limit, duplicate, pause, revoke, audit |
| 7 Analytics | `analytics/` | tested: matched-age robust baseline, min samples, winners, exploration floor |
| 8 Ads + security | `ads/`, `docs/SECURITY_REVIEW.md` | tested; no Ads API code at all (export + manual launch) |

## Key behaviours
- **Rights:** `unverified` audio is never rendered/published/advertised; Instagram-native sounds are a manual step; licence refs and attribution are stored and attribution is appended to captions.
- **Branding:** ANURAG / AP STUDIOS credit is opt-in per category in `voice_guide.yaml` (`branding.apply_to_categories`, empty by default), never on aesthetic Reels.
- **Rendering config:** every visual setting (font, size, colours, safe margins, animation, grain, footage background, pacing, beat snap, bitrate) is in YAML templates or per-reel overrides, validated by `render/spec.py`. Fonts without a licence record are refused.
- **Writing:** originality is guarded by banned phrases and similarity to all previously published lines; scores are *text-quality heuristics*, not performance forecasts.
- **Analytics:** a verdict needs ≥5 prior reels at matched age (~48 h); a group "winner" needs ≥3 reels per group and a ≥20 % lead; missing metrics are shown as n/a.

## Docs
`SETUP.md` · `ARCHITECTURE.md` · `INSTAGRAM_SETUP.md` · `DEPLOYMENT.md` · `SECURITY_REVIEW.md` · `MANUAL_STEPS.md` (blockers & remaining manual work)

## Layout
```
config/ (trends, voice guide, fonts, templates, automation)   src/reelstudio/{trends,reference,writing,audio,render,
instagram,publishing,analytics,ads,api}   migrations/   tests/   docs/   deploy/
```
