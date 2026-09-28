// Bundles the MV3 service worker (ESM) and the generic content script (IIFE)
// with esbuild. These run outside the DOM-based Vite build because Chrome
// service workers and content scripts have different module/format
// requirements than the side panel / popup / options HTML pages.
import * as esbuild from "esbuild";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";

const __dirname = dirname(fileURLToPath(import.meta.url));
const root = resolve(__dirname, "..");

await esbuild.build({
  entryPoints: [resolve(root, "src/background/service-worker.ts")],
  outfile: resolve(root, "dist/background/service-worker.js"),
  bundle: true,
  format: "esm",
  target: "chrome116",
  platform: "browser",
  minify: false,
  sourcemap: true,
});

await esbuild.build({
  entryPoints: [resolve(root, "src/content/content-script.ts")],
  outfile: resolve(root, "dist/content/content-script.js"),
  bundle: true,
  format: "iife",
  target: "chrome116",
  platform: "browser",
  minify: false,
  sourcemap: true,
});

console.log("[build-background] service worker + content script bundled");
