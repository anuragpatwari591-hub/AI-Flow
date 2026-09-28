# Contributing to AI Flow

Thanks for your interest in contributing! AI Flow is a browser extension
built with TypeScript, React, and Vite. This document explains how to get a
development environment running and the conventions we follow.

## Ground rules

1. **Never bypass provider protections.** Any change that helps AI Flow
   defeat CAPTCHAs, spoof authentication, evade rate limits, or scrape
   credentials will be rejected outright, regardless of how useful it seems.
2. **Local-first, privacy-first.** Don't introduce a remote server or
   telemetry endpoint that receives prompts, files, or conversation content
   without an explicit, opt-in setting and documentation update.
3. **No half-finished features.** If you can't finish a provider adapter
   safely, implement the `AIProviderAdapter` interface and document the gap
   instead of a fake integration.
4. **State machine, not booleans.** Job status transitions belong in
   `src/core/state-machine/job-state-machine.ts`. Don't add parallel status
   flags elsewhere.

## Getting started

```bash
git clone https://github.com/<your-org>/ai-flow.git
cd ai-flow
npm install
npm run dev
```

`npm run dev` starts the Vite dev server for the side panel / popup / options
UI. To exercise the full extension (service worker + content scripts), build
it and load it as an unpacked extension:

```bash
npm run build
```

Then, in Chrome/Edge/Brave: `chrome://extensions` → enable **Developer
mode** → **Load unpacked** → select `extension/dist`.

## Project layout

See `docs/architecture.md` for a full breakdown. In short:

- `extension/src/core` — provider-agnostic engines (state machine, scheduler,
  retry, checkpoints, prompt composer, storage)
- `extension/src/providers` — the `AIProviderAdapter` interface, the
  `MockAIProvider`, and per-provider adapters
- `extension/src/background`, `content`, `sidepanel`, `popup`, `options` —
  the extension surfaces
- `extension/tests` — unit, integration, and e2e tests

## Before opening a PR

```bash
npm run typecheck
npm run lint
npm run test
npm run build
```

All four must pass. Add unit tests for new core logic and integration tests
for new cross-module behavior.

## Adding a provider adapter

See `docs/provider-adapters.md`. New adapters must:

- Implement the full `AIProviderAdapter` interface
- Only read visible page state and interact with standard UI elements
  (typing into a compose box, clicking a send button, reading rendered text)
- Never call undocumented private APIs to evade limits
- Fail into `REQUIRES_USER_ACTION` when the conversation or provider state
  cannot be verified, rather than guessing

## Commit style

Use clear, imperative commit messages (`Add retry backoff jitter`, not
`fixed stuff`). Reference issues where relevant.

## Code of Conduct

By participating, you agree to abide by our `CODE_OF_CONDUCT.md`.
