import { DomProviderAdapterBase, type ProviderDomConfig } from "@/providers/interface/dom-provider-base";

/**
 * EXPERIMENTAL / BEST-EFFORT, same caveats as the other DOM adapters.
 * Gemini's compose UI is a rich-text contenteditable region rather than a
 * plain textarea, which this config accounts for.
 */
const GEMINI_CONFIG: ProviderDomConfig = {
  id: "gemini",
  displayName: "Gemini (gemini.google.com)",
  domains: ["gemini.google.com"],
  composeSelector: 'div[contenteditable="true"][role="textbox"]',
  sendButtonSelector: 'button[aria-label*="send" i]',
  fileInputSelector: 'input[type="file"]',
  generatingIndicatorSelector: 'button[aria-label*="stop" i]',
  latestResponseSelector: 'message-content:last-of-type, [data-response-index]:last-of-type',
  limitTextPatterns: ["reached your limit", "try again later", "quota"],
  authTextPatterns: ["sign in", "you.re signed out"],
  errorTextPatterns: ["something went wrong", "an error occurred"],
};

export class GeminiAdapter extends DomProviderAdapterBase {
  constructor() {
    super(GEMINI_CONFIG);
  }
}
