/**
 * Availability states a provider adapter can report. `LIMITED` must never
 * be paired with a fabricated reset time — only `retryAfterMs` values the
 * adapter actually observed (e.g. a countdown shown in the UI) should be
 * set; otherwise leave it undefined and let the availability engine fall
 * back to exponential backoff with a clearly "unknown" status message.
 */
export const AvailabilityState = {
  AVAILABLE: "AVAILABLE",
  LIMITED: "LIMITED",
  AUTH_REQUIRED: "AUTH_REQUIRED",
  NETWORK_ERROR: "NETWORK_ERROR",
  UNKNOWN: "UNKNOWN",
  PROVIDER_ERROR: "PROVIDER_ERROR",
} as const;
export type AvailabilityState = (typeof AvailabilityState)[keyof typeof AvailabilityState];

export interface AvailabilityResult {
  state: AvailabilityState;
  /** Only set when the provider surfaced a real, observed retry time. */
  retryAfterMs?: number;
  message: string;
}

export interface ConversationMetadata {
  id?: string;
  title?: string;
  url: string;
}

export interface VerifyConversationResult {
  verified: boolean;
  reason: string;
  metadata?: ConversationMetadata;
}

export interface AttachFileResult {
  success: boolean;
  reason?: string;
}

export interface SubmitResult {
  success: boolean;
  reason?: string;
}

export const ConversationState = {
  IDLE: "IDLE",
  GENERATING: "GENERATING",
  DONE: "DONE",
  ERROR: "ERROR",
} as const;
export type ConversationState = (typeof ConversationState)[keyof typeof ConversationState];

export interface ReadConversationStateResult {
  state: ConversationState;
  latestMessageText?: string;
}

export interface FileToAttach {
  name: string;
  type: string;
  data: ArrayBuffer;
}

/**
 * The contract every AI provider integration implements. Core job-execution
 * logic depends only on this interface, never on provider-specific
 * selectors or endpoints, so adapters can be swapped or extended without
 * touching the scheduler, retry engine, or state machine.
 *
 * Every method must:
 *  - use only visible page state and standard UI interactions (or an
 *    official documented API, if one exists)
 *  - never attempt to bypass authentication, CAPTCHAs, or rate limits
 *  - fail closed: when something cannot be verified, return a result that
 *    says so rather than guessing
 */
export interface AIProviderAdapter {
  readonly id: string;
  readonly displayName: string;
  readonly domains: string[];

  getAvailability(): Promise<AvailabilityResult>;
  openConversation(conversationUrl: string): Promise<{ tabId: number }>;
  verifyConversation(tabId: number, expected: ConversationMetadata): Promise<VerifyConversationResult>;
  attachFile(tabId: number, file: FileToAttach): Promise<AttachFileResult>;
  verifyAttachment(tabId: number, file: FileToAttach): Promise<AttachFileResult>;
  composeMessage(tabId: number, text: string): Promise<{ success: boolean; reason?: string }>;
  submitMessage(tabId: number): Promise<SubmitResult>;
  readConversationState(tabId: number): Promise<ReadConversationStateResult>;
  detectLimitState(tabId: number): Promise<boolean>;
  detectAuthenticationRequired(tabId: number): Promise<boolean>;
  detectErrors(tabId: number): Promise<string[]>;
  getConversationMetadata(tabId: number): Promise<ConversationMetadata>;
}
