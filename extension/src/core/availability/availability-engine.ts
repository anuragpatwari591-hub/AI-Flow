import { AvailabilityState, type AvailabilityResult } from "@/providers/interface/types";
import { computeBackoffDelayMs } from "@/core/retry/retry-engine";

export type AvailabilityAction =
  | { action: "PROCEED"; reason: string }
  | { action: "WAIT"; waitMs: number; reason: string; trustworthy: boolean }
  | { action: "REQUIRES_USER_ACTION"; reason: string };

const MAX_UNKNOWN_OR_ERROR_ATTEMPTS = 8;

/**
 * Turns a raw AvailabilityResult into a scheduling decision. This is the
 * only place that is allowed to decide "wait and check again later" — it
 * never assumes a fixed reset window and never spams the provider: repeated
 * LIMITED/UNKNOWN results widen the wait via exponential backoff instead of
 * polling at a constant rate.
 */
export function decideAvailabilityAction(result: AvailabilityResult, attemptNumber: number): AvailabilityAction {
  switch (result.state) {
    case AvailabilityState.AVAILABLE:
      return { action: "PROCEED", reason: result.message || "Provider is available." };

    case AvailabilityState.AUTH_REQUIRED:
      return {
        action: "REQUIRES_USER_ACTION",
        reason: result.message || "Provider requires the user to sign in again.",
      };

    case AvailabilityState.LIMITED: {
      if (result.retryAfterMs && result.retryAfterMs > 0) {
        return {
          action: "WAIT",
          waitMs: result.retryAfterMs,
          reason: result.message || "Provider usage limit reached; provider reported a retry time.",
          trustworthy: true,
        };
      }
      return {
        action: "WAIT",
        waitMs: computeBackoffDelayMs(attemptNumber),
        reason: result.message || "Provider usage limit reached. Availability unknown — checking again later.",
        trustworthy: false,
      };
    }

    case AvailabilityState.NETWORK_ERROR:
    case AvailabilityState.PROVIDER_ERROR:
    case AvailabilityState.UNKNOWN:
    default: {
      if (attemptNumber >= MAX_UNKNOWN_OR_ERROR_ATTEMPTS) {
        return {
          action: "REQUIRES_USER_ACTION",
          reason: `Provider availability has been ${result.state} for ${attemptNumber} consecutive checks.`,
        };
      }
      return {
        action: "WAIT",
        waitMs: computeBackoffDelayMs(attemptNumber),
        reason: result.message || `Availability ${result.state.toLowerCase()} — checking again later.`,
        trustworthy: false,
      };
    }
  }
}
