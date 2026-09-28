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

export type MockScenario =
  | "AVAILABLE"
  | "LIMITED"
  | "LIMITED_WITH_KNOWN_RETRY"
  | "AUTH_REQUIRED"
  | "UPLOAD_FAILURE"
  | "NETWORK_FAILURE"
  | "LONG_RUNNING"
  | "CONVERSATION_MISMATCH"
  | "PROVIDER_ERROR";

interface MockTabState {
  url: string;
  id?: string;
  title: string;
  lastComposedText?: string;
  generatingStepsRemaining: number;
}

/**
 * A fully simulated provider used for development, demos, and the test
 * suite. It never touches the network or a real browser tab, so the whole
 * job lifecycle (availability waiting, retries, checkpoints, continuation,
 * loop protection) can be exercised deterministically without depending on
 * a real AI service being reachable or in a particular state.
 */
export class MockAIProvider implements AIProviderAdapter {
  readonly id = "mock";
  readonly displayName = "Mock Provider (simulation)";
  readonly domains = ["mock.aiflow.local"];

  private scenario: MockScenario = "AVAILABLE";
  private knownRetryAfterMs = 60_000;
  private longRunningSteps = 2;
  private tabs = new Map<number, MockTabState>();
  private nextTabId = 1;

  setScenario(scenario: MockScenario, options: { retryAfterMs?: number; longRunningSteps?: number } = {}): void {
    this.scenario = scenario;
    if (options.retryAfterMs !== undefined) this.knownRetryAfterMs = options.retryAfterMs;
    if (options.longRunningSteps !== undefined) this.longRunningSteps = options.longRunningSteps;
  }

  async getAvailability(): Promise<AvailabilityResult> {
    switch (this.scenario) {
      case "AUTH_REQUIRED":
        return { state: AvailabilityState.AUTH_REQUIRED, message: "Sign-in required." };
      case "LIMITED":
        return { state: AvailabilityState.LIMITED, message: "Usage limit reached." };
      case "LIMITED_WITH_KNOWN_RETRY":
        return {
          state: AvailabilityState.LIMITED,
          retryAfterMs: this.knownRetryAfterMs,
          message: "Usage limit reached; provider reported a retry time.",
        };
      case "NETWORK_FAILURE":
        return { state: AvailabilityState.NETWORK_ERROR, message: "Could not reach the provider." };
      case "PROVIDER_ERROR":
        return { state: AvailabilityState.PROVIDER_ERROR, message: "Provider returned an unexpected error." };
      default:
        return { state: AvailabilityState.AVAILABLE, message: "Provider is available." };
    }
  }

  async openConversation(conversationUrl: string): Promise<{ tabId: number }> {
    const tabId = this.nextTabId++;
    const id = conversationUrl.split("/").filter(Boolean).pop();
    this.tabs.set(tabId, {
      url: conversationUrl,
      id,
      title: "Mock Conversation",
      generatingStepsRemaining: 0,
    });
    return { tabId };
  }

  async verifyConversation(tabId: number, expected: ConversationMetadata): Promise<VerifyConversationResult> {
    const tab = this.requireTab(tabId);
    if (this.scenario === "CONVERSATION_MISMATCH") {
      return { verified: false, reason: "Simulated conversation mismatch: open conversation does not match the job." };
    }
    const urlMatches = tab.url === expected.url;
    const idMatches = !expected.id || tab.id === expected.id;
    if (!urlMatches || !idMatches) {
      return { verified: false, reason: "Conversation URL/id does not match the expected job conversation." };
    }
    return { verified: true, reason: "Conversation matches.", metadata: { id: tab.id, title: tab.title, url: tab.url } };
  }

  async attachFile(tabId: number, _file: FileToAttach): Promise<AttachFileResult> {
    this.requireTab(tabId);
    if (this.scenario === "UPLOAD_FAILURE") return { success: false, reason: "Simulated upload failure." };
    return { success: true };
  }

  async verifyAttachment(tabId: number, _file: FileToAttach): Promise<AttachFileResult> {
    this.requireTab(tabId);
    if (this.scenario === "UPLOAD_FAILURE") return { success: false, reason: "Simulated attachment verification failure." };
    return { success: true };
  }

  async composeMessage(tabId: number, text: string): Promise<{ success: boolean; reason?: string }> {
    const tab = this.requireTab(tabId);
    if (this.scenario === "NETWORK_FAILURE") return { success: false, reason: "Simulated network failure while composing." };
    tab.lastComposedText = text;
    return { success: true };
  }

  async submitMessage(tabId: number): Promise<SubmitResult> {
    const tab = this.requireTab(tabId);
    if (this.scenario === "NETWORK_FAILURE") return { success: false, reason: "Simulated network failure while submitting." };
    tab.generatingStepsRemaining = this.scenario === "LONG_RUNNING" ? this.longRunningSteps : 0;
    return { success: true };
  }

  async readConversationState(tabId: number): Promise<ReadConversationStateResult> {
    const tab = this.requireTab(tabId);
    if (this.scenario === "PROVIDER_ERROR") {
      return { state: ConversationState.ERROR, latestMessageText: "Simulated provider error." };
    }
    if (tab.generatingStepsRemaining > 0) {
      tab.generatingStepsRemaining -= 1;
      return { state: ConversationState.GENERATING };
    }
    return {
      state: ConversationState.DONE,
      latestMessageText: `Mock response acknowledging: ${(tab.lastComposedText ?? "").slice(0, 80)}`,
    };
  }

  async detectLimitState(_tabId: number): Promise<boolean> {
    return this.scenario === "LIMITED" || this.scenario === "LIMITED_WITH_KNOWN_RETRY";
  }

  async detectAuthenticationRequired(_tabId: number): Promise<boolean> {
    return this.scenario === "AUTH_REQUIRED";
  }

  async detectErrors(_tabId: number): Promise<string[]> {
    return this.scenario === "PROVIDER_ERROR" ? ["Simulated provider error."] : [];
  }

  async getConversationMetadata(tabId: number): Promise<ConversationMetadata> {
    const tab = this.requireTab(tabId);
    return { id: tab.id, title: tab.title, url: tab.url };
  }

  private requireTab(tabId: number): MockTabState {
    const tab = this.tabs.get(tabId);
    if (!tab) throw new Error(`MockAIProvider: unknown tabId ${tabId}`);
    return tab;
  }
}
