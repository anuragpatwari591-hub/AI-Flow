import { describe, expect, it } from "vitest";
import { MockAIProvider } from "@/providers/mock/mock-provider";
import { AvailabilityState, ConversationState } from "@/providers/interface/types";

describe("MockAIProvider", () => {
  it("reports AVAILABLE by default and lets a job proceed end-to-end", async () => {
    const provider = new MockAIProvider();
    const availability = await provider.getAvailability();
    expect(availability.state).toBe(AvailabilityState.AVAILABLE);

    const { tabId } = await provider.openConversation("https://mock.aiflow.local/c/1");
    const verify = await provider.verifyConversation(tabId, { url: "https://mock.aiflow.local/c/1" });
    expect(verify.verified).toBe(true);

    const compose = await provider.composeMessage(tabId, "hello");
    expect(compose.success).toBe(true);
    const submit = await provider.submitMessage(tabId);
    expect(submit.success).toBe(true);

    const state = await provider.readConversationState(tabId);
    expect(state.state).toBe(ConversationState.DONE);
    expect(state.latestMessageText).toContain("hello");
  });

  it("simulates a usage limit", async () => {
    const provider = new MockAIProvider();
    provider.setScenario("LIMITED");
    const availability = await provider.getAvailability();
    expect(availability.state).toBe(AvailabilityState.LIMITED);
    expect(availability.retryAfterMs).toBeUndefined();
  });

  it("simulates a known retry time when the provider scenario provides one", async () => {
    const provider = new MockAIProvider();
    provider.setScenario("LIMITED_WITH_KNOWN_RETRY", { retryAfterMs: 45_000 });
    const availability = await provider.getAvailability();
    expect(availability.retryAfterMs).toBe(45_000);
  });

  it("simulates authentication required", async () => {
    const provider = new MockAIProvider();
    provider.setScenario("AUTH_REQUIRED");
    expect((await provider.getAvailability()).state).toBe(AvailabilityState.AUTH_REQUIRED);
    const { tabId } = await provider.openConversation("https://mock.aiflow.local/c/1");
    expect(await provider.detectAuthenticationRequired(tabId)).toBe(true);
  });

  it("simulates an upload failure", async () => {
    const provider = new MockAIProvider();
    provider.setScenario("UPLOAD_FAILURE");
    const { tabId } = await provider.openConversation("https://mock.aiflow.local/c/1");
    const result = await provider.attachFile(tabId, { name: "a.txt", type: "text/plain", data: new ArrayBuffer(1) });
    expect(result.success).toBe(false);
  });

  it("simulates a network failure while submitting", async () => {
    const provider = new MockAIProvider();
    provider.setScenario("NETWORK_FAILURE");
    const { tabId } = await provider.openConversation("https://mock.aiflow.local/c/1");
    const submit = await provider.submitMessage(tabId);
    expect(submit.success).toBe(false);
  });

  it("simulates a long-running response that stays GENERATING for several polls", async () => {
    const provider = new MockAIProvider();
    provider.setScenario("LONG_RUNNING", { longRunningSteps: 2 });
    const { tabId } = await provider.openConversation("https://mock.aiflow.local/c/1");
    await provider.composeMessage(tabId, "long task");
    await provider.submitMessage(tabId);
    expect((await provider.readConversationState(tabId)).state).toBe(ConversationState.GENERATING);
    expect((await provider.readConversationState(tabId)).state).toBe(ConversationState.GENERATING);
    expect((await provider.readConversationState(tabId)).state).toBe(ConversationState.DONE);
  });

  it("simulates a conversation mismatch", async () => {
    const provider = new MockAIProvider();
    provider.setScenario("CONVERSATION_MISMATCH");
    const { tabId } = await provider.openConversation("https://mock.aiflow.local/c/1");
    const verify = await provider.verifyConversation(tabId, { url: "https://mock.aiflow.local/c/1" });
    expect(verify.verified).toBe(false);
  });

  it("simulates a provider-side error surfacing through detectErrors and readConversationState", async () => {
    const provider = new MockAIProvider();
    provider.setScenario("PROVIDER_ERROR");
    const { tabId } = await provider.openConversation("https://mock.aiflow.local/c/1");
    expect(await provider.detectErrors(tabId)).toHaveLength(1);
    expect((await provider.readConversationState(tabId)).state).toBe(ConversationState.ERROR);
  });
});
