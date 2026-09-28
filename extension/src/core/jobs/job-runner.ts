import { JobManager } from "@/core/jobs/job-manager";
import { CheckpointStore } from "@/core/checkpoint/checkpoint-store";
import { createCheckpoint, type CreateCheckpointInput } from "@/core/checkpoint/checkpoint.model";
import { Scheduler } from "@/core/scheduler/scheduler";
import { ProviderRegistry } from "@/providers/provider-registry";
import { AttachmentStore } from "@/core/storage/attachment-store";
import { JobStatus, type Job } from "@/core/jobs/job.model";
import { JobEvent } from "@/core/state-machine/job-state-machine";
import { decideAvailabilityAction } from "@/core/availability/availability-engine";
import { classifyErrorCode, decideRetry } from "@/core/retry/retry-engine";
import { composePrompt } from "@/core/prompt-engine/prompt-composer";
import { computeSubmissionFingerprint, isDuplicateSubmission, checkLoopGuards } from "@/core/jobs/loop-protection";
import { nowIso } from "@/utils/time";
import { ExecutionMode, type JobError } from "@/core/jobs/job.model";

export const RESPONSE_POLL_INTERVAL_MS = 10_000;

export type JobRunnerEvent =
  | { type: "waiting"; job: Job }
  | { type: "resumed"; job: Job }
  | { type: "requiresAction"; job: Job }
  | { type: "completed"; job: Job }
  | { type: "failed"; job: Job };

interface NormalizedError {
  code: string;
  message: string;
}

function normalizeError(error: unknown): NormalizedError {
  if (error && typeof error === "object" && "code" in error && "message" in error) {
    return error as NormalizedError;
  }
  if (error instanceof Error) return { code: "UNKNOWN", message: error.message };
  return { code: "UNKNOWN", message: String(error) };
}

/**
 * Drives a single job forward, one status at a time. Every step is
 * resumable: on failure, progress already made (verified conversation tab,
 * uploaded attachments, the last submitted prompt hash) is persisted
 * before the job goes back to WAITING_FOR_AVAILABILITY/REQUIRES_USER_ACTION/
 * FAILED, so re-running the job later never repeats already-completed
 * work.
 */
export class JobRunner {
  constructor(
    private readonly jobs: JobManager,
    private readonly checkpoints: CheckpointStore,
    private readonly scheduler: Scheduler,
    private readonly providers: ProviderRegistry,
    private readonly attachmentStore: AttachmentStore,
    private readonly onEvent?: (event: JobRunnerEvent) => void,
  ) {}

  async runStep(jobId: string): Promise<void> {
    const job = await this.jobs.get(jobId);
    switch (job.status) {
      case JobStatus.QUEUED:
        return this.handleQueued(job);
      case JobStatus.WAITING_FOR_AVAILABILITY:
        return this.handleWaitingForAvailability(job);
      case JobStatus.READY:
        return this.handleReady(job);
      case JobStatus.UPLOADING:
        return this.handleUploading(job);
      case JobStatus.SUBMITTING:
        return this.handleSubmitting(job);
      case JobStatus.PROCESSING:
        return this.handleProcessing(job);
      case JobStatus.WAITING_FOR_RESPONSE:
        return this.handleWaitingForResponse(job);
      case JobStatus.CONTINUING:
        return this.handleContinuing(job);
      default:
        return; // RUNNING is transient within handleReady; other states need explicit user action.
    }
  }

  private async handleQueued(job: Job): Promise<void> {
    const updated = await this.jobs.apply(
      job.id,
      JobEvent.CHECK_AVAILABILITY,
      {},
      { level: "INFO", code: "PROVIDER_DETECTED", message: `Checking availability for provider "${job.provider}".` },
    );
    return this.handleWaitingForAvailability(updated);
  }

