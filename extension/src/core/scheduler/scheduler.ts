import type { AlarmsPort } from "@/core/scheduler/alarms-port";

export const QUEUE_TICK_ALARM = "aiflow:queue-tick";
const JOB_ALARM_PREFIX = "aiflow:job:";
const QUEUE_TICK_INTERVAL_MINUTES = 1;

export type ParsedAlarm = { type: "job"; jobId: string } | { type: "queue-tick" } | { type: "unknown" };

export function parseAlarmName(name: string): ParsedAlarm {
  if (name === QUEUE_TICK_ALARM) return { type: "queue-tick" };
  if (name.startsWith(JOB_ALARM_PREFIX)) return { type: "job", jobId: name.slice(JOB_ALARM_PREFIX.length) };
  return { type: "unknown" };
}

function jobAlarmName(jobId: string): string {
  return `${JOB_ALARM_PREFIX}${jobId}`;
}

/**
 * Schedules per-job wake-ups plus a periodic queue-processing tick that
 * reconciles state even if a precise per-job alarm was lost (e.g. across a
 * browser restart). Every method here is a thin, testable wrapper around
 * the injected AlarmsPort — no chrome.* calls happen anywhere else.
 */
export class Scheduler {
  constructor(private readonly alarms: AlarmsPort) {}

  async scheduleJobAt(jobId: string, whenMs: number): Promise<void> {
    await this.alarms.create(jobAlarmName(jobId), { when: whenMs });
  }

  async scheduleJobAfterDelay(jobId: string, delayMs: number): Promise<void> {
    await this.scheduleJobAt(jobId, Date.now() + Math.max(0, delayMs));
  }

  async cancelJob(jobId: string): Promise<void> {
    await this.alarms.clear(jobAlarmName(jobId));
  }

  async ensureQueueTick(): Promise<void> {
    const alarms = await this.alarms.getAll();
    const exists = alarms.some((a) => a.name === QUEUE_TICK_ALARM);
    if (!exists) {
      await this.alarms.create(QUEUE_TICK_ALARM, { delayInMinutes: QUEUE_TICK_INTERVAL_MINUTES });
    }
  }

  async listScheduledJobIds(): Promise<string[]> {
    const alarms = await this.alarms.getAll();
    return alarms
      .map((a) => parseAlarmName(a.name))
      .filter((parsed): parsed is { type: "job"; jobId: string } => parsed.type === "job")
      .map((parsed) => parsed.jobId);
  }

  onAlarm(listener: (parsed: ParsedAlarm) => void): void {
    this.alarms.onAlarm((alarm) => listener(parseAlarmName(alarm.name)));
  }
}
