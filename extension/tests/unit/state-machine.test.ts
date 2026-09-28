import { describe, expect, it } from "vitest";
import { JobStatus } from "@/core/jobs/job.model";
import { JobEvent, canTransition, nextStatus, InvalidTransitionError, isTerminal } from "@/core/state-machine/job-state-machine";

describe("job state machine", () => {
  it("walks the happy path from DRAFT to COMPLETED", () => {
    let status: JobStatus = JobStatus.DRAFT;
    const path: Array<[JobStatus, ReturnType<typeof String>]> = [];
    const steps: Array<typeof JobEvent[keyof typeof JobEvent]> = [
      JobEvent.QUEUE,
      JobEvent.CHECK_AVAILABILITY,
      JobEvent.AVAILABILITY_CONFIRMED,
      JobEvent.START_EXECUTION,
      JobEvent.SKIP_UPLOAD,
      JobEvent.MESSAGE_SUBMITTED,
      JobEvent.ENTER_WAITING_FOR_RESPONSE,
      JobEvent.RESPONSE_DONE,
    ];
    for (const event of steps) {
      path.push([status, event]);
      status = nextStatus(status, event);
    }
    expect(status).toBe(JobStatus.COMPLETED);
    expect(isTerminal(status)).toBe(true);
  });

  it("rejects invalid transitions instead of silently coercing state", () => {
    expect(() => nextStatus(JobStatus.DRAFT, JobEvent.MESSAGE_SUBMITTED)).toThrow(InvalidTransitionError);
    expect(canTransition(JobStatus.DRAFT, JobEvent.MESSAGE_SUBMITTED)).toBe(false);
  });

  it("allows pausing from any active state and resuming back into the queue", () => {
    expect(nextStatus(JobStatus.WAITING_FOR_RESPONSE, JobEvent.PAUSE)).toBe(JobStatus.PAUSED);
    expect(nextStatus(JobStatus.PAUSED, JobEvent.RESUME)).toBe(JobStatus.QUEUED);
  });

  it("routes limit/auth/verification failures into the correct terminal-ish states", () => {
    expect(nextStatus(JobStatus.SUBMITTING, JobEvent.LIMIT_DETECTED)).toBe(JobStatus.WAITING_FOR_AVAILABILITY);
    expect(nextStatus(JobStatus.SUBMITTING, JobEvent.AUTH_REQUIRED)).toBe(JobStatus.REQUIRES_USER_ACTION);
    expect(nextStatus(JobStatus.RUNNING, JobEvent.VERIFICATION_FAILED)).toBe(JobStatus.REQUIRES_USER_ACTION);
    expect(nextStatus(JobStatus.PROCESSING, JobEvent.ERROR)).toBe(JobStatus.FAILED);
  });

  it("never allows a transition out of COMPLETED or CANCELLED", () => {
    expect(canTransition(JobStatus.COMPLETED, JobEvent.QUEUE)).toBe(false);
    expect(canTransition(JobStatus.CANCELLED, JobEvent.RESUME)).toBe(false);
    // COMPLETED can only be re-entered via an explicit restart-from-checkpoint.
    expect(nextStatus(JobStatus.COMPLETED, JobEvent.RESTART_FROM_CHECKPOINT)).toBe(JobStatus.QUEUED);
  });

  it("supports retrying a failed or blocked job back into the queue", () => {
    expect(nextStatus(JobStatus.FAILED, JobEvent.RETRY)).toBe(JobStatus.QUEUED);
    expect(nextStatus(JobStatus.REQUIRES_USER_ACTION, JobEvent.RETRY)).toBe(JobStatus.QUEUED);
  });
});
