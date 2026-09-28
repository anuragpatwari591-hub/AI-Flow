/**
 * SHA-256 hex digest using the Web Crypto API. Used for attachment
 * duplicate/corruption detection and for message fingerprints in the loop
 * protection system (never for anything security-sensitive like passwords).
 */
export async function sha256Hex(data: ArrayBuffer | string): Promise<string> {
  const buffer = typeof data === "string" ? new TextEncoder().encode(data) : data;
  const digest = await crypto.subtle.digest("SHA-256", buffer);
  return Array.from(new Uint8Array(digest))
    .map((b) => b.toString(16).padStart(2, "0"))
    .join("");
}
