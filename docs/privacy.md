# Privacy

AI Flow is local-first by default. This page states plainly what is stored,
where, and what (if anything) ever leaves your device.

## What is stored

| Data | Where | Notes |
|---|---|---|
| Job metadata (title, instructions, status, history, checkpoints) | `chrome.storage.local` | Never leaves the device automatically. |
| Attachment file contents | IndexedDB | Kept separate from job metadata so exporting/inspecting jobs never drags file contents along by accident. |
| Settings | `chrome.storage.local` | Defaults, notification preferences, retry policy, theme, etc. |
| Logs | Embedded in job history (`chrome.storage.local`) | Secrets are redacted before being written (`src/core/events/logger.ts`). |

Nothing is stored on a remote AI Flow server, because there isn't one.

## What data leaves the device

The **only** network requests AI Flow's own code makes are to the provider
site a job is configured to use (e.g. `claude.ai`), and only when a job on
that provider is actually running — to open the conversation tab and let
the content script read/interact with that page. AI Flow does not:

- run its own backend or telemetry endpoint,
- send prompts, instructions, files, or conversation contents anywhere
  other than the provider's own site the user is already signed into,
- phone home usage statistics.

If a future version adds an optional cloud-sync feature, it will be
opt-in, clearly disclosed, and documented here before it ships.

## What permissions are required, and why

See `docs/security.md#permissions` for the full list. In short:
`storage`/`alarms`/`notifications`/`sidePanel`/`scripting`/`tabs` for the
extension to function locally, plus a per-provider host permission
requested only when you add that provider to a job.

## What provider websites are accessed

Only the ones you explicitly configure on a job (e.g. `claude.ai`,
`chatgpt.com`, `gemini.google.com`), and only while a job for that provider
is actively running or being checked for availability.

## Your controls

- **Export**: Settings → Export data, produces a plain JSON file
  (`ai-flow-backup-<date>.json`) with your jobs, checkpoints, and settings.
  An encrypted export option is also available (AES-GCM, passphrase-based).
- **Import**: restore from a previous export.
- **Reset local data**: Security panel → "Reset all local data" permanently
  deletes every job, checkpoint, attachment, and setting on this device.
  This is destructive and requires explicit confirmation — AI Flow never
  deletes user data automatically.
- **Revoke provider access**: remove a granted host permission at any time
  via `chrome://extensions` → AI Flow → Site access, or via the
  Providers panel.

## Data AI Flow will never collect

Passwords, session cookies, API keys, or any other authentication
credential — see `docs/security.md` for the full list of hard constraints.
