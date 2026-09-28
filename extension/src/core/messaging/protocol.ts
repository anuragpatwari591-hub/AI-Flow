import type { CreateJobInput, Job } from "@/core/jobs/job.model";
import type { Checkpoint } from "@/core/checkpoint/checkpoint.model";
import type { Settings } from "@/core/storage/settings-store";
import type { ExportBundle } from "@/core/storage/export-import";

/** Messages sent from the UI (side panel / popup / options) to the background service worker. */
export type UiRequest =
  | { type: "LIST_JOBS" }
  | { type: "GET_JOB"; jobId: string }
  | { type: "CREATE_JOB"; input: CreateJobInput }
  | { type: "QUEUE_JOB"; jobId: string }
  | { type: "PAUSE_JOB"; jobId: string }
  | { type: "RESUME_JOB"; jobId: string }
  | { type: "CANCEL_JOB"; jobId: string }
  | { type: "RETRY_JOB"; jobId: string }
  | { type: "DUPLICATE_JOB"; jobId: string }
  | { type: "DELETE_JOB"; jobId: string }
  | { type: "RESTART_FROM_CHECKPOINT"; jobId: string; checkpointId: string }
  | { type: "LIST_CHECKPOINTS"; jobId: string }
  | { type: "GET_SETTINGS" }
  | { type: "UPDATE_SETTINGS"; patch: Partial<Settings> }
  | { type: "RESET_SETTINGS" }
  | { type: "EXPORT_DATA" }
  | { type: "IMPORT_DATA"; bundle: ExportBundle }
  | { type: "REQUEST_PROVIDER_PERMISSION"; domainPattern: string }
  | { type: "LIST_PROVIDER_PERMISSIONS" }
  | { type: "LIST_PROVIDERS" }
  | { type: "STORE_ATTACHMENT"; jobId: string; file: { name: string; type: string; size: number; data: ArrayBuffer } }
  | { type: "REMOVE_ATTACHMENT"; jobId: string; attachmentId: string }
  | { type: "CONFIRM_PENDING_ACTION"; jobId: string }
  | { type: "UPDATE_JOB_DETAILS"; jobId: string; patch: EditableJobPatch };

export interface EditableJobPatch {
  title?: string;
  instructions?: string;
  executionMode?: Job["executionMode"];
  priority?: Job["priority"];
  retryPolicy?: Job["retryPolicy"];
  notificationPreferences?: Job["notificationPreferences"];
  requiresConfirmationBeforeSubmit?: boolean;
  requiresConfirmationBeforeUpload?: boolean;
  conversationTitle?: string;
}

export type UiResponse<T = unknown> = { ok: true; data: T } | { ok: false; error: string };

export interface JobListResponse {
  jobs: Job[];
}
export interface CheckpointListResponse {
  checkpoints: Checkpoint[];
}
