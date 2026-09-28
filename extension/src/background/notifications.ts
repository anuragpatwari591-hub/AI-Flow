import type { JobRunnerEvent } from "@/core/jobs/job-runner";

const TITLES: Record<JobRunnerEvent["type"], string> = {
  waiting: "AI Flow is waiting",
  resumed: "AI Flow resumed",
  requiresAction: "AI Flow needs your attention",
  completed: "Job completed",
  failed: "Job failed",
};

function messageFor(event: JobRunnerEvent): string {
  switch (event.type) {
    case "waiting":
      return `Waiting for provider availability for "${event.job.title}".`;
    case "resumed":
      return `AI Flow resumed "${event.job.title}".`;
    case "requiresAction":
      return `"${event.job.title}" requires your attention: ${event.job.lastError?.message ?? "action required."}`;
    case "completed":
      return `"${event.job.title}" completed.`;
    case "failed":
      return `"${event.job.title}" failed: ${event.job.lastError?.message ?? "unknown error."}`;
  }
}

/** Simple in-memory de-dupe so a burst of identical events (e.g. two rapid ticks) never produces duplicate OS notifications. */
const recentlyNotified = new Map<string, number>();
const DEDUPE_WINDOW_MS = 15_000;

export function notifyForEvent(event: JobRunnerEvent): void {
  const key = `${event.job.id}:${event.type}`;
  const now = Date.now();
  const last = recentlyNotified.get(key);
  if (last && now - last < DEDUPE_WINDOW_MS) return;
  recentlyNotified.set(key, now);

  chrome.notifications.create(`aiflow:${key}:${now}`, {
    type: "basic",
    iconUrl: "assets/icons/icon-128.png",
    title: TITLES[event.type],
    message: messageFor(event),
    priority: event.type === "requiresAction" || event.type === "failed" ? 2 : 0,
  });
}
