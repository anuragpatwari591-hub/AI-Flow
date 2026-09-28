# AI Flow

**Queue once. Resume automatically.**

AI Flow is a local-first browser extension that orchestrates and resumes AI
tasks across browser-based AI providers. Define a task once, attach files,
pick a provider and conversation, and AI Flow will wait for legitimate
provider availability and resume the task automatically — without ever
bypassing rate limits, authentication, or CAPTCHAs.

> AI Flow is an automation/orchestration layer, not a limit-bypass tool.
> When a provider is unavailable because of a legitimate usage limit, AI
> Flow waits and retries later.

## What is AI Flow?

A Chrome/Chromium Manifest V3 extension that turns "I have to remember to
come back and re-paste this prompt when my limit resets" into "queue it
once and get notified when it's done." Under the hood it's a small,
understandable system:

```
Browser Extension + Job Queue + Scheduler + State Machine
+ Provider Adapter + File Manager + Checkpoint System
+ Retry Engine + Security Layer
```

## Features

- **Job system** with a deterministic state machine (`DRAFT` → `QUEUED` →
  `WAITING_FOR_AVAILABILITY` → `READY` → `RUNNING` → `UPLOADING` →
  `SUBMITTING` → `PROCESSING` → `WAITING_FOR_RESPONSE` → `CONTINUING` →
  `COMPLETED` / `FAILED` / `PAUSED` / `CANCELLED` / `REQUIRES_USER_ACTION`).
- **Job creation wizard** with a review step before queuing.
- **Attachment manager**: PDF, DOCX, TXT, CSV, XLSX, images, ZIP, common
  source files — validated for size, type, and duplicates; metadata and
  file contents are stored separately.
- **Structured continuation prompts** (current objective / state /
  completed work / remaining work / constraints / next action / validation
  requirements) so continuations never duplicate work or restart from
  scratch.
- **Append-only checkpoint system** with restart-from-checkpoint.
- **Availability engine**: `AVAILABLE / LIMITED / AUTH_REQUIRED /
  NETWORK_ERROR / UNKNOWN / PROVIDER_ERROR`, never fabricates a reset time.
- **Scheduler** on `chrome.alarms`, with startup reconciliation that
  survives service-worker restarts.
- **Exponential-backoff retry engine** with per-error-type policies (auth
  failures and malformed jobs are never retried).
- **Loop protection**: submission fingerprints, `MAX_CONTINUATIONS`,
  `MAX_EXECUTION_TIME_MS`.
- **Provider abstraction** with a fully simulated `MockAIProvider` (used in
  the test suite and available in the UI for demos) plus experimental
  Claude/ChatGPT/Gemini adapters.
- **Dashboard** (Overview, Active, Queue, Waiting, Completed, Failed,
  History, Providers, Security, Logs), pause/resume/retry/cancel/duplicate
  controls, dark/light theme, reduced-motion support.
- **JSON export/import**, with an optional AES-GCM encrypted export.
- **Structured, secret-redacted logging**.

## Architecture

See [`docs/architecture.md`](docs/architecture.md) for the full breakdown,
including diagrams of the job lifecycle and the end-to-end request flow.

## Installation

```bash
git clone <repo-url>
cd ai-flow
npm install
npm run build
```

Then in Chrome/Edge/Brave: `chrome://extensions` → enable **Developer
mode** → **Load unpacked** → select `extension/dist`.

## Development

```bash
npm install
npm run dev        # Vite dev server for the side panel/popup/options UI
npm run build       # full production build -> extension/dist
npm run test         # Vitest unit + integration tests
npm run typecheck
npm run lint
```

See [`docs/development.md`](docs/development.md) for the full guide.

## Supported browsers

Any Chromium-based browser supporting Manifest V3 and the Side Panel API:
Chrome 116+, Edge, Brave. Firefox is not currently supported (different
extension APIs).

## Usage

1. Open the side panel (toolbar icon → "Open dashboard", or the panel
   icon) and click **+ New job**.
2. Fill in the task name, pick a provider, and paste the conversation URL.
3. Write the instructions and (optionally) a step checklist used to track
   progress/continuation.
4. Attach files/images if needed, choose an execution mode (Manual /
   Semi-automatic / Autonomous), priority, and retry settings.
5. Review, then **Queue job now**.
6. AI Flow waits for the provider to be available, opens and verifies the
   conversation, uploads files, submits the prompt, and — depending on
   execution mode — continues automatically or pauses for your approval
   after each step.

Example, from the design brief this project was built against:

```
JOB CREATED -> FILES VALIDATED -> CONVERSATION VERIFIED -> PROMPT PREPARED
  -> PROVIDER LIMIT DETECTED -> WAITING -> AVAILABILITY CHECK -> AVAILABLE
  -> FILES VERIFIED -> PROMPT SUBMITTED -> AI WORKS -> CHECKPOINT CREATED
  -> NEXT STEP GENERATED -> CONTINUE -> COMPLETED
```

## Permissions

`storage`, `unlimitedStorage`, `alarms`, `notifications`, `sidePanel`,
`scripting`, `tabs` — always on, and needed for the extension to function
locally. Provider host permissions (e.g. `https://claude.ai/*`) are
`optional_host_permissions`, requested one domain at a time only when you
add that provider to a job. Full rationale in
[`docs/security.md#permissions`](docs/security.md#permissions).

## Security

No credential storage, no CAPTCHA/rate-limit bypassing, no stealth
automation, fail-closed conversation verification, loop protection, a
locked-down extension-pages CSP. Full details:
[`docs/security.md`](docs/security.md). Found a vulnerability?
See [`SECURITY.md`](SECURITY.md).

## Privacy

Local-first: job metadata and settings in `chrome.storage.local`,
attachment contents in IndexedDB, nothing synced to a remote AI Flow
server (there isn't one). Full details: [`docs/privacy.md`](docs/privacy.md).

## Provider adapters

`AIProviderAdapter` interface + a fully simulated `MockAIProvider`, plus
experimental Claude/ChatGPT/Gemini adapters built on a shared DOM-interaction
base. See [`docs/provider-adapters.md`](docs/provider-adapters.md) for how
they work, their known limitations, and how to add a new one.

## Troubleshooting

See [`docs/troubleshooting.md`](docs/troubleshooting.md).

## Roadmap

Architected so these can be added later without a rewrite: AI provider
marketplace, opt-in cloud sync, team collaboration / shared queues, a
remote dashboard, mobile notifications, a desktop companion, official
provider API integrations (where available), local LLM support, workflow
templates, AI-generated workflow planning, and integrations (GitHub,
Google Drive, Notion, Slack, email).

## Contributing

See [`CONTRIBUTING.md`](CONTRIBUTING.md). Please also read the ground
rules there before proposing anything that touches provider automation.

## License

[MIT](LICENSE)
