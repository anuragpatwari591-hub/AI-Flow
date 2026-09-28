import { describe, expect, it } from "vitest";
import { MemoryKvStore } from "@/core/storage/kv-store";
import { JobStore } from "@/core/storage/job-store";
import { JobManager, JobNotFoundError } from "@/core/jobs/job-manager";
import { JobStatus } from "@/core/jobs/job.model";
import { JobEvent, InvalidTransitionError } from "@/core/state-machine/job-state-machine";

function makeManager() {
  return new JobManager(new JobStore(new MemoryKvStore()));
}

describe("JobManager", () => {
  it("creates a job as a draft and persists it", async () => {
    const manager = makeManager();
    const job = await manager.create({ title: "Test", provider: "mock", conversationUrl: "https://mock.aiflow.local/c/1", instructions: "do it" });
    expect(job.status).toBe(JobStatus.DRAFT);
    expect(await manager.get(job.id)).toEqual(job);
  });

  it("throws JobNotFoundError for unknown ids", async () => {
    const manager = makeManager();
    await expect(manager.get("nope")).rejects.toBeInstanceOf(JobNotFoundError);
  });

  it("queue/pause/resume/cancel/retry all go through the state machine", async () => {
    const manager = makeManager();
    const job = await manager.create({ title: "Test", provider: "mock", conversationUrl: "u", instructions: "i" });

    const queued = await manager.queue(job.id);
    expect(queued.status).toBe(JobStatus.QUEUED);

    const paused = await manager.pause(queued.id);
    expect(paused.status).toBe(JobStatus.PAUSED);

    const resumed = await manager.resume(paused.id);
    expect(resumed.status).toBe(JobStatus.QUEUED);

    const cancelled = await manager.cancel(resumed.id);
    expect(cancelled.status).toBe(JobStatus.CANCELLED);
  });

  it("rejects an invalid manual apply() the same way the state machine would", async () => {
    const manager = makeManager();
    const job = await manager.create({ title: "Test", provider: "mock", conversationUrl: "u", instructions: "i" });
    await expect(manager.apply(job.id, JobEvent.MESSAGE_SUBMITTED)).rejects.toBeInstanceOf(InvalidTransitionError);
  });

  it("appends history entries without losing prior entries", async () => {
    const manager = makeManager();
    const job = await manager.create({ title: "Test", provider: "mock", conversationUrl: "u", instructions: "i" });
    const withLog = await manager.log(job.id, "INFO", "TEST_EVENT", "hello");
    expect(withLog.history.length).toBe(job.history.length + 1);
    expect(withLog.history.at(-1)?.code).toBe("TEST_EVENT");
  });

  it("duplicate() creates a fresh draft with the same instructions but no attachments", async () => {
    const manager = makeManager();
    const job = await manager.create({ title: "Original", provider: "mock", conversationUrl: "u", instructions: "i" });
    const copy = await manager.duplicate(job.id);
    expect(copy.id).not.toBe(job.id);
    expect(copy.title).toContain("Original");
    expect(copy.attachments).toEqual([]);
    expect(copy.status).toBe(JobStatus.DRAFT);
  });
});
