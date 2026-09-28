import { describe, expect, it } from "vitest";
import { MemoryKvStore } from "@/core/storage/kv-store";
import { JobStore } from "@/core/storage/job-store";
import { CheckpointStore } from "@/core/checkpoint/checkpoint-store";
import { JobManager } from "@/core/jobs/job-manager";
import { JobRunner } from "@/core/jobs/job-runner";
import { Scheduler } from "@/core/scheduler/scheduler";
import { FakeAlarmsPort } from "@/core/scheduler/alarms-port";
import { AttachmentStore } from "@/core/storage/attachment-store";
import { ProviderRegistry } from "@/providers/provider-registry";
import { MockAIProvider } from "@/providers/mock/mock-provider";
import { JobStatus, ExecutionMode } from "@/core/jobs/job.model";
import type { JobRunnerEvent } from "@/core/jobs/job-runner";

function makeHarness() {
  const kv = new MemoryKvStore();
  const jobStore = new JobStore(kv);
  const checkpoints = new CheckpointStore(kv);
  const jobs = new JobManager(jobStore);
  const alarms = new FakeAlarmsPort();
  const scheduler = new Scheduler(alarms);
  const provider = new MockAIProvider();
  const providers = new ProviderRegistry();
  providers.register(provider);
  const attachments = new AttachmentStore();
  const events: JobRunnerEvent[] = [];
  const runner = new JobRunner(jobs, checkpoints, scheduler, providers, attachments, (e) => events.push(e));
  return { jobs, checkpoints, scheduler, alarms, provider, attachments, runner, events };
}

async function driveUntil(runner: JobRunner, jobs: JobManager, jobId: string, predicate: (status: string) => boolean, maxSteps = 30) {
  for (let i = 0; i < maxSteps; i++) {
    const job = await jobs.get(jobId);
    if (predicate(job.status)) return job;
    await runner.runStep(jobId);
  }
  return jobs.get(jobId);
}

