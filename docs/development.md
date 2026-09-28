# Development guide

## Prerequisites

- Node.js 20+ and npm 10+
- A Chromium-based browser (Chrome, Edge, Brave) for manual testing

## Setup

```bash
git clone <repo-url>
cd ai-flow
npm install
```

This is an npm workspaces repo: the root `package.json` delegates to
`extension/`.

## Scripts (run from the repo root)

| Command | What it does |
|---|---|
| `npm run dev` | Starts the Vite dev server for the side panel/popup/options UI (hot reload for UI work; the service worker/content script still need a full build to test). |
| `npm run build` | Type-checks, builds the UI with Vite, bundles the service worker and content script with esbuild, generates icons, and copies `manifest.json` into `extension/dist`. |
| `npm run typecheck` | `tsc --noEmit` across the whole extension package. |
| `npm run lint` | ESLint over `src` and `tests`. |
| `npm run test` | Vitest (unit + integration). |
| `npm run e2e` | Playwright, from inside `extension/` (see below). |

## Loading the extension for manual testing

```bash
npm run build
```

Then in Chrome: `chrome://extensions` → enable **Developer mode** →
**Load unpacked** → select `extension/dist`.

Click the AI Flow toolbar icon to open the popup, or use its "Open
dashboard" button (or the side panel icon) to open the full dashboard.

## Working on the UI only

`npm run dev` (from `extension/`) starts Vite's dev server, which is the
fastest loop for iterating on the React components. Because the UI talks to
`chrome.runtime`, it won't function standalone in a plain browser tab
unless you stub `window.chrome` — see `extension/tests/e2e/chrome-stub.ts`
for exactly that kind of stub, used by the Playwright smoke test.

## Working on the background/content scripts

These aren't served by Vite's dev server (they're not DOM pages); after
editing `src/background/*` or `src/content/*`, run `npm run build` and
reload the unpacked extension in `chrome://extensions`.

## Tests

- `extension/tests/unit/*.test.ts` — pure logic: state machine, retry
  engine, availability engine, checkpoint store, prompt composer,
  scheduler (via a fake alarms clock), job manager, the mock provider,
  export/import, loop protection, file validation.
- `extension/tests/integration/*.test.ts` — the job runner driven end to
  end against `MockAIProvider` (happy path, waiting on a limit,
  auth-required, conversation mismatch, duplicate-submission protection,
  the continuation cap) and startup reconciliation after a simulated
  service-worker restart.
- `extension/tests/e2e/*.spec.ts` — a best-effort Playwright smoke test of
  the side panel UI. Run with:

  ```bash
  cd extension
  npx playwright test
  ```

  If your sandbox has a pre-installed Chromium that doesn't match this
  repo's pinned Playwright version, set `PLAYWRIGHT_CHROMIUM_PATH` to its
  binary instead of running `npx playwright install` (see
  `docs/troubleshooting.md`).

## Adding a core feature

1. If it changes what a job can be doing, start in
   `src/core/state-machine/job-state-machine.ts` — add the event/transition
   there first, with a unit test.
2. Wire the behavior into `src/core/jobs/job-runner.ts`.
3. If it needs new persisted state, add it to `Job` in
   `src/core/jobs/job.model.ts`.
4. Expose it to the UI via a new `UiRequest` variant in
   `src/core/messaging/protocol.ts` and a handler in
   `src/background/message-router.ts`.
5. Add the UI in `src/ui/components/`.

## Adding a provider

See `docs/provider-adapters.md`.

## Code style

- TypeScript strict mode; avoid `any`.
- No comments explaining *what* code does — only *why*, when non-obvious.
- Don't add abstractions, config flags, or error handling for scenarios
  that can't happen.
