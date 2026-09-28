# Provider adapters

## The interface

Every provider integration implements `AIProviderAdapter`
(`extension/src/providers/interface/types.ts`):

```ts
interface AIProviderAdapter {
  readonly id: string;
  readonly displayName: string;
  readonly domains: string[];

  getAvailability(): Promise<AvailabilityResult>;
  openConversation(conversationUrl: string): Promise<{ tabId: number }>;
  verifyConversation(tabId: number, expected: ConversationMetadata): Promise<VerifyConversationResult>;
  attachFile(tabId: number, file: FileToAttach): Promise<AttachFileResult>;
  verifyAttachment(tabId: number, file: FileToAttach): Promise<AttachFileResult>;
  composeMessage(tabId: number, text: string): Promise<{ success: boolean; reason?: string }>;
  submitMessage(tabId: number): Promise<SubmitResult>;
  readConversationState(tabId: number): Promise<ReadConversationStateResult>;
  detectLimitState(tabId: number): Promise<boolean>;
  detectAuthenticationRequired(tabId: number): Promise<boolean>;
  detectErrors(tabId: number): Promise<string[]>;
  getConversationMetadata(tabId: number): Promise<ConversationMetadata>;
}
```

Core logic (`JobRunner`, the UI) depends only on this interface. Nothing
outside a provider's own adapter file knows a single CSS selector for that
provider.

## MockAIProvider

`extension/src/providers/mock/mock-provider.ts` is a fully simulated
implementation used throughout the test suite and available in the UI as
the `mock` provider for demos. It supports scripted scenarios:

`AVAILABLE`, `LIMITED`, `LIMITED_WITH_KNOWN_RETRY`, `AUTH_REQUIRED`,
`UPLOAD_FAILURE`, `NETWORK_FAILURE`, `LONG_RUNNING`,
`CONVERSATION_MISMATCH`, `PROVIDER_ERROR`.

This lets the entire job lifecycle — including waiting, backoff, retries,
checkpoints, and continuation — be exercised deterministically without a
real AI service being reachable or in any particular state.

## DOM-based adapters (Claude, ChatGPT, Gemini)

`extension/src/providers/interface/dom-provider-base.ts` implements the
shared plumbing for a "real" adapter: opening a tab, injecting the generic
content script on demand, and translating interface calls into content
script actions (`INSERT_TEXT`, `CLICK`, `READ_TEXT`, `ATTACH_FILE`,
`SCAN_PATTERNS`, `ELEMENT_EXISTS` — see
`extension/src/core/messaging/content-protocol.ts`).

Each concrete adapter (`claude/claude-adapter.ts`, `chatgpt/chatgpt-adapter.ts`,
`gemini/gemini-adapter.ts`) supplies only a small `ProviderDomConfig`:
CSS selectors for the compose box, send button, file input, a
"generating" indicator, the latest response, and a handful of regular
expressions used to detect usage-limit / sign-in-required / error text on
the page.

### Status: experimental / best-effort

These adapters are marked `experimental` in the provider registry. Their
selectors were written against each provider's public web UI as commonly
documented, but:

- **They have not been validated against live, authenticated sessions in
  this environment** (this repository was built without live access to
  claude.ai / chatgpt.com / gemini.google.com credentials). Treat them as
  a working skeleton, not a guarantee.
- Provider web UIs change their markup without notice. When a selector
  stops matching, the corresponding adapter call fails, and — by design
  — the job moves to `REQUIRES_USER_ACTION` rather than silently doing
  nothing or clicking the wrong element.
- `verifyConversation()` always checks the open tab's URL against the
  job's configured conversation URL before anything is typed or sent, so a
  stale selector can cause a job to stall, but it cannot cause AI Flow to
  send a prompt to the wrong conversation.

If you use a real provider adapter and a selector needs updating, the fix
is scoped entirely to that provider's `*-adapter.ts` file — the core
engines, tests, and other adapters are unaffected.

## Safety rules every adapter must follow

- Only use visible page state and standard UI interactions (or an official
  documented API, if one exists for that provider).
- Never attempt to bypass authentication, CAPTCHAs, or rate limits.
- Never call an undocumented/private endpoint to evade a limit.
- Fail closed: if something can't be verified, return a result that says
  so. Never guess.

## Adding a new provider

1. Create `extension/src/providers/<id>/<id>-adapter.ts` extending
   `DomProviderAdapterBase` with a `ProviderDomConfig` (see the existing
   adapters for the shape), **or** implement `AIProviderAdapter` directly
   if the provider exposes an official API instead of a web UI.
2. Register it in `extension/src/providers/provider-registry.ts`
   (`createDefaultProviderRegistry`).
3. Add its domain(s) to `optional_host_permissions` in `manifest.json`.
4. If you can't safely or reliably automate a given provider, that's a
   legitimate outcome: implement the interface, document the limitation
   here, and leave it registered as `experimental` (or don't register a
   DOM adapter at all and rely on `MockAIProvider` for that provider id
   in the meantime) rather than pretending the integration works.
5. Open a PR using the "Provider adapter request" issue template as a
   checklist for what reviewers will ask.