describe("job lifecycle (MockAIProvider)", () => {
  it("runs a two-step autonomous job end to end and produces checkpoints along the way", async () => {
    const { jobs, checkpoints, runner, events } = makeHarness();
    const job = await jobs.create({
      title: "Two step job",
      provider: "mock",
      conversationUrl: "https://mock.aiflow.local/c/1",
      instructions: "Do two things.",
      executionMode: ExecutionMode.AUTONOMOUS,
      steps: ["Step one", "Step two"],
    });
    await jobs.queue(job.id);

    const finalJob = await driveUntil(runner, jobs, job.id, (s) => s === JobStatus.COMPLETED || s === JobStatus.FAILED || s === JobStatus.REQUIRES_USER_ACTION);

    expect(finalJob.status).toBe(JobStatus.COMPLETED);
    expect(finalJob.progress.remainingSteps).toEqual([]);
    expect(finalJob.progress.completedSteps).toEqual(["Step one", "Step two"]);

    const jobCheckpoints = await checkpoints.listForJob(job.id);
    expect(jobCheckpoints.length).toBeGreaterThanOrEqual(2);
    expect(events.some((e) => e.type === "completed")).toBe(true);
  });

  it("uploads attachments before submitting and marks them UPLOADED", async () => {
    const { jobs, runner, attachments } = makeHarness();
    const job = await jobs.create({
      title: "Job with files",
      provider: "mock",
      conversationUrl: "https://mock.aiflow.local/c/1",
      instructions: "Use the attached file.",
      executionMode: ExecutionMode.AUTONOMOUS,
      steps: ["Only step"],
    });
    await attachments.put({ id: "att_1", jobId: job.id, name: "notes.txt", type: "text/plain", data: new TextEncoder().encode("hello").buffer });
    await jobs.patch(job.id, {
      attachments: [{ id: "att_1", name: "notes.txt", size: 5, type: "text/plain", checksum: "x", addedAt: job.createdAt, status: "VALIDATED" }],
    });
    await jobs.queue(job.id);

    const finalJob = await driveUntil(runner, jobs, job.id, (s) => s === JobStatus.COMPLETED || s === JobStatus.FAILED);
    expect(finalJob.status).toBe(JobStatus.COMPLETED);
    expect(finalJob.attachments[0]?.status).toBe("UPLOADED");
  });

  it("waits (without spamming the provider) when the provider is at a usage limit, then proceeds once available", async () => {
    const { jobs, provider, runner, events } = makeHarness();
    provider.setScenario("LIMITED");
    const job = await jobs.create({
      title: "Waits for limit",
      provider: "mock",
      conversationUrl: "https://mock.aiflow.local/c/1",
      instructions: "Do a thing.",
      executionMode: ExecutionMode.AUTONOMOUS,
    });
    await jobs.queue(job.id);
    await runner.runStep(job.id);

    let current = await jobs.get(job.id);
    expect(current.status).toBe(JobStatus.WAITING_FOR_AVAILABILITY);
    expect(current.retryCount).toBe(1);
    expect(events.some((e) => e.type === "waiting")).toBe(true);

    // Calling runStep again while still limited must widen the backoff, not
    // resubmit or spam the provider.
    await runner.runStep(job.id);
    current = await jobs.get(job.id);
    expect(current.retryCount).toBe(2);

    provider.setScenario("AVAILABLE");
    const finalJob = await driveUntil(runner, jobs, job.id, (s) => s === JobStatus.COMPLETED);
    expect(finalJob.status).toBe(JobStatus.COMPLETED);
  });

  it("moves to REQUIRES_USER_ACTION on authentication required, without retrying", async () => {
    const { jobs, provider, runner, events } = makeHarness();
    provider.setScenario("AUTH_REQUIRED");
    const job = await jobs.create({ title: "Needs login", provider: "mock", conversationUrl: "https://mock.aiflow.local/c/1", instructions: "x" });
    await jobs.queue(job.id);
    await runner.runStep(job.id);

    const current = await jobs.get(job.id);
    expect(current.status).toBe(JobStatus.REQUIRES_USER_ACTION);
    expect(current.retryCount).toBe(0);
    expect(events.some((e) => e.type === "requiresAction")).toBe(true);
  });

  it("moves to REQUIRES_USER_ACTION when the open conversation doesn't match the job", async () => {
    const { jobs, provider, runner } = makeHarness();
    provider.setScenario("CONVERSATION_MISMATCH");
    const job = await jobs.create({ title: "Wrong chat", provider: "mock", conversationUrl: "https://mock.aiflow.local/c/1", instructions: "x" });
    await jobs.queue(job.id);
    const finalJob = await driveUntil(runner, jobs, job.id, (s) => s === JobStatus.REQUIRES_USER_ACTION);
    expect(finalJob.status).toBe(JobStatus.REQUIRES_USER_ACTION);
  });

  it("never resubmits an identical prompt twice in a row (loop protection)", async () => {
    const { jobs, runner } = makeHarness();
    const job = await jobs.create({
      title: "Duplicate guard",
      provider: "mock",
      conversationUrl: "https://mock.aiflow.local/c/1",
      instructions: "x",
      executionMode: ExecutionMode.MANUAL,
      requiresConfirmationBeforeSubmit: true,
    });
    await jobs.queue(job.id);
    await runner.runStep(job.id); // gets as far as PAUSED awaiting submit confirmation

    let current = await jobs.get(job.id);
    expect(current.status).toBe(JobStatus.PAUSED);
    expect(current.pendingAction).toBe("SUBMIT");

    await jobs.resume(job.id);
    await runner.runStep(job.id); // performs the confirmed submit
    current = await jobs.get(job.id);
    const firstHash = current.lastSubmittedHash;
    expect(firstHash).toBeTruthy();

    // Simulate a duplicate run (e.g. a reconciliation re-entry) without any
    // new checkpoint: it must not send a second identical message.
    const beforeHistoryLength = current.history.length;
    await jobs.patch(job.id, { status: JobStatus.SUBMITTING, requiresConfirmationBeforeSubmit: false, pendingAction: undefined });
    await runner.runStep(job.id);
    current = await jobs.get(job.id);
    expect(current.history.some((h) => h.code === "DUPLICATE_SUBMISSION_BLOCKED")).toBe(true);
    expect(current.history.length).toBeGreaterThan(beforeHistoryLength);
  });

  it("respects MAX_CONTINUATIONS and stops with REQUIRES_USER_ACTION instead of looping forever", async () => {
    const { jobs, runner } = makeHarness();
    const job = await jobs.create({
      title: "Runaway",
      provider: "mock",
      conversationUrl: "https://mock.aiflow.local/c/1",
      instructions: "x",
      executionMode: ExecutionMode.AUTONOMOUS,
      steps: Array.from({ length: 40 }, (_, i) => `Step ${i + 1}`),
    });
    await jobs.queue(job.id);
    const finalJob = await driveUntil(runner, jobs, job.id, (s) => s === JobStatus.PAUSED || s === JobStatus.COMPLETED, 200);
    expect(finalJob.status).toBe(JobStatus.PAUSED);
    expect(finalJob.lastError?.code).toBe("LOOP_GUARD");
    expect(finalJob.progress.continuationCount).toBeLessThanOrEqual(25);
  });
});
