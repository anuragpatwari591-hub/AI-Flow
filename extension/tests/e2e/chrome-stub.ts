/**
 * Minimal chrome.* stub injected into the page before any script runs, so
 * the side panel's React app (which normally talks to the real extension
 * service worker) can render standalone in a plain browser tab for this
 * best-effort e2e smoke test. Responses are just enough for the UI to
 * reach a stable, testable state — this is not a substitute for loading
 * the real packed extension (see docs/troubleshooting.md).
 */
export function installChromeStub(): void {
  const settings = {
    defaultProvider: "mock",
    defaultExecutionMode: "SEMI_AUTOMATIC",
    maxRetries: 6,
    retryStrategyJitter: true,
    notifyOnWaiting: true,
    notifyOnResumed: true,
    notifyOnRequiresAction: true,
    notifyOnCompleted: true,
    notifyOnFailed: true,
    maxContinuations: 25,
    confirmBeforeSubmission: false,
    confirmBeforeUpload: false,
    debugLogging: false,
    theme: "light",
    reducedMotion: false,
  };

  const providers = [
    { id: "mock", displayName: "Mock Provider (simulation)", domains: ["mock.aiflow.local"], experimental: false },
  ];

  function respond(request: { type: string }) {
    switch (request.type) {
      case "LIST_JOBS":
        return { jobs: [] };
      case "GET_SETTINGS":
        return settings;
      case "LIST_PROVIDERS":
        return { providers };
      case "LIST_PROVIDER_PERMISSIONS":
        return { origins: [] };
      default:
        return {};
    }
  }

  (window as unknown as { chrome: unknown }).chrome = {
    runtime: {
      sendMessage: (request: { type: string }) => Promise.resolve({ ok: true, data: respond(request) }),
    },
    storage: {
      onChanged: {
        addListener: () => {},
        removeListener: () => {},
      },
    },
  };
}
