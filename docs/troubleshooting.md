# Troubleshooting

## The extension doesn't load / "Manifest file is missing or unreadable"

Make sure you ran `npm run build` first and pointed **Load unpacked** at
`extension/dist`, not the repo root or `extension/`.

## A job is stuck in "Waiting for availability"

This is expected behavior when a provider reports a usage limit or an
unknown/error state — AI Flow waits and retries with exponential backoff
instead of repeatedly hitting the provider (see `docs/security.md`). Check
the job's log for the most recent `PROVIDER_LIMIT_DETECTED` / `JOB_WAITING`
entry and its "next attempt" time. If a job has been waiting far longer than
expected, open the provider's site yourself to confirm what state it's
actually in — AI Flow deliberately never claims a specific reset time
unless the provider itself reported one.

## A job says "Needs your action" (`REQUIRES_USER_ACTION`)

This means AI Flow could not safely continue automatically. Common causes:

- **Authentication required** — sign in to the provider yourself, then hit
  **Retry** on the job.
- **Conversation could not be verified** — the open tab's URL didn't match
  the job's configured conversation URL, or (for DOM-based adapters) the
  provider's page markup changed and a selector no longer matches. Check
  `docs/provider-adapters.md` for that provider's known limitations.
- **Retry budget exhausted** — the job hit its configured maximum retry
  attempts. Adjust "Maximum retry attempts" when duplicating/retrying the
  job if the underlying issue is resolved.

## The DOM-based provider adapter (Claude/ChatGPT/Gemini) isn't working

These adapters are marked **experimental** for a reason — see
`docs/provider-adapters.md#status-experimental--best-effort`. If a
provider changed its UI, the fix is isolated to that provider's
`*-adapter.ts` selector config.

## Playwright e2e tests fail with "Executable doesn't exist"

Your environment's pre-installed Chromium revision doesn't match this
repo's pinned `@playwright/test` version. Either run
`npx playwright install` (needs network access), or point at a
pre-installed binary:

```bash
PLAYWRIGHT_CHROMIUM_PATH=/path/to/chrome npx playwright test
```

## `npm install` fails / workspace errors

Confirm you're on Node 20+ and running `npm install` from the **repo
root** (not `extension/`) so the npm workspaces setup resolves correctly.

## I don't see the side panel icon

Some Chromium builds hide the side panel entry point until a page enables
it. Use the popup's "Open dashboard" button, which calls
`chrome.sidePanel.open()` directly.

## Notifications aren't showing up

Check Settings → Notifications — each event type (waiting, resumed,
requires action, completed, failed) can be toggled independently. Also
confirm your OS hasn't blocked notifications for your browser.

## I want to start over

Security panel → "Reset all local data". This is destructive and
irreversible — export a backup first (Settings → Export data) if you
might want any of it later.
