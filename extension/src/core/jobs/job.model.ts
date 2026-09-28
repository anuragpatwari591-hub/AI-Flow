import { generateId } from "@/utils/id";
import { nowIso } from "@/utils/time";

export const JobStatus = {
  DRAFT: "DRAFT",
  QUEUED: "QUEUED",
  WAITING_FOR_AVAILABILITY: "WAITING_FOR_AVAILABILITY",
  READY: "READY",
  RUNNING: "RUNNING",
  UPLOADING: "UPLOADING",
  SUBMITTING: "SUBMITTING",
  PROCESSING: "PROCESSING",
  WAITING_FOR_RESPONSE: "WAITING_FOR_RESPONSE",
  CONTINUING: "CONTINUING",
  COMPLETED: "COMPLETED",
  FAILED: "FAILED",
  PAUSED: "PAUSED",
  CANCELLED: "CANCELLED",
  REQUIRES_USER_ACTION: "REQUIRES_USER_ACTION",
} as const;

export type JobStatus = (typeof JobStatus)[keyof typeof JobStatus];

export const ExecutionMode = {
  MANUAL: "MANUAL",
  SEMI_AUTOMATIC: "SEMI_AUTOMATIC",
  AUTONOMOUS: "AUTONOMOUS",
} as const;
export type ExecutionMode = (typeof ExecutionMode)[keyof typeof ExecutionMode];

export const JobPriority = {
  LOW: "LOW",
  NORMAL: "NORMAL",
  HIGH: "HIGH",
} as const;
export type JobPriority = (typeof JobPriority)[keyof typeof JobPriority];

export interface AttachmentMeta {
  id: string;
  name: string;
  size: number;
  type: string;
  checksum: string;
  addedAt: string;
  status: "PENDING" | "VALIDATED" | "REJECTED" | "UPLOADED" | "UPLOAD_FAILED";
  rejectionReason?: string;
}

export interface RetryPolicy {
  maxAttempts: number;
  baseDelayMs: number;
}

export interface NotificationPreferences {
  onWaiting: boolean;
  onResumed: boolean;
  onRequiresAction: boolean;
  onCompleted: boolean;
  onFailed: boolean;
}

export interface JobHistoryEntry {
  id: string;
  timestamp: string;
  level: "INFO" | "SUCCESS" | "WARNING" | "ERROR" | "DEBUG";
  code: string;
  message: string;
}

export interface JobError {
  code: string;
  message: string;
  occurredAt: string;
  retryable: boolean;
}

export interface Job {
  id: string;
  title: string;
  provider: string;
  conversationUrl: string;
  conversationId?: string;
  conversationTitle?: string;
  instructions: string;
  attachments: AttachmentMeta[];
  executionMode: ExecutionMode;
  status: JobStatus;
  priority: JobPriority;
  createdAt: string;
  updatedAt: string;
  nextAttemptAt?: string;
  retryCount: number;
  retryPolicy: RetryPolicy;
  checkpointId?: string;
  lastError?: JobError;
  progress: {
    completedSteps: string[];
    remainingSteps: string[];
    continuationCount: number;
  };
  history: JobHistoryEntry[];
  notificationPreferences: NotificationPreferences;
  scheduledFor?: string;
  lastSubmittedHash?: string;
  requiresConfirmationBeforeSubmit: boolean;
  requiresConfirmationBeforeUpload: boolean;
  /** Set when the job is PAUSED waiting for the user to confirm the next step (upload/submit/continue). */
  pendingAction?: "UPLOAD" | "SUBMIT" | "CONTINUE";
  tabId?: number;
}

export const DEFAULT_RETRY_POLICY: RetryPolicy = {
  maxAttempts: 6,
  baseDelayMs: 30_000,
};

export const DEFAULT_NOTIFICATION_PREFERENCES: NotificationPreferences = {
  onWaiting: true,
  onResumed: true,
  onRequiresAction: true,
  onCompleted: true,
  onFailed: true,
};

export interface CreateJobInput {
  title: string;
  provider: string;
  conversationUrl: string;
  conversationId?: string;
  conversationTitle?: string;
  instructions: string;
  attachments?: AttachmentMeta[];
  executionMode?: ExecutionMode;
  priority?: JobPriority;
  retryPolicy?: Partial<RetryPolicy>;
  notificationPreferences?: Partial<NotificationPreferences>;
  scheduledFor?: string;
  requiresConfirmationBeforeSubmit?: boolean;
  requiresConfirmationBeforeUpload?: boolean;
  /** Explicit step checklist used for continuation/progress tracking. Defaults to a single generic step. */
  steps?: string[];
}

export function createJob(input: CreateJobInput): Job {
  const timestamp = nowIso();
  return {
    id: generateId("job"),
    title: input.title,
    provider: input.provider,
    conversationUrl: input.conversationUrl,
    conversationId: input.conversationId,
    conversationTitle: input.conversationTitle,
    instructions: input.instructions,
    attachments: input.attachments ?? [],
    executionMode: input.executionMode ?? ExecutionMode.SEMI_AUTOMATIC,
    status: JobStatus.DRAFT,
    priority: input.priority ?? JobPriority.NORMAL,
    createdAt: timestamp,
    updatedAt: timestamp,
    retryCount: 0,
    retryPolicy: { ...DEFAULT_RETRY_POLICY, ...input.retryPolicy },
    progress: {
      completedSteps: [],
      remainingSteps: input.steps && input.steps.length > 0 ? input.steps : ["Complete the task as described in the instructions."],
      continuationCount: 0,
    },
    history: [
      {
        id: generateId("evt"),
        timestamp,
        level: "INFO",
        code: "JOB_CREATED",
        message: `Job "${input.title}" created as a draft.`,
      },
    ],
    notificationPreferences: {
      ...DEFAULT_NOTIFICATION_PREFERENCES,
      ...input.notificationPreferences,
    },
    scheduledFor: input.scheduledFor,
    requiresConfirmationBeforeSubmit: input.requiresConfirmationBeforeSubmit ?? false,
    requiresConfirmationBeforeUpload: input.requiresConfirmationBeforeUpload ?? false,
  };
}

export const MAX_CONTINUATIONS = 25;
export const MAX_EXECUTION_TIME_MS = 6 * 60 * 60 * 1000; // 6 hours wall clock per job
