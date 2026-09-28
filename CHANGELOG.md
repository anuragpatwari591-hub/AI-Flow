# Changelog

All notable changes to AI Flow are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

## [0.1.0] - 2026-09-27

### Added

- Initial MVP release of AI Flow.
- Job model and deterministic job state machine (`DRAFT` → ... →
  `COMPLETED` / `FAILED` / `CANCELLED`).
- Local-first storage: job metadata and settings in `chrome.storage.local`,
  attachment blobs in IndexedDB.
- Scheduler built on `chrome.alarms` with startup reconciliation for
  service-worker restarts.
- Exponential-backoff retry engine with per-error-type policies.
- Append-only checkpoint system with rollback support.
- Structured continuation prompt composer.
- `AIProviderAdapter` interface and a fully simulated `MockAIProvider`
  covering available / limited / auth-required / upload-failure /
  network-failure / long-running / conversation-mismatch scenarios.
- Experimental, clearly-documented Claude / ChatGPT / Gemini adapters that
  perform only safe, visible-DOM interactions and verify conversation
  identity before submitting anything.
- Availability engine with `AVAILABLE / LIMITED / AUTH_REQUIRED /
  NETWORK_ERROR / UNKNOWN / PROVIDER_ERROR` states.
- Side panel dashboard (Overview, Jobs, Queue, Waiting, Completed, Failed,
  History, Settings, Providers, Security, Logs).
- Job creation wizard with a review step before submission.
- Attachment manager with MIME/size/duplicate validation.
- Notification system with per-event preferences and anti-spam batching.
- JSON export/import, with optional AES-GCM encrypted export.
- Structured, secret-free logging.
- Unit and integration test suites (Vitest) plus a best-effort Playwright
  e2e test for the side panel UI.
- Full documentation set under `docs/`.

### Known limitations

- Real provider adapters are best-effort: they rely on visible page text and
  standard form elements, which can break when a provider changes its UI.
  When verification fails, jobs move to `REQUIRES_USER_ACTION` rather than
  guessing.
- No cloud sync, team collaboration, or remote dashboard (see roadmap in
  `README.md`).
