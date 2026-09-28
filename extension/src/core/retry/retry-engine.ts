/**
 * Retry engine: turns an error into a retry decision. Different failure
 * categories get different policies on purpose — authentication failures
 * and malformed jobs must never be retried blindly, and unknown errors get
 * a small, bounded retry budget rather than infinite attempts.
 */
export const ErrorCategory = {
  TRANSIENT_NETWORK: "TRANSIENT_NETWORK",
  PROVIDER_LIMIT: "PROVIDER_LIMIT",
  AUTH_REQUIRED: "AUTH_REQUIRED",
  VERIFICATION_FAILED: "VERIFICATION_FAILED",
  UNSUPPORTED_OPERATION: "UNSUPPORTED_OPERATION",
  MALFORMED_JOB: "MALFORMED_JOB",
  PROVIDER_ERROR: "PROVIDER_ERROR",
  UNKNOWN: "UNKNOWN",
} as const;
export type ErrorCategory = (typeof ErrorCategory)[keyof typeof ErrorCategory];

export type RetryOutcome = "RETRY" | "REQUIRES_USER_ACTION" | "FAIL";

interface CategoryPolicy {
  retryable: boolean;
  maxAttempts: number;
  /** What happens once the retry budget is exhausted (or immediately, if not retryable). */
  onExhausted: "REQUIRES_USER_ACTION" | "FAIL";
}

export const CATEGORY_POLICIES: Record<ErrorCategory, CategoryPolicy> = {
  [ErrorCategory.TRANSIENT_NETWORK]: { retryable: true, maxAttempts: 6, onExhausted: "REQUIRES_USER_ACTION" },
  [ErrorCategory.PROVIDER_LIMIT]: { retryable: true, maxAttempts: 12, onExhausted: "REQUIRES_USER_ACTION" },
  [ErrorCategory.PROVIDER_ERROR]: { retryable: true, maxAttempts: 4, onExhausted: "REQUIRES_USER_ACTION" },
  [ErrorCategory.UNKNOWN]: { retryable: true, maxAttempts: 3, onExhausted: "REQUIRES_USER_ACTION" },
  [ErrorCategory.AUTH_REQUIRED]: { retryable: false, maxAttempts: 0, onExhausted: "REQUIRES_USER_ACTION" },
  [ErrorCategory.VERIFICATION_FAILED]: { retryable: false, maxAttempts: 0, onExhausted: "REQUIRES_USER_ACTION" },
  [ErrorCategory.UNSUPPORTED_OPERATION]: { retryable: false, maxAttempts: 0, onExhausted: "FAIL" },
  [ErrorCategory.MALFORMED_JOB]: { retryable: false, maxAttempts: 0, onExhausted: "FAIL" },
};

// attempt 1 -> 30s, 2 -> 2m, 3 -> 5m, 4 -> 15m, 5 -> 30m, then doubles, capped.
const BASE_SCHEDULE_MS = [30_000, 120_000, 300_000, 900_000, 1_800_000];
const MAX_DELAY_MS = 2 * 60 * 60 * 1000; // 2 hours

export interface BackoffOptions {
  /** Deterministic jitter fraction in [0, 1); tests should pass 0. */
  jitterFraction?: number;
}

export function computeBackoffDelayMs(attempt: number, options: BackoffOptions = {}): number {
  const index = Math.max(0, attempt - 1);
  let delay: number;
  if (index < BASE_SCHEDULE_MS.length) {
    delay = BASE_SCHEDULE_MS[index]!;
  } else {
    const extra = index - BASE_SCHEDULE_MS.length + 1;
    delay = Math.min(BASE_SCHEDULE_MS[BASE_SCHEDULE_MS.length - 1]! * Math.pow(2, extra), MAX_DELAY_MS);
  }
  const jitterFraction = options.jitterFraction ?? 0.1;
  if (jitterFraction <= 0) return delay;
  const jitter = delay * jitterFraction * (Math.random() * 2 - 1);
  return Math.max(1000, Math.round(delay + jitter));
}

export interface RetryDecision {
  outcome: RetryOutcome;
  delayMs?: number;
  reason: string;
}

/**
 * Decides what to do next given an error category and how many attempts
 * have already been made for this job. `attemptNumber` is 1-based and
 * represents the attempt that just failed.
 */
export function decideRetry(category: ErrorCategory, attemptNumber: number, maxAttemptsOverride?: number): RetryDecision {
  const policy = CATEGORY_POLICIES[category];
  if (!policy.retryable) {
    return {
      outcome: policy.onExhausted,
      reason: `${category} is not retryable.`,
    };
  }
  const maxAttempts = maxAttemptsOverride ?? policy.maxAttempts;
  if (attemptNumber >= maxAttempts) {
    return {
      outcome: policy.onExhausted,
      reason: `Exhausted ${maxAttempts} retry attempts for ${category}.`,
    };
  }
  return {
    outcome: "RETRY",
    delayMs: computeBackoffDelayMs(attemptNumber),
    reason: `Retrying after attempt ${attemptNumber} (${category}).`,
  };
}

/** Best-effort mapping from a provider/system error code to a retry category. */
export function classifyErrorCode(code: string): ErrorCategory {
  const normalized = code.toUpperCase();
  // Internal call sites pass exact ErrorCategory names as codes; honor those directly.
  if ((Object.values(ErrorCategory) as string[]).includes(normalized)) return normalized as ErrorCategory;
  if (normalized.includes("NETWORK") || normalized.includes("TIMEOUT")) return ErrorCategory.TRANSIENT_NETWORK;
  if (normalized.includes("LIMIT") || normalized.includes("RATE")) return ErrorCategory.PROVIDER_LIMIT;
  if (normalized.includes("AUTH") || normalized.includes("LOGIN") || normalized.includes("SESSION")) {
    return ErrorCategory.AUTH_REQUIRED;
  }
  if (normalized.includes("VERIF") || normalized.includes("MISMATCH") || normalized.includes("CONVERSATION")) {
    return ErrorCategory.VERIFICATION_FAILED;
  }
  if (normalized.includes("UNSUPPORTED")) return ErrorCategory.UNSUPPORTED_OPERATION;
  if (normalized.includes("MALFORMED") || normalized.includes("INVALID_JOB")) return ErrorCategory.MALFORMED_JOB;
  if (normalized.includes("PROVIDER")) return ErrorCategory.PROVIDER_ERROR;
  return ErrorCategory.UNKNOWN;
}
