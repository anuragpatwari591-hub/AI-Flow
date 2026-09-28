import { copyFileSync, mkdirSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";

const __dirname = dirname(fileURLToPath(import.meta.url));
const root = resolve(__dirname, "..");

mkdirSync(resolve(root, "dist"), { recursive: true });
copyFileSync(resolve(root, "manifest.json"), resolve(root, "dist/manifest.json"));

console.log("[copy-manifest] manifest.json -> dist/manifest.json");
