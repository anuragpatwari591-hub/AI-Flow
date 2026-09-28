/** Strips control characters and clamps length for any free-text user input before it's stored or sent to a provider page. */
export function sanitizeText(input: string, maxLength = 50_000): string {
  // eslint-disable-next-line no-control-regex -- intentionally stripping ASCII control characters (keeps \t \n \r).
  const withoutControlChars = input.replace(/[\u0000-\u0008\u000B\u000C\u000E-\u001F]/g, "");
  return withoutControlChars.slice(0, maxLength);
}

/** Escapes text before it is ever inserted into a provider page's DOM via innerHTML (we prefer textContent, but this exists for defense in depth). */
export function escapeHtml(input: string): string {
  return input
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

/** Validates that a conversation URL belongs to one of the provider's declared domains before any tab/content-script interaction. */
export function isUrlOnDomain(url: string, allowedDomains: string[]): boolean {
  try {
    const parsed = new URL(url);
    return allowedDomains.some((domain) => parsed.hostname === domain || parsed.hostname.endsWith(`.${domain}`));
  } catch {
    return false;
  }
}
