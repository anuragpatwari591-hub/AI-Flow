# Security

Security is treated as a first-class requirement, not an afterthought,
because AI Flow automates interactions with sites the user is authenticated
into. This document explains the controls in place and the reasoning
behind them.

## Hard constraints (never violated)

AI Flow will never:

- Store passwords, raw authentication credentials, session cookies, or
  private keys.
- Attempt to bypass, defeat, spoof, or otherwise circumvent a CAPTCHA,
  rate limit, authentication requirement, or other provider access
  control.
- Call an undocumented/private endpoint specifically to evade a limit.
- Perform "stealth" automation designed to look like something other than
  what it is.
- Submit a message to a conversation it could not verify.
- Silently change the user's task, instructions, or attached files.
- Retry an authentication failure, a malformed job, or an unsupported
  operation indefinitely (see `docs/architecture.md#retry-engine`).

If a job reaches a state where continuing safely isn't possible —
authentication required, conversation can't be verified, unsupported
operation — it moves to `REQUIRES_USER_ACTION` and the user is notified.
It never guesses.

## Permissions

`manifest.json` requests only:

- `storage`, `unlimitedStorage` — job/settings persistence and IndexedDB.
- `alarms` — the scheduler.
- `notifications` — user-facing status notifications.
- `sidePanel` — the dashboard UI.
- `scripting`, `tabs` — to open a job's conversation tab and inject the
  generic content script into it on demand.

Host permissions for provider domains (`claude.ai`, `chatgpt.com`, etc.)
are declared under `optional_host_permissions` and requested at runtime,
one domain at a time, only when the user adds that provider to a job (see
`src/security/permissions.ts`). AI Flow never requests `<all_urls>` or a
broad host pattern.

## Content script model

The content script (`src/content/content-script.ts`) is **not** a
standing, always-injected script. It is injected on demand via
`chrome.scripting.executeScript` only into a tab the user's own job just
opened, and only after the corresponding host permission was granted. It
exposes a small set of generic actions (insert text into a field, click a
button, read text, scan for text patterns, attach a file to a file input)
driven entirely by selectors that live in the calling provider adapter
(`src/providers/*/**-adapter.ts`). The content script itself contains no
provider-specific logic and never executes arbitrary code sent to it.

## Conversation verification

Before any message is composed or submitted, the provider adapter's
`verifyConversation()` checks the open tab's URL against the job's
configured conversation URL (and id/title where available). If verification
fails, the job moves to `REQUIRES_USER_ACTION` rather than sending the
prompt to whatever conversation happens to be open (`src/providers/interface/dom-provider-base.ts`).

## Loop and duplication protection

- Every submission is fingerprinted (`src/core/jobs/loop-protection.ts`);
  an identical fingerprint is never resubmitted.
- `MAX_CONTINUATIONS` and `MAX_EXECUTION_TIME_MS` bound autonomous
  continuation so a misbehaving job can't loop forever.
- Attachments already marked `UPLOADED` are never re-uploaded on retry.

## Storage and encryption

- Job metadata and settings: `chrome.storage.local` (this device only).
- Attachment contents: IndexedDB (this device only).
- Optional encrypted export uses AES-GCM with a PBKDF2-derived key
  (210,000 iterations, SHA-256) — see `src/security/encryption/encryption.ts`.
  This is for the user's own backup file, not for anything AI Flow stores
  itself.

## Content Security Policy

Extension pages are restricted via `content_security_policy.extension_pages`
to `script-src 'self'; object-src 'self'; base-uri 'self';` — no remote
code, no inline scripts.

## Logging

Structured logs (`src/core/events/logger.ts`) run every message through a
best-effort secret-redaction pass (`sanitizeForLog`) before it's stored, as
defense in depth on top of "never collect secrets in the first place".

## Reporting a vulnerability

See `SECURITY.md` at the repository root.
