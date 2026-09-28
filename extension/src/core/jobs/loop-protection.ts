import type { Job } from "@/core/jobs/job.model";
import { MAX_CONTINUATIONS, MAX_EXECUTION_TIME_MS } from "@/core/jobs/job.model";
import { sha256Hex } from "@/utils/hash";
import { summarizeForFingerprint } from "@/core/prompt-engine/prompt-composer";
import type { Checkpoint } from "@/core/checkpoint/checkpoint.model";

/**
 * Guards against infinite continuation loops, duplicate submissions, and
 * repeated uploads. This is intentionally independent of the state machine
 * so it applies no matter which state transition led here.
 */
export async function computeSubmissionFingerprint(job: Job, checkpoint?: Checkpoint): Promise<string> {
  return sha256Hex(summarizeForFingerprint(job, checkpoint));
}

export function isDuplicateSubmission(job: Job, fingerprint: string): boolean {
  return Boolean(job.lastSubmittedHash) && job.lastSubmittedHash === fingerprint;
}

export function hasExceededContinuationLimit(job: Job, limit = MAX_CONTINUATIONS): boolean {
  return job.progress.continuationCount >= limit;
}

export function hasExceededExecutionTime(job: Job, maxMs = MAX_EXECUTION_TIME_MS): boolean {
  return Date.now() - new Date(job.createdAt).getTime() >= maxMs;
}

export interface LoopGuardResult {
  allowed: boolean;
  reason?: string;
}

export function checkLoopGuards(job: Job): LoopGuardResult {
  if (hasExceededContinuationLimit(job)) {
    return { allowed: false, reason: `Reached the maximum of ${MAX_CONTINUATIONS} continuations for this job.` };
  }
  if (hasExceededExecutionTime(job)) {
    return { allowed: false, reason: "Reached the maximum total execution time for this job." };
  }
  return { allowed: true };
}
