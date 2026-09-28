import { defineConfig } from "@playwright/test";

// Best-effort e2e: exercises the side panel UI as a standalone static page
// served over http, without loading the packed extension (loading an
// unpacked MV3 extension requires a persistent browser context, which is
// impractical in most headless CI sandboxes). Chrome-API calls are mocked
// in tests/e2e/fixtures.ts. See docs/troubleshooting.md for how to run a
// full manual extension load-test instead.
export default defineConfig({
  testDir: "./tests/e2e",
  timeout: 30_000,
  fullyParallel: true,
  webServer: {
    command: "npx vite preview --port 4173",
    port: 4173,
    reuseExistingServer: !process.env.CI,
    timeout: 60_000,
  },
  use: {
    baseURL: "http://localhost:4173",
    // Set PLAYWRIGHT_CHROMIUM_PATH to point at a pre-installed Chromium
    // binary in sandboxes where `npx playwright install` can't reach the
    // network or where the installed revision doesn't match this
    // package's pinned @playwright/test version. See docs/troubleshooting.md.
    ...(process.env.PLAYWRIGHT_CHROMIUM_PATH
      ? { launchOptions: { executablePath: process.env.PLAYWRIGHT_CHROMIUM_PATH } }
      : {}),
  },
});
