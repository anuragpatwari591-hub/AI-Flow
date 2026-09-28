import { describe, expect, it } from "vitest";
import { decideAvailabilityAction } from "@/core/availability/availability-engine";
import { AvailabilityState } from "@/providers/interface/types";

describe("availability engine", () => {
  it("proceeds immediately when the provider is available", () => {
    const decision = decideAvailabilityAction({ state: AvailabilityState.AVAILABLE, message: "ok" }, 1);
    expect(decision.action).toBe("PROCEED");
  });

  it("requires user action on AUTH_REQUIRED without ever retrying", () => {
    const decision = decideAvailabilityAction({ state: AvailabilityState.AUTH_REQUIRED, message: "sign in" }, 1);
    expect(decision.action).toBe("REQUIRES_USER_ACTION");
  });

  it("trusts a provider-reported retry time when present", () => {
    const decision = decideAvailabilityAction({ state: AvailabilityState.LIMITED, retryAfterMs: 3_600_000, message: "limited" }, 1);
    expect(decision.action).toBe("WAIT");
    if (decision.action === "WAIT") {
      expect(decision.waitMs).toBe(3_600_000);
      expect(decision.trustworthy).toBe(true);
    }
  });

  it("never fabricates a retry time when the provider didn't report one", () => {
    const decision = decideAvailabilityAction({ state: AvailabilityState.LIMITED, message: "limited" }, 1);
    expect(decision.action).toBe("WAIT");
    if (decision.action === "WAIT") {
      expect(decision.trustworthy).toBe(false);
      expect(decision.waitMs).toBeGreaterThan(0);
    }
  });

  it("widens the wait on repeated unknown/network states instead of polling at a fixed rate", () => {
    const first = decideAvailabilityAction({ state: AvailabilityState.NETWORK_ERROR, message: "down" }, 1);
    const later = decideAvailabilityAction({ state: AvailabilityState.NETWORK_ERROR, message: "down" }, 4);
    expect(first.action).toBe("WAIT");
    expect(later.action).toBe("WAIT");
    if (first.action === "WAIT" && later.action === "WAIT") {
      expect(later.waitMs).toBeGreaterThan(first.waitMs);
    }
  });

  it("eventually requires user action if availability stays unknown for too long", () => {
    const decision = decideAvailabilityAction({ state: AvailabilityState.UNKNOWN, message: "?" }, 50);
    expect(decision.action).toBe("REQUIRES_USER_ACTION");
  });
});
