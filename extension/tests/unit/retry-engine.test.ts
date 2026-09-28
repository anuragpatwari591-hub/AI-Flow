import { describe, expect, it } from "vitest";
import { computeBackoffDelayMs, decideRetry, classifyErrorCode, ErrorCategory } from "@/core/retry/retry-engine";

describe("retry engine", () => {
  it("follows the documented backoff schedule for the first five attempts", () => {
    expect(computeBackoffDelayMs(1, { jitterFraction: 0 })).toBe(30_000);
    expect(computeBackoffDelayMs(2, { jitterFraction: 0 })).toBe(120_000);
    expect(computeBackoffDelayMs(3, { jitterFraction: 0 })).toBe(300_000);
    expect(computeBackoffDelayMs(4, { jitterFraction: 0 })).toBe(900_000);
    expect(computeBackoffDelayMs(5, { jitterFraction: 0 })).toBe(1_800_000);
  });

  it("keeps growing (capped) beyond the fifth attempt instead of looping forever at a fixed interval", () => {
    const sixth = computeBackoffDelayMs(6, { jitterFraction: 0 });
    const seventh = computeBackoffDelayMs(7, { jitterFraction: 0 });
    expect(sixth).toBeGreaterThan(1_800_000);
    expect(seventh).toBeGreaterThanOrEqual(sixth);
    expect(seventh).toBeLessThanOrEqual(2 * 60 * 60 * 1000);
  });

  it("classifies error codes into sensible categories", () => {
    expect(classifyErrorCode("NETWORK_TIMEOUT")).toBe(ErrorCategory.TRANSIENT_NETWORK);
    expect(classifyErrorCode("RATE_LIMIT")).toBe(ErrorCategory.PROVIDER_LIMIT);
    expect(classifyErrorCode("AUTH_REQUIRED")).toBe(ErrorCategory.AUTH_REQUIRED);
    expect(classifyErrorCode("CONVERSATION_MISMATCH")).toBe(ErrorCategory.VERIFICATION_FAILED);
    expect(classifyErrorCode("UNSUPPORTED_ACTION")).toBe(ErrorCategory.UNSUPPORTED_OPERATION);
    expect(classifyErrorCode("MALFORMED_JOB")).toBe(ErrorCategory.MALFORMED_JOB);
    expect(classifyErrorCode("SOMETHING_ELSE")).toBe(ErrorCategory.UNKNOWN);
  });

  it("never retries authentication failures", () => {
    const decision = decideRetry(ErrorCategory.AUTH_REQUIRED, 1);
    expect(decision.outcome).toBe("REQUIRES_USER_ACTION");
  });

  it("never retries malformed jobs or unsupported operations, and fails outright", () => {
    expect(decideRetry(ErrorCategory.MALFORMED_JOB, 1).outcome).toBe("FAIL");
    expect(decideRetry(ErrorCategory.UNSUPPORTED_OPERATION, 1).outcome).toBe("FAIL");
  });

  it("bounds unknown errors to a small retry budget instead of retrying forever", () => {
    const policy = decideRetry(ErrorCategory.UNKNOWN, 1);
    expect(policy.outcome).toBe("RETRY");
    const exhausted = decideRetry(ErrorCategory.UNKNOWN, 3);
    expect(exhausted.outcome).toBe("REQUIRES_USER_ACTION");
  });

  it("gives provider limits a much larger retry budget than unknown errors", () => {
    expect(decideRetry(ErrorCategory.PROVIDER_LIMIT, 5).outcome).toBe("RETRY");
  });

  it("respects a per-job maxAttempts override", () => {
    const decision = decideRetry(ErrorCategory.TRANSIENT_NETWORK, 2, 2);
    expect(decision.outcome).toBe("REQUIRES_USER_ACTION");
  });
});
