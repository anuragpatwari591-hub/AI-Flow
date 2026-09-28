import { JobManager } from "@/core/jobs/job-manager";
import { Scheduler } from "@/core/scheduler/scheduler";
import { JobRunner } from "@/core/jobs/job-runner";
import { JobStatus } from "@/core/jobs/job.model";

const RECONCILABLE_STATUSES = new Set<string>([
  JobStatus.QUEUED,
  JobStatus.WAITING_FOR_AVAILABILITY,
  JobStatus.READY,
  JobStatus.RUNNING,
  JobStatus.UPLOADING,
  JobStatus.SUBMITTING,
  JobStatus.PROCESSING,
  JobStatus.WAITING_FOR_RESPONSE,
  JobStatus.CONTINUING,
]);

/**
 * Runs on service-worker startup (and on install) to restore state that
 * only lives in memory otherwise: re-create the queue-tick alarm, and for
 * any job that's mid-flight but has no pending alarm (most likely because
 * the service worker was killed between steps), resume it from exactly
 * where its persisted status/checkpoint/attachment progress left off.
 */
export async function reconcileOnStartup(jobs: JobManager, scheduler: Scheduler, runner: JobRunner): Promise<void> {
  await scheduler.ensureQueueTick();
  const allJobs = await jobs.list();
  const scheduledJobIds = new Set(await scheduler.listScheduledJobIds());

  for (const job of allJobs) {
    if (!RECONCILABLE_STATUSES.has(job.status)) continue;
    if (scheduledJobIds.has(job.id)) continue;
    await jobs.log(job.id, "INFO", "JOB_RECONCILED", "Resuming job after a browser or service-worker restart.");
    await runner.runStep(job.id);
  }
}

/** Called on the periodic queue-tick alarm: catches any job whose scheduled time has passed but whose alarm didn't fire it directly (defensive; alarms should fire jobs on their own). */
export async function reconcileQueueTick(jobs: JobManager, scheduler: Scheduler, runner: JobRunner): Promise<void> {
  const allJobs = await jobs.list();
  const scheduledJobIds = new Set(await scheduler.listScheduledJobIds());
  const now = Date.now();

  for (const job of allJobs) {
    if (!RECONCILABLE_STATUSES.has(job.status)) continue;
    if (scheduledJobIds.has(job.id)) continue;
    if (job.nextAttemptAt && new Date(job.nextAttemptAt).getTime() > now) continue;
    await runner.runStep(job.id);
  }
}