  private async handleWaitingForAvailability(job: Job): Promise<void> {
    const provider = this.providers.get(job.provider);
    const result = await provider.getAvailability();
    const decision = decideAvailabilityAction(result, job.retryCount + 1);

    if (decision.action === "PROCEED") {
      const updated = await this.jobs.apply(
        job.id,
        JobEvent.AVAILABILITY_CONFIRMED,
        { retryCount: 0, nextAttemptAt: undefined },
        { level: "SUCCESS", code: "AVAILABILITY_CONFIRMED", message: decision.reason },
      );
      await this.scheduler.cancelJob(job.id);
      if (job.retryCount > 0 && job.notificationPreferences.onResumed) {
        this.onEvent?.({ type: "resumed", job: updated });
      }
      return this.handleReady(updated);
    }

    if (decision.action === "WAIT") {
      const nextAttemptAt = new Date(Date.now() + decision.waitMs).toISOString();
      const updated = await this.jobs.apply(
        job.id,
        JobEvent.AVAILABILITY_STILL_LIMITED,
        { retryCount: job.retryCount + 1, nextAttemptAt },
        job.retryCount === 0
          ? { level: "WARNING", code: "PROVIDER_LIMIT_DETECTED", message: decision.reason }
          : { level: "DEBUG", code: "JOB_WAITING", message: decision.reason },
      );
      await this.scheduler.scheduleJobAfterDelay(job.id, decision.waitMs);
      if (job.retryCount === 0 && job.notificationPreferences.onWaiting) {
        this.onEvent?.({ type: "waiting", job: updated });
      }
      return;
    }

    // REQUIRES_USER_ACTION
    const lastError: JobError = { code: "AUTH_REQUIRED", message: decision.reason, occurredAt: nowIso(), retryable: false };
    const updated = await this.jobs.apply(
      job.id,
      JobEvent.AUTH_REQUIRED,
      { lastError },
      { level: "ERROR", code: "AUTH_REQUIRED", message: decision.reason },
    );
    await this.scheduler.cancelJob(job.id);
    if (job.notificationPreferences.onRequiresAction) this.onEvent?.({ type: "requiresAction", job: updated });
  }

  private async handleReady(job: Job): Promise<void> {
    let current = await this.jobs.apply(
      job.id,
      JobEvent.START_EXECUTION,
      {},
      { level: "INFO", code: "JOB_RUNNING", message: "Opening the conversation." },
    );
    const provider = this.providers.get(current.provider);

    try {
      const { tabId } = current.tabId
        ? { tabId: current.tabId }
        : await provider.openConversation(current.conversationUrl);
      const verification = await provider.verifyConversation(tabId, {
        url: current.conversationUrl,
        id: current.conversationId,
        title: current.conversationTitle,
      });
      if (!verification.verified) {
        throw { code: "VERIFICATION_FAILED", message: verification.reason };
      }
      current = await this.jobs.patch(current.id, {
        tabId,
        conversationId: verification.metadata?.id ?? current.conversationId,
        conversationTitle: verification.metadata?.title ?? current.conversationTitle,
      });
      current = await this.jobs.log(current.id, "SUCCESS", "CONVERSATION_VERIFIED", verification.reason);
    } catch (error) {
      return this.handleExecutionError(current, normalizeError(error));
    }

    return this.proceedToUploadOrSubmit(current, JobEvent.BEGIN_UPLOAD, JobEvent.SKIP_UPLOAD);
  }

  private async proceedToUploadOrSubmit(job: Job, uploadEvent: JobEvent, skipEvent: JobEvent): Promise<void> {
    const pending = job.attachments.filter((a) => a.status !== "UPLOADED");
    if (pending.length === 0) {
      // Preserve a still-pending SUBMIT confirmation marker across this
      // no-op upload step; only an UPLOAD/CONTINUE marker is consumed here.
      const carryOver = job.pendingAction === "SUBMIT" ? "SUBMIT" : undefined;
      const updated = await this.jobs.apply(
        job.id,
        skipEvent,
        { pendingAction: carryOver },
        { level: "INFO", code: "NO_PENDING_UPLOADS", message: "No attachments to upload." },
      );
      return this.handleSubmitting(updated);
    }
    if (job.requiresConfirmationBeforeUpload && job.pendingAction !== "UPLOAD") {
      await this.jobs.apply(
        job.id,
        JobEvent.PAUSE,
        { pendingAction: "UPLOAD" },
        { level: "INFO", code: "AWAITING_UPLOAD_CONFIRMATION", message: "Waiting for user confirmation before uploading files." },
      );
      return;
    }
    const updated = await this.jobs.apply(
      job.id,
      uploadEvent,
      { pendingAction: undefined },
      { level: "INFO", code: "FILE_UPLOAD_STARTED", message: `Uploading ${pending.length} file(s).` },
    );
    return this.handleUploading(updated);
  }

