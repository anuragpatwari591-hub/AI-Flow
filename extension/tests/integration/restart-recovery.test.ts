import { describe, expect, it } from "vitest";
import { MemoryKvStore } from "@/core/storage/kv-store";
import { JobStore } from "@/core/storage/job-store";
import { CheckpointStore } from "@/core/checkpoint/checkpoint-store";
import { JobManager } from "@/core/jobs/job-manager";
import { JobRunner } from "@/core/jobs/job-runner";
import { Scheduler, QUEUE_TICK_ALARM } from "@/core/scheduler/scheduler";
import { FakeAlarmsPort } from "@/core/scheduler/alarms-port";
import { AttachmentStore } from "@/core/storage/attachment-store";
import { ProviderRegistry } from "@/providers/provider-registry";
import { MockAIProvider } from "@/providers/mock/mock-provider";
import { JobStatus, ExecutionMode } from "@/core/jobs/job.model";
import { reconcileOnStartup } from "@/background/reconciliation";

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
  const runner = new JobRunner(jobs, checkpoints, scheduler, providers, attachments);
  return { jobs, checkpoints, scheduler, alarms, provider, attachments, runner };
}

describe("startup reconciliation (simulated browser/service-worker restart)", () => {
  it("resumes a job stuck WAITING_FOR_RESPONSE whose alarm was lost, without reopening the conversation", async () => {
    const { jobs, scheduler, alarms, runner } = makeHarness();

    const job = await jobs.create({
      title: "Interrupted job",
      provider: "mock",
      conversationUrl: "https://mock.aiflow.local/c/1",
      instructions: "x",
      executionMode: ExecutionMode.AUTONOMOUS,
      steps: ["Only step"],
    });
    await jobs.queue(job.id);
    await runner.runStep(job.id); // runs all the way to WAITING_FOR_RESPONSE, opening a real tab

    const midFlight = await jobs.get(job.id);
    expect(midFlight.status).toBe(JobStatus.WAITING_FOR_RESPONSE);
    const tabId = midFlight.tabId;
    expect(tabId).toBeDefined();

    // Simulate the alarm being lost across a restart (the job's status/tabId
    // persisted fine, but the in-memory alarm did not survive).
    await scheduler.cancelJob(job.id);

    await reconcileOnStartup(jobs, scheduler, runner);

    const recovered = await jobs.get(job.id);
    expect(recovered.status).toBe(JobStatus.COMPLETED);
    expect(recovered.tabId).toBe(tabId); // never reopened a second tab
    expect(recovered.history.some((h) => h.code === "JOB_RECONCILED")).toBe(true);

    const alarmsList = await alarms.getAll();
    expect(alarmsList.some((a) => a.name === QUEUE_TICK_ALARM)).toBe(true);
  });

  it("does not touch a job that already has a pending alarm", async () => {
    const { jobs, scheduler, runner } = makeHarness();

    const job = await jobs.create({ title: "Waiting job", provider: "mock", conversationUrl: "u", instructions: "x" });
    await jobs.queue(job.id);
    await jobs.patch(job.id, { status: JobStatus.WAITING_FOR_AVAILABILITY });
    await scheduler.scheduleJobAfterDelay(job.id, 60_000);

    const historyBefore = (await jobs.get(job.id)).history.length;
    await reconcileOnStartup(jobs, scheduler, runner);
    const historyAfter = (await jobs.get(job.id)).history.length;

    expect(historyAfter).toBe(historyBefore); // untouched: its own alarm will fire it later
  });

  it("never loses or duplicates an already-uploaded attachment when a job resumes after being interrupted mid-upload", async () => {
    const { jobs, provider, scheduler, runner, attachments } = makeHarness();

    const job = await jobs.create({
      title: "Two files",
      provider: "mock",
      conversationUrl: "https://mock.aiflow.local/c/1",
      instructions: "x",
      executionMode: ExecutionMode.AUTONOMOUS,
      steps: ["Only step"],
    });
    await attachments.put({ id: "a1", jobId: job.id, name: "one.txt", type: "text/plain", data: new ArrayBuffer(1) });
    await attachments.put({ id: "a2", jobId: job.id, name: "two.txt", type: "text/plain", data: new ArrayBuffer(1) });

    // Prime a real tab known to the mock provider (as if the job had
    // already opened and verified its conversation before being killed).
    const { tabId } = await provider.openConversation(job.conversationUrl);

    await jobs.queue(job.id);
    await jobs.patch(job.id, {
      status: JobStatus.UPLOADING,
      tabId,
      attachments: [
        { id: "a1", name: "one.txt", size: 1, type: "text/plain", checksum: "x", addedAt: job.createdAt, status: "UPLOADED" },
        { id: "a2", name: "two.txt", size: 1, type: "text/plain", checksum: "y", addedAt: job.createdAt, status: "VALIDATED" },
      ],
    });
    // No alarm exists for this job, simulating a lost in-flight upload step.
    await scheduler.cancelJob(job.id);

    await reconcileOnStartup(jobs, scheduler, runner);

    // reconcileOnStartup drives the job one step forward (through the
    // remaining upload + submit) and leaves it WAITING_FOR_RESPONSE with a
    // freshly scheduled poll alarm; simulate that alarm firing once more.
    const afterReconcile = await jobs.get(job.id);
    expect(afterReconcile.status).toBe(JobStatus.WAITING_FOR_RESPONSE);
    expect(afterReconcile.attachments.every((a) => a.status === "UPLOADED")).toBe(true);
    await runner.runStep(job.id);

    const finalJob = await jobs.get(job.id);
    expect(finalJob.status).toBe(JobStatus.COMPLETED);
    expect(finalJob.attachments).toHaveLength(2);
    expect(finalJob.attachments.every((a) => a.status === "UPLOADED")).toBe(true);
  });
});
