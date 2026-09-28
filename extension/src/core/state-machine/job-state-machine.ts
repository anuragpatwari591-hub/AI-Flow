import { JobStatus } from "@/core/jobs/job.model";

/**
 * All valid job status transitions, expressed as discrete events rather than
 * boolean flags scattered across the codebase. Anything not listed here is
 * an invalid transition and `transition()` will throw rather than silently
 * coercing the job into an unexpected state.
 */
export const JobEvent = {
  QUEUE: "QUEUE",
  CHECK_AVAILABILITY: "CHECK_AVAILABILITY",
  AVAILABILITY_CONFIRMED: "AVAILABILITY_CONFIRMED",
  AVAILABILITY_STILL_LIMITED: "AVAILABILITY_STILL_LIMITED",
  START_EXECUTION: "START_EXECUTION",
  BEGIN_UPLOAD: "BEGIN_UPLOAD",
  SKIP_UPLOAD: "SKIP_UPLOAD",
  UPLOAD_COMPLETE: "UPLOAD_COMPLETE",
  MESSAGE_SUBMITTED: "MESSAGE_SUBMITTED",
  ENTER_WAITING_FOR_RESPONSE: "ENTER_WAITING_FOR_RESPONSE",
  RECHECK_RESPONSE: "RECHECK_RESPONSE",
  RESPONSE_DONE: "RESPONSE_DONE",
  RESPONSE_CONTINUE: "RESPONSE_CONTINUE",
  RESPONSE_NEEDS_APPROVAL: "RESPONSE_NEEDS_APPROVAL",
  CONTINUE_WITH_UPLOAD: "CONTINUE_WITH_UPLOAD",
  CONTINUE_SKIP_UPLOAD: "CONTINUE_SKIP_UPLOAD",
  LIMIT_DETECTED: "LIMIT_DETECTED",
  AUTH_REQUIRED: "AUTH_REQUIRED",
  VERIFICATION_FAILED: "VERIFICATION_FAILED",
  ERROR: "ERROR",
  PAUSE: "PAUSE",
  RESUME: "RESUME",
  CANCEL: "CANCEL",
  RETRY: "RETRY",
  RESTART_FROM_CHECKPOINT: "RESTART_FROM_CHECKPOINT",
} as const;
export type JobEvent = (typeof JobEvent)[keyof typeof JobEvent];

interface TransitionRule {
  from: JobStatus[];
  event: JobEvent;
  to: JobStatus;
}

const ACTIVE_STATES: JobStatus[] = [
  JobStatus.QUEUED,
  JobStatus.WAITING_FOR_AVAILABILITY,
  JobStatus.READY,
  JobStatus.RUNNING,
  JobStatus.UPLOADING,
  JobStatus.SUBMITTING,
  JobStatus.PROCESSING,
  JobStatus.WAITING_FOR_RESPONSE,
  JobStatus.CONTINUING,
];

const ERRORABLE_STATES: JobStatus[] = [
  JobStatus.RUNNING,
  JobStatus.UPLOADING,
  JobStatus.SUBMITTING,
  JobStatus.PROCESSING,
  JobStatus.WAITING_FOR_RESPONSE,
  JobStatus.CONTINUING,
];

