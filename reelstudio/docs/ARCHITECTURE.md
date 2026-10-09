# Architecture & milestone plan

## Shape of the system

```
            ┌────────────── dashboard (static HTML/JS, bearer-token gated) ──────────────┐
            │                                                                             │
 research ─▶│ FastAPI (api/app.py) ── SQLAlchemy ── PostgreSQL (SQLite in dev/tests)      │
 sources    │    │                                                                        │
            │    ├─ trends/      sources → scoring → ranked Trend rows (signals labelled)  │
            │    ├─ reference/   supplied-file measurements + inspected-only observations  │
            │    ├─ writing/     AIProvider (local_seed | anthropic) → validate → score    │
            │    ├─ audio/       asset registry, rights policy, beat analysis, matching    │
            │    ├─ render/      template spec → Pillow text layer → FFmpeg → QA           │
            │    ├─ publishing/  approval queue, preflight, scheduler, audit               │
            │    ├─ instagram/   official API client, OAuth, token lifecycle, insights     │
            │    ├─ analytics/   own-baseline comparison, breakdowns, adaptive mix         │
            │    └─ ads/         campaign drafts, variants, 5-item approval, export only   │
            └─────────────────────────────────────────────────────────────────────────────┘
 worker (worker.py): run_due() → token_upkeep() → collect_due()   every 30 s, one process
```

Provider-specific code lives behind small seams so each piece is replaceable:

| Seam | Interface | Implementations |
|---|---|---|
| Text generation | `writing.types.AIProvider.generate_concepts` | `LocalSeedProvider`, `AnthropicProvider` |
| Trend input | `trends.sources.TrendSource.fetch` | manual JSON/CSV export, seasonal calendar, RSS, credentialed-API placeholder |
| Social API | `instagram.client.IGClient` | Instagram API (Instagram Login), official endpoints only |
| Secrets | `instagram.secrets.TokenCipher` | Fernet key from `RS_SECRET_KEY` (swap for a KMS/secret manager that injects the env var) |
| Media hosting | `publishing.media.public_url` | signed URLs served by this app behind HTTPS |

## Data model (db.py)
`Trend`, `ReferenceItem`, `Concept`, `PublishedLine`, `AudioAsset`, `Reel`, `IGAccount`, `PublishJob`, `AuditLog`,
`Setting`, `MetricSnapshot`, `AdCampaign`, `AdVariant`. Migrations: `migrations/versions/0001_initial_schema.py`
(`reelstudio migrate`; `alembic check` reports no drift).

## Publishing state machine
```
pending_approval ─approve(human)─▶ scheduled ─claim─▶ publishing ─▶ published
      │ reject/cancel                 │ cancel            │ transient/rate-limit ─▶ scheduled (backoff, same container)
      ▼                               ▼                   └ permanent / attempts exhausted ─▶ failed (alert)
 rejected / cancelled
```
Every transition writes an `AuditLog` row. Claiming is an atomic `UPDATE … WHERE status='scheduled'`.
Idempotency key = hash(account, video sha256): the same media cannot be queued twice for an account.
Preflight (re-run at approval **and** at publish time): render complete, media QA passed, file hash unchanged,
cover present, caption sane + no email/phone/link, audio rights cleared for publishing, destination account
eligible/enabled/token valid, named approval present, scheduler not paused.

## Milestones (all implemented; see README for test status)
1. Trend research + reference library  2. Writing + scoring  3. Rendering + previews  4. DB + dashboard
5. Instagram integration  6. Approval queue + scheduling  7. Analytics loop  8. Ads + security review.
