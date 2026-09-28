import { DomProviderAdapterBase, type ProviderDomConfig } from "@/providers/interface/dom-provider-base";

/**
 * EXPERIMENTAL / BEST-EFFORT. Claude's web UI can change its markup at any
 * time; these selectors are not guaranteed to stay accurate. When they
 * stop matching, `verifyConversation`/`attachFile`/etc. fail closed (the
 * job moves to REQUIRES_USER_ACTION) rather than silently doing nothing or
 * clicking the wrong element. See docs/provider-adapters.md.
 */
const CLAUDE_CONFIG: ProviderDomConfig = {
  id: "claude",
  displayName: "Claude (claude.ai)",
  domains: ["claude.ai"],
  composeSelector: 'div[contenteditable="true"][aria-label*="prompt" i], div[contenteditable="true"]',
  sendButtonSelector: 'button[aria-label*="send" i]',
  fileInputSelector: 'input[type="file"]',
  generatingIndicatorSelector: 'button[aria-label*="stop" i]',
  latestResponseSelector: '[data-testid="conversation-turn"]:last-of-type, main',
  limitTextPatterns: ["usage limit", "you.ve reached", "come back", "message limit"],
  authTextPatterns: ["log in to continue", "sign in to claude", "session expired"],
  errorTextPatterns: ["something went wrong", "an error occurred"],
};

export class ClaudeAdapter extends DomProviderAdapterBase {
  constructor() {
    super(CLAUDE_CONFIG);
  }
}
