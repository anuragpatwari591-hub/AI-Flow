import {
  AvailabilityState,
  ConversationState,
  type AIProviderAdapter,
  type AttachFileResult,
  type AvailabilityResult,
  type ConversationMetadata,
  type FileToAttach,
  type ReadConversationStateResult,
  type SubmitResult,
  type VerifyConversationResult,
} from "@/providers/interface/types";
import type { ContentScriptRequest, ContentScriptResponse } from "@/core/messaging/content-protocol";
import { isUrlOnDomain } from "@/security/sanitize";

/**
 * Provider-specific selectors and text heuristics. Kept isolated per
 * adapter so a UI change on one provider's site never touches another
 * provider or the core engines. These are necessarily best-effort: web
 * UIs change without notice, so every DOM interaction here is guarded and
 * failures surface as REQUIRES_USER_ACTION rather than being retried
 * blindly or silently mis-clicking something else.
 */
export interface ProviderDomConfig {
  id: string;
  displayName: string;
  domains: string[];
  composeSelector: string;
  sendButtonSelector: string;
  fileInputSelector: string;
  generatingIndicatorSelector: string;
  latestResponseSelector: string;
  limitTextPatterns: string[];
  authTextPatterns: string[];
  errorTextPatterns: string[];
}

async function ensureContentScriptInjected(tabId: number): Promise<void> {
  try {
    await chrome.tabs.sendMessage(tabId, { action: "GET_METADATA" } satisfies ContentScriptRequest);
  } catch {
    await chrome.scripting.executeScript({ target: { tabId }, files: ["content/content-script.js"] });
  }
}

async function sendToTab(tabId: number, request: ContentScriptRequest): Promise<ContentScriptResponse> {
  await ensureContentScriptInjected(tabId);
  return chrome.tabs.sendMessage(tabId, request);
}

export abstract class DomProviderAdapterBase implements AIProviderAdapter {
  readonly id: string;
  readonly displayName: string;
  readonly domains: string[];

  constructor(protected readonly config: ProviderDomConfig) {
    this.id = config.id;
    this.displayName = config.displayName;
    this.domains = config.domains;
  }

  async getAvailability(): Promise<AvailabilityResult> {
    // Availability is checked in context of a specific job's conversation
    // tab via detectLimitState/detectAuthenticationRequired, since these
    // providers don't expose a documented status API. A generic
    // "is the site reachable" probe is intentionally NOT implemented here
    // to avoid polling the provider outside of a real job's own tab.
    return { state: AvailabilityState.UNKNOWN, message: "Availability is checked per-conversation once a job opens its tab." };
  }

  async openConversation(conversationUrl: string): Promise<{ tabId: number }> {
    if (!isUrlOnDomain(conversationUrl, this.domains)) {
      throw new Error(`Refusing to open a conversation URL outside ${this.displayName}'s domain: ${conversationUrl}`);
    }
    const tab = await chrome.tabs.create({ url: conversationUrl, active: false });
    if (!tab.id) throw new Error("Failed to open a tab for the conversation.");
    return { tabId: tab.id };
  }

  async verifyConversation(tabId: number, expected: ConversationMetadata): Promise<VerifyConversationResult> {
    const tab = await chrome.tabs.get(tabId);
    if (!tab.url || !isUrlOnDomain(tab.url, this.domains)) {
      return { verified: false, reason: "Open tab is not on the expected provider domain." };
    }
    if (expected.url && stripQueryAndHash(tab.url) !== stripQueryAndHash(expected.url)) {
      return { verified: false, reason: "Open tab URL does not match the job's conversation URL." };
    }
    const metadata = await this.getConversationMetadata(tabId);
    return { verified: true, reason: "Conversation URL matches the job.", metadata };
  }

  async attachFile(tabId: number, file: FileToAttach): Promise<AttachFileResult> {
    const response = await sendToTab(tabId, {
      action: "ATTACH_FILE",
      selector: this.config.fileInputSelector,
      file,
    });
    return response.ok ? { success: true } : { success: false, reason: response.error };
  }

  async verifyAttachment(tabId: number, file: FileToAttach): Promise<AttachFileResult> {
    // Best-effort: confirm the compose area now references the filename.
    // Providers rarely expose a stable "upload succeeded" selector, so a
    // false negative here fails the job into REQUIRES_USER_ACTION rather
    // than guessing that the attachment went through.
    const response = await sendToTab(tabId, { action: "SCAN_PATTERNS", patterns: [escapeRegex(file.name)] });
    if (!response.ok) return { success: false, reason: response.error };
    return response.data ? { success: true } : { success: false, reason: `Could not confirm "${file.name}" was attached.` };
  }

  async composeMessage(tabId: number, text: string): Promise<{ success: boolean; reason?: string }> {
    const response = await sendToTab(tabId, { action: "INSERT_TEXT", selector: this.config.composeSelector, text });
    return response.ok ? { success: true } : { success: false, reason: response.error };
  }

  async submitMessage(tabId: number): Promise<SubmitResult> {
    const response = await sendToTab(tabId, { action: "CLICK", selector: this.config.sendButtonSelector });
    return response.ok ? { success: true } : { success: false, reason: response.error };
  }

  async readConversationState(tabId: number): Promise<ReadConversationStateResult> {
    const errors = await this.detectErrors(tabId);
    if (errors.length > 0) return { state: ConversationState.ERROR, latestMessageText: errors.join("; ") };

    const generating = await sendToTab(tabId, { action: "ELEMENT_EXISTS", selector: this.config.generatingIndicatorSelector });
    if (generating.ok && generating.data) return { state: ConversationState.GENERATING };

    const latest = await sendToTab(tabId, { action: "READ_TEXT", selector: this.config.latestResponseSelector });
    if (!latest.ok) return { state: ConversationState.ERROR, latestMessageText: latest.error };
    return { state: ConversationState.DONE, latestMessageText: latest.data as string };
  }

  async detectLimitState(tabId: number): Promise<boolean> {
    const response = await sendToTab(tabId, { action: "SCAN_PATTERNS", patterns: this.config.limitTextPatterns });
    return Boolean(response.ok && response.data);
  }

  async detectAuthenticationRequired(tabId: number): Promise<boolean> {
    const response = await sendToTab(tabId, { action: "SCAN_PATTERNS", patterns: this.config.authTextPatterns });
    return Boolean(response.ok && response.data);
  }

  async detectErrors(tabId: number): Promise<string[]> {
    const response = await sendToTab(tabId, { action: "SCAN_PATTERNS", patterns: this.config.errorTextPatterns });
    return response.ok && response.data ? ["Provider page shows an error state."] : [];
  }

  async getConversationMetadata(tabId: number): Promise<ConversationMetadata> {
    const response = await sendToTab(tabId, { action: "GET_METADATA" });
    if (!response.ok) throw new Error(response.error);
    const data = response.data as { url: string; title: string };
    return { url: data.url, title: data.title };
  }
}

function escapeRegex(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

function stripQueryAndHash(url: string): string {
  return url.split("#", 1)[0]?.split("?", 1)[0] ?? url;
}