  private async handleUploading(job: Job): Promise<void> {
    const provider = this.providers.get(job.provider);
    const tabId = job.tabId!;
    const attachments = [...job.attachments];

    for (let i = 0; i < attachments.length; i++) {
      const attachment = attachments[i]!;
      if (attachment.status === "UPLOADED") continue;
      try {
        const stored = await this.attachmentStore.get(attachment.id);
        if (!stored) throw { code: "MALFORMED_JOB", message: `Attachment data missing for ${attachment.name}.` };
        const file = { name: stored.name, type: stored.type, data: stored.data };
        const attachResult = await provider.attachFile(tabId, file);
        if (!attachResult.success) throw { code: "PROVIDER_ERROR", message: attachResult.reason ?? "Attach failed." };
        const verifyResult = await provider.verifyAttachment(tabId, file);
        if (!verifyResult.success) throw { code: "PROVIDER_ERROR", message: verifyResult.reason ?? "Attachment verification failed." };
        attachments[i] = { ...attachment, status: "UPLOADED" };
        await this.jobs.patch(job.id, { attachments: [...attachments] });
        await this.jobs.log(job.id, "SUCCESS", "FILE_UPLOAD_COMPLETED", `Uploaded ${attachment.name}.`);
      } catch (error) {
        await this.jobs.patch(job.id, { attachments: [...attachments] });
        const latest = await this.jobs.get(job.id);
        return this.handleExecutionError(latest, normalizeError(error));
      }
    }

    const updated = await this.jobs.apply(
      job.id,
      JobEvent.UPLOAD_COMPLETE,
      { attachments },
      { level: "INFO", code: "FILE_UPLOAD_COMPLETED", message: "All attachments uploaded." },
    );
    return this.handleSubmitting(updated);
  }

  private async handleSubmitting(job: Job): Promise<void> {
    if (job.requiresConfirmationBeforeSubmit && job.pendingAction !== "SUBMIT") {
      await this.jobs.apply(
        job.id,
        JobEvent.PAUSE,
        { pendingAction: "SUBMIT" },
        { level: "INFO", code: "AWAITING_SUBMIT_CONFIRMATION", message: "Waiting for user confirmation before submitting." },
      );
      return;
    }

    const checkpoint = job.checkpointId ? await this.checkpoints.get(job.checkpointId) : await this.checkpoints.latestForJob(job.id);
    const promptText = composePrompt(job, checkpoint);
    const fingerprint = await computeSubmissionFingerprint(job, checkpoint);
    const provider = this.providers.get(job.provider);
    const tabId = job.tabId!;

    if (isDuplicateSubmission(job, fingerprint)) {
      await this.jobs.log(job.id, "WARNING", "DUPLICATE_SUBMISSION_BLOCKED", "Skipped re-sending an identical prompt (loop protection).");
      const updated = await this.jobs.apply(job.id, JobEvent.MESSAGE_SUBMITTED, { pendingAction: undefined }, {
        level: "INFO",
        code: "PROMPT_SUBMITTED",
        message: "Reusing previous submission (idempotent).",
      });
      return this.handleProcessing(updated);
    }

    try {
      const compose = await provider.composeMessage(tabId, promptText);
      if (!compose.success) throw { code: "PROVIDER_ERROR", message: compose.reason ?? "Failed to compose message." };
      const submit = await provider.submitMessage(tabId);
      if (!submit.success) throw { code: "PROVIDER_ERROR", message: submit.reason ?? "Failed to submit message." };
    } catch (error) {
      return this.handleExecutionError(job, normalizeError(error));
    }

    const updated = await this.jobs.apply(
      job.id,
      JobEvent.MESSAGE_SUBMITTED,
      { lastSubmittedHash: fingerprint, pendingAction: undefined },
      { level: "SUCCESS", code: "PROMPT_SUBMITTED", message: "Prompt submitted to the provider." },
    );
    return this.handleProcessing(updated);
  }

  private async handleProcessing(job: Job): Promise<void> {
    const updated = await this.jobs.apply(
      job.id,
      JobEvent.ENTER_WAITING_FOR_RESPONSE,
      {},
      { level: "INFO", code: "AWAITING_RESPONSE", message: "Waiting for the provider's response." },
    );
    await this.scheduler.scheduleJobAfterDelay(updated.id, RESPONSE_POLL_INTERVAL_MS);
  }