const TRANSITIONS: TransitionRule[] = [
  { from: [JobStatus.DRAFT], event: JobEvent.QUEUE, to: JobStatus.QUEUED },
  { from: [JobStatus.QUEUED], event: JobEvent.CHECK_AVAILABILITY, to: JobStatus.WAITING_FOR_AVAILABILITY },
  { from: [JobStatus.WAITING_FOR_AVAILABILITY], event: JobEvent.AVAILABILITY_CONFIRMED, to: JobStatus.READY },
  {
    from: [JobStatus.WAITING_FOR_AVAILABILITY],
    event: JobEvent.AVAILABILITY_STILL_LIMITED,
    to: JobStatus.WAITING_FOR_AVAILABILITY,
  },
  { from: [JobStatus.READY], event: JobEvent.START_EXECUTION, to: JobStatus.RUNNING },
  { from: [JobStatus.RUNNING], event: JobEvent.BEGIN_UPLOAD, to: JobStatus.UPLOADING },
  { from: [JobStatus.RUNNING], event: JobEvent.SKIP_UPLOAD, to: JobStatus.SUBMITTING },
  { from: [JobStatus.UPLOADING], event: JobEvent.UPLOAD_COMPLETE, to: JobStatus.SUBMITTING },
  { from: [JobStatus.SUBMITTING], event: JobEvent.MESSAGE_SUBMITTED, to: JobStatus.PROCESSING },
  { from: [JobStatus.PROCESSING], event: JobEvent.ENTER_WAITING_FOR_RESPONSE, to: JobStatus.WAITING_FOR_RESPONSE },
  {
    from: [JobStatus.WAITING_FOR_RESPONSE],
    event: JobEvent.RECHECK_RESPONSE,
    to: JobStatus.WAITING_FOR_RESPONSE,
  },
  { from: [JobStatus.WAITING_FOR_RESPONSE], event: JobEvent.RESPONSE_DONE, to: JobStatus.COMPLETED },
  { from: [JobStatus.WAITING_FOR_RESPONSE], event: JobEvent.RESPONSE_CONTINUE, to: JobStatus.CONTINUING },
  { from: [JobStatus.WAITING_FOR_RESPONSE], event: JobEvent.RESPONSE_NEEDS_APPROVAL, to: JobStatus.PAUSED },
  { from: [JobStatus.CONTINUING], event: JobEvent.CONTINUE_WITH_UPLOAD, to: JobStatus.UPLOADING },
  { from: [JobStatus.CONTINUING], event: JobEvent.CONTINUE_SKIP_UPLOAD, to: JobStatus.SUBMITTING },

  ...([JobStatus.READY, ...ERRORABLE_STATES] as JobStatus[]).map((from) => ({
    from: [from],
    event: JobEvent.LIMIT_DETECTED,
    to: JobStatus.WAITING_FOR_AVAILABILITY,
  })),
  ...([JobStatus.WAITING_FOR_AVAILABILITY, ...ERRORABLE_STATES] as JobStatus[]).map((from) => ({
    from: [from],
    event: JobEvent.AUTH_REQUIRED,
    to: JobStatus.REQUIRES_USER_ACTION,
  })),
  ...([JobStatus.WAITING_FOR_AVAILABILITY, ...ERRORABLE_STATES] as JobStatus[]).map((from) => ({
    from: [from],
    event: JobEvent.VERIFICATION_FAILED,
    to: JobStatus.REQUIRES_USER_ACTION,
  })),
  ...([JobStatus.WAITING_FOR_AVAILABILITY, ...ERRORABLE_STATES] as JobStatus[]).map((from) => ({
    from: [from],
    event: JobEvent.ERROR,
    to: JobStatus.FAILED,
  })),
  ...ACTIVE_STATES.map((from) => ({
    from: [from],
    event: JobEvent.PAUSE,
    to: JobStatus.PAUSED,
  })),
  ...ACTIVE_STATES.map((from) => ({
    from: [from],
    event: JobEvent.CANCEL,
    to: JobStatus.CANCELLED,
  })),

  { from: [JobStatus.PAUSED], event: JobEvent.RESUME, to: JobStatus.QUEUED },
  { from: [JobStatus.PAUSED], event: JobEvent.CANCEL, to: JobStatus.CANCELLED },
  { from: [JobStatus.FAILED], event: JobEvent.RETRY, to: JobStatus.QUEUED },
  { from: [JobStatus.REQUIRES_USER_ACTION], event: JobEvent.RETRY, to: JobStatus.QUEUED },
  {
    from: [JobStatus.FAILED, JobStatus.REQUIRES_USER_ACTION, JobStatus.PAUSED, JobStatus.COMPLETED],
    event: JobEvent.RESTART_FROM_CHECKPOINT,
    to: JobStatus.QUEUED,
  },
];

function buildLookup() {
  const map = new Map<string, JobStatus>();
  for (const rule of TRANSITIONS) {
    for (const from of rule.from) {
      map.set(`${from}::${rule.event}`, rule.to);
    }
  }
  return map;
}

const LOOKUP = buildLookup();

export class InvalidTransitionError extends Error {
  constructor(
    public readonly from: JobStatus,
    public readonly event: JobEvent,
  ) {
    super(`Invalid job transition: cannot apply "${event}" while status is "${from}".`);
    this.name = "InvalidTransitionError";
  }
}

export function canTransition(from: JobStatus, event: JobEvent): boolean {
  return LOOKUP.has(`${from}::${event}`);
}

export function nextStatus(from: JobStatus, event: JobEvent): JobStatus {
  const to = LOOKUP.get(`${from}::${event}`);
  if (!to) throw new InvalidTransitionError(from, event);
  return to;
}

export const TERMINAL_STATES: JobStatus[] = [JobStatus.COMPLETED, JobStatus.CANCELLED];

export function isTerminal(status: JobStatus): boolean {
  return TERMINAL_STATES.includes(status);
}
