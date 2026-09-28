import { describe, expect, it } from "vitest";
import { createJob } from "@/core/jobs/job.model";
import { computeSubmissionFingerprint, isDuplicateSubmission, hasExceededContinuationLimit, checkLoopGuards } from "@/core/jobs/loop-protection";

describe("loop protection", () => {
  it("computes a stable fingerprint for the same job+checkpoint pair", async () => {
    const job = createJob({ title: "T", provider: "mock", conversationUrl: "u", instructions: "i" });
    const a = await computeSubmissionFingerprint(job);
    const b = await computeSubmissionFingerprint(job);
    expect(a).toBe(b);
  });

  it("flags a resubmission with the same fingerprint as a duplicate", async () => {
    const job = createJob({ title: "T", provider: "mock", conversationUrl: "u", instructions: "i" });
    const fingerprint = await computeSubmissionFingerprint(job);
    expect(isDuplicateSubmission({ ...job, lastSubmittedHash: fingerprint }, fingerprint)).toBe(true);
    expect(isDuplicateSubmission(job, fingerprint)).toBe(false);
  });

  it("flags jobs that exceeded the continuation limit", () => {
    const job = createJob({ title: "T", provider: "mock", conversationUrl: "u", instructions: "i" });
    expect(hasExceededContinuationLimit({ ...job, progress: { ...job.progress, continuationCount: 25 } }, 25)).toBe(true);
    expect(hasExceededContinuationLimit(job, 25)).toBe(false);
  });

  it("checkLoopGuards blocks a job once its continuation limit is hit", () => {
    const job = createJob({ title: "T", provider: "mock", conversationUrl: "u", instructions: "i" });
    const overLimit = { ...job, progress: { ...job.progress, continuationCount: 999 } };
    const guard = checkLoopGuards(overLimit);
    expect(guard.allowed).toBe(false);
  });
});