  private async handleWaitingForResponse(job: Job): Promise<void> {
    const provider = this.providers.get(job.provider);
    const tabId = job.tabId!;

    try {
      const state = await provider.readConversationState(tabId);
      if (state.state === "GENERATING") {
        const updated = await this.jobs.apply(job.id, JobEvent.RECHECK_RESPONSE, {});
        await this.scheduler.scheduleJobAfterDelay(updated.id, RESPONSE_POLL_INTERVAL_MS);
        return;
      }
      if (state.state === "ERROR") {
        throw { code: "PROVIDER_ERROR", message: state.latestMessageText ?? "Provider reported an error." };
      }

      const completed = [...job.progress.completedSteps];
      const remaining = [...job.progress.remainingSteps];
      const justCompleted = remaining.shift();
      if (justCompleted) completed.push(justCompleted);

      const checkpointInput: CreateCheckpointInput = {
        jobId: job.id,
        state: job.status,
        completedTasks: completed,
        remainingTasks: remaining,
        provider: job.provider,
        conversationUrl: job.conversationUrl,
        executionSummary: (state.latestMessageText ?? "").slice(0, 800),
        nextAction: remaining[0] ?? "None — all steps complete.",
      };
      const checkpoint = createCheckpoint(checkpointInput);
      await this.checkpoints.append(checkpoint);
      await this.jobs.log(job.id, "SUCCESS", "CHECKPOINT_CREATED", `Checkpoint created (${completed.length} done, ${remaining.length} remaining).`);

      const progress = { completedSteps: completed, remainingSteps: remaining, continuationCount: job.progress.continuationCount };

      if (remaining.length === 0) {
        const updated = await this.jobs.apply(
          job.id,
          JobEvent.RESPONSE_DONE,
          { checkpointId: checkpoint.id, progress },
          { level: "SUCCESS", code: "JOB_COMPLETED", message: "All steps completed." },
        );
        await this.scheduler.cancelJob(job.id);
        if (job.notificationPreferences.onCompleted) this.onEvent?.({ type: "completed", job: updated });
        return;
      }

      const guard = checkLoopGuards(job);
      if (!guard.allowed) {
        const updated = await this.jobs.apply(
          job.id,
          JobEvent.RESPONSE_NEEDS_APPROVAL,
          {
            checkpointId: checkpoint.id,
            progress,
            pendingAction: "CONTINUE",
            lastError: { code: "LOOP_GUARD", message: guard.reason ?? "Loop guard triggered.", occurredAt: nowIso(), retryable: false },
          },
          { level: "WARNING", code: "LOOP_GUARD_TRIGGERED", message: guard.reason ?? "Loop guard triggered." },
        );
        if (updated.notificationPreferences.onRequiresAction) this.onEvent?.({ type: "requiresAction", job: updated });
        return;
      }

      if (job.executionMode === ExecutionMode.AUTONOMOUS) {
        const updated = await this.jobs.apply(
          job.id,
          JobEvent.RESPONSE_CONTINUE,
          { checkpointId: checkpoint.id, progress: { ...progress, continuationCount: progress.continuationCount + 1 } },
          { level: "INFO", code: "NEXT_STEP_GENERATED", message: `Continuing automatically: ${checkpointInput.nextAction}` },
        );
        return this.handleContinuing(updated);
      }

      const updated = await this.jobs.apply(
        job.id,
        JobEvent.RESPONSE_NEEDS_APPROVAL,
        { checkpointId: checkpoint.id, progress, pendingAction: "CONTINUE" },
        { level: "INFO", code: "NEXT_STEP_READY", message: `Next step ready, waiting for approval: ${checkpointInput.nextAction}` },
      );
      await this.scheduler.cancelJob(job.id);
      void updated;
    } catch (error) {
      return this.handleExecutionError(job, normalizeError(error));
    }
  }

  private async handleContinuing(job: Job): Promise<void> {
    return this.proceedToUploadOrSubmit(job, JobEvent.CONTINUE_WITH_UPLOAD, JobEvent.CONTINUE_SKIP_UPLOAD);
  }

  private async handleExecutionError(job: Job, error: NormalizedError): Promise<void> {
    const category = classifyErrorCode(error.code);
    const decision = decideRetry(category, job.retryCount + 1, job.retryPolicy.maxAttempts);
    const lastError: JobError = { code: error.code, message: error.message, occurredAt: nowIso(), retryable: decision.outcome === "RETRY" };

    if (decision.outcome === "RETRY") {
      const nextAttemptAt = new Date(Date.now() + (decision.delayMs ?? 0)).toISOString();
      const updated = await this.jobs.apply(
        job.id,
        JobEvent.LIMIT_DETECTED,
        { retryCount: job.retryCount + 1, nextAttemptAt, lastError },
        { level: "WARNING", code: error.code, message: decision.reason },
      );
      await this.scheduler.scheduleJobAfterDelay(updated.id, decision.delayMs ?? 0);
      return;
    }

    if (decision.outcome === "REQUIRES_USER_ACTION") {
      const event = category === "AUTH_REQUIRED" ? JobEvent.AUTH_REQUIRED : JobEvent.VERIFICATION_FAILED;
      const updated = await this.jobs.apply(job.id, event, { lastError }, { level: "ERROR", code: error.code, message: error.message });
      await this.scheduler.cancelJob(job.id);
      if (updated.notificationPreferences.onRequiresAction) this.onEvent?.({ type: "requiresAction", job: updated });
      return;
    }

    const updated = await this.jobs.apply(job.id, JobEvent.ERROR, { lastError }, { level: "ERROR", code: error.code, message: error.message });
    await this.scheduler.cancelJob(job.id);
    if (updated.notificationPreferences.onFailed) this.onEvent?.({ type: "failed", job: updated });
  }
}
