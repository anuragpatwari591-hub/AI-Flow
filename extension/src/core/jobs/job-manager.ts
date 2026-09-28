import type { JobStore } from "@/core/storage/job-store";
import { createJob, type CreateJobInput, type Job, type JobHistoryEntry } from "@/core/jobs/job.model";
import { JobEvent, nextStatus, type JobEvent as JobEventType } from "@/core/state-machine/job-state-machine";
import { createLogEntry } from "@/core/events/logger";
import { nowIso } from "@/utils/time";

export class JobNotFoundError extends Error {
  constructor(id: string) {
    super(`Job not found: ${id}`);
  }
}

/**
 * The single place allowed to mutate a job's status. Wraps every mutation
 * with the deterministic state machine (`nextStatus`) so status can never
 * drift out of sync with a parallel boolean flag.
 */
export class JobManager {
  constructor(private readonly store: JobStore) {}

  async create(input: CreateJobInput): Promise<Job> {
    const job = createJob(input);
    await this.store.save(job);
    return job;
  }

  async list(): Promise<Job[]> {
    return this.store.list();
  }

  async get(id: string): Promise<Job> {
    const job = await this.store.get(id);
    if (!job) throw new JobNotFoundError(id);
    return job;
  }

  async apply(id: string, event: JobEventType, patch: Partial<Job> = {}, logEntry?: Omit<JobHistoryEntry, "id" | "timestamp">): Promise<Job> {
    const job = await this.get(id);
    const to = nextStatus(job.status, event);
    const updated: Job = {
      ...job,
      ...patch,
      status: to,
      updatedAt: nowIso(),
    };
    if (logEntry) {
      updated.history = [...updated.history, { ...createLogEntry(logEntry.level, logEntry.code, logEntry.message) }];
    }
    await this.store.save(updated);
    return updated;
  }

  async log(id: string, level: JobHistoryEntry["level"], code: string, message: string): Promise<Job> {
    const job = await this.get(id);
    const updated: Job = {
      ...job,
      updatedAt: nowIso(),
      history: [...job.history, createLogEntry(level, code, message)],
    };
    await this.store.save(updated);
    return updated;
  }

  async patch(id: string, patch: Partial<Job>): Promise<Job> {
    const job = await this.get(id);
    const updated: Job = { ...job, ...patch, updatedAt: nowIso() };
    await this.store.save(updated);
    return updated;
  }

  async queue(id: string): Promise<Job> {
    return this.apply(id, JobEvent.QUEUE, {}, { level: "INFO", code: "JOB_QUEUED", message: "Job queued for execution." });
  }

  async pause(id: string): Promise<Job> {
    return this.apply(id, JobEvent.PAUSE, {}, { level: "INFO", code: "JOB_PAUSED", message: "Job paused by user." });
  }

  async resume(id: string): Promise<Job> {
    // Intentionally keeps `pendingAction` as-is: it marks which step (if
    // any) the user just confirmed, so the runner can perform exactly that
    // step once without re-prompting, then clear it itself.
    return this.apply(
      id,
      JobEvent.RESUME,
      {},
      { level: "INFO", code: "JOB_RESUMED", message: "Job resumed by user." },
    );
  }

  async cancel(id: string): Promise<Job> {
    return this.apply(id, JobEvent.CANCEL, {}, { level: "WARNING", code: "JOB_CANCELLED", message: "Job cancelled by user." });
  }

  async retry(id: string): Promise<Job> {
    return this.apply(
      id,
      JobEvent.RETRY,
      { retryCount: 0, lastError: undefined, pendingAction: undefined },
      { level: "INFO", code: "JOB_RETRY", message: "Job re-queued after failure." },
    );
  }

  async restartFromCheckpoint(id: string, checkpointId: string): Promise<Job> {
    return this.apply(
      id,
      JobEvent.RESTART_FROM_CHECKPOINT,
      { checkpointId, retryCount: 0, lastError: undefined },
      { level: "INFO", code: "JOB_RESTARTED", message: `Job restarted from checkpoint ${checkpointId}.` },
    );
  }

  async duplicate(id: string): Promise<Job> {
    const original = await this.get(id);
    return this.create({
      title: `${original.title} (copy)`,
      provider: original.provider,
      conversationUrl: original.conversationUrl,
      conversationId: original.conversationId,
      conversationTitle: original.conversationTitle,
      instructions: original.instructions,
      attachments: [],
      executionMode: original.executionMode,
      priority: original.priority,
      retryPolicy: original.retryPolicy,
      notificationPreferences: original.notificationPreferences,
      steps: [...original.progress.completedSteps, ...original.progress.remainingSteps],
    });
  }

  async delete(id: string): Promise<void> {
    await this.store.delete(id);
  }
}
