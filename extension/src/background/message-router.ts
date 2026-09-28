import type { UiRequest, UiResponse } from "@/core/messaging/protocol";
import { JobManager } from "@/core/jobs/job-manager";
import { JobRunner } from "@/core/jobs/job-runner";
import { Scheduler } from "@/core/scheduler/scheduler";
import { CheckpointStore } from "@/core/checkpoint/checkpoint-store";
import { SettingsStore } from "@/core/storage/settings-store";
import { AttachmentStore } from "@/core/storage/attachment-store";
import { JobStore } from "@/core/storage/job-store";
import { ProviderRegistry } from "@/providers/provider-registry";
import { buildExportBundle, importExportBundle } from "@/core/storage/export-import";
import { requestProviderPermission, listGrantedProviderPermissions } from "@/security/permissions";
import { validateFile, MAX_TOTAL_ATTACHMENT_BYTES } from "@/utils/file-utils";
import { sha256Hex } from "@/utils/hash";
import { generateId } from "@/utils/id";
import { nowIso } from "@/utils/time";
import { sanitizeText } from "@/security/sanitize";
import type { AttachmentMeta } from "@/core/jobs/job.model";

export interface RouterContext {
  jobStore: JobStore;
  jobs: JobManager;
  runner: JobRunner;
  scheduler: Scheduler;
  checkpoints: CheckpointStore;
  settings: SettingsStore;
  attachments: AttachmentStore;
  providers: ProviderRegistry;
}

export async function handleUiRequest(request: UiRequest, ctx: RouterContext): Promise<UiResponse> {
  try {
    const data = await dispatch(request, ctx);
    return { ok: true, data };
  } catch (error) {
    return { ok: false, error: error instanceof Error ? error.message : String(error) };
  }
}

async function dispatch(request: UiRequest, ctx: RouterContext): Promise<unknown> {
  switch (request.type) {
    case "LIST_JOBS":
      return { jobs: await ctx.jobs.list() };

    case "GET_JOB":
      return ctx.jobs.get(request.jobId);

    case "CREATE_JOB": {
      const sanitizedInput = { ...request.input, instructions: sanitizeText(request.input.instructions) };
      return ctx.jobs.create(sanitizedInput);
    }

    case "QUEUE_JOB": {
      await ctx.jobs.queue(request.jobId);
      await ctx.runner.runStep(request.jobId);
      return ctx.jobs.get(request.jobId);
    }

    case "PAUSE_JOB": {
      const job = await ctx.jobs.pause(request.jobId);
      await ctx.scheduler.cancelJob(request.jobId);
      return job;
    }

    case "RESUME_JOB": {
      await ctx.jobs.resume(request.jobId);
      await ctx.runner.runStep(request.jobId);
      return ctx.jobs.get(request.jobId);
    }

    case "CONFIRM_PENDING_ACTION": {
      await ctx.jobs.resume(request.jobId);
      await ctx.runner.runStep(request.jobId);
      return ctx.jobs.get(request.jobId);
    }

    case "CANCEL_JOB": {
      const job = await ctx.jobs.cancel(request.jobId);
      await ctx.scheduler.cancelJob(request.jobId);
      return job;
    }

    case "RETRY_JOB": {
      await ctx.jobs.retry(request.jobId);
      await ctx.runner.runStep(request.jobId);
      return ctx.jobs.get(request.jobId);
    }

    case "DUPLICATE_JOB":
      return ctx.jobs.duplicate(request.jobId);

    case "DELETE_JOB": {
      await ctx.scheduler.cancelJob(request.jobId);
      await ctx.attachments.deleteForJob(request.jobId);
      await ctx.jobs.delete(request.jobId);
      return { deleted: true };
    }

    case "RESTART_FROM_CHECKPOINT": {
      await ctx.jobs.restartFromCheckpoint(request.jobId, request.checkpointId);
      await ctx.runner.runStep(request.jobId);
      return ctx.jobs.get(request.jobId);
    }

    case "LIST_CHECKPOINTS":
      return { checkpoints: await ctx.checkpoints.listForJob(request.jobId) };

    case "GET_SETTINGS":
      return ctx.settings.get();

    case "UPDATE_SETTINGS":
      return ctx.settings.update(request.patch);

    case "RESET_SETTINGS":
      return ctx.settings.reset();

    case "EXPORT_DATA":
      return buildExportBundle(ctx.jobStore, ctx.checkpoints, ctx.settings);

    case "IMPORT_DATA":
      return importExportBundle(request.bundle, ctx.jobStore, ctx.checkpoints, ctx.settings);

    case "REQUEST_PROVIDER_PERMISSION":
      return { granted: await requestProviderPermission(request.domainPattern) };

    case "LIST_PROVIDER_PERMISSIONS":
      return { origins: await listGrantedProviderPermissions() };

    case "LIST_PROVIDERS":
      return { providers: ctx.providers.list() };

    case "STORE_ATTACHMENT":
      return storeAttachment(request.jobId, request.file, ctx);

    case "UPDATE_JOB_DETAILS":
      return ctx.jobs.patch(request.jobId, request.patch);

    case "REMOVE_ATTACHMENT": {
      const job = await ctx.jobs.get(request.jobId);
      await ctx.attachments.delete(request.attachmentId);
      const attachments = job.attachments.filter((a) => a.id !== request.attachmentId);
      return ctx.jobs.patch(request.jobId, { attachments });
    }

    default:
      throw new Error(`Unknown request type: ${JSON.stringify(request)}`);
  }
}

async function storeAttachment(
  jobId: string,
  file: { name: string; type: string; size: number; data: ArrayBuffer },
  ctx: RouterContext,
): Promise<AttachmentMeta> {
  const job = await ctx.jobs.get(jobId);
  const validation = validateFile(file);
  const checksum = await sha256Hex(file.data);
  const totalExisting = job.attachments.reduce((sum, a) => sum + a.size, 0);
  const isDuplicate = job.attachments.some((a) => a.checksum === checksum);

  const meta: AttachmentMeta = {
    id: generateId("att"),
    name: file.name,
    size: file.size,
    type: file.type,
    checksum,
    addedAt: nowIso(),
    status: "PENDING",
  };

  if (!validation.valid) {
    meta.status = "REJECTED";
    meta.rejectionReason = validation.reason;
  } else if (isDuplicate) {
    meta.status = "REJECTED";
    meta.rejectionReason = "An identical file is already attached to this job.";
  } else if (totalExisting + file.size > MAX_TOTAL_ATTACHMENT_BYTES) {
    meta.status = "REJECTED";
    meta.rejectionReason = "Adding this file would exceed the per-job attachment size limit.";
  } else {
    meta.status = "VALIDATED";
    await ctx.attachments.put({ id: meta.id, jobId, name: file.name, type: file.type, data: file.data });
  }

  await ctx.jobs.patch(jobId, { attachments: [...job.attachments, meta] });
  return meta;
}
