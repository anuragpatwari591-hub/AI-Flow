import { DomProviderAdapterBase, type ProviderDomConfig } from "@/providers/interface/dom-provider-base";

/**
 * EXPERIMENTAL / BEST-EFFORT, same caveats as the Claude adapter: ChatGPT's
 * markup changes frequently and these selectors will need periodic
 * maintenance. Failures fail closed into REQUIRES_USER_ACTION.
 */
const CHATGPT_CONFIG: ProviderDomConfig = {
  id: "chatgpt",
  displayName: "ChatGPT (chatgpt.com)",
  domains: ["chatgpt.com", "chat.openai.com"],
  composeSelector: '#prompt-textarea, div[contenteditable="true"]',
  sendButtonSelector: 'button[data-testid="send-button"]',
  fileInputSelector: 'input[type="file"]',
  generatingIndicatorSelector: 'button[data-testid="stop-button"]',
  latestResponseSelector: '[data-message-author-role="assistant"]:last-of-type',
  limitTextPatterns: ["you.ve reached", "usage cap", "try again later", "rate limit"],
  authTextPatterns: ["log in", "sign in to continue", "session has expired"],
  errorTextPatterns: ["something went wrong", "an error occurred"],
};

export class ChatGptAdapter extends DomProviderAdapterBase {
  constructor() {
    super(CHATGPT_CONFIG);
  }
}
