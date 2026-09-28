import "fake-indexeddb/auto";
import { webcrypto } from "node:crypto";

// jsdom's environment doesn't always provide a full Web Crypto (subtle)
// implementation; fall back to Node's when it's missing.
if (!globalThis.crypto || !("subtle" in globalThis.crypto)) {
  Object.defineProperty(globalThis, "crypto", { value: webcrypto });
}
