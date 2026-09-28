import { describe, expect, it, vi } from "vitest";
import { FakeAlarmsPort } from "@/core/scheduler/alarms-port";
import { Scheduler, QUEUE_TICK_ALARM } from "@/core/scheduler/scheduler";

describe("Scheduler", () => {
  it("creates and fires a per-job alarm at the scheduled time", async () => {
    const alarms = new FakeAlarmsPort();
    const scheduler = new Scheduler(alarms);
    const fired: string[] = [];
    scheduler.onAlarm((parsed) => {
      if (parsed.type === "job") fired.push(parsed.jobId);
    });

    await scheduler.scheduleJobAfterDelay("job_1", 60_000);
    alarms.advanceBy(30_000);
    expect(fired).toEqual([]);
    alarms.advanceBy(30_001);
    expect(fired).toEqual(["job_1"]);
  });

  it("cancelJob removes a scheduled alarm before it fires", async () => {
    const alarms = new FakeAlarmsPort();
    const scheduler = new Scheduler(alarms);
    const fired = vi.fn();
    scheduler.onAlarm(fired);

    await scheduler.scheduleJobAfterDelay("job_1", 10_000);
    await scheduler.cancelJob("job_1");
    alarms.advanceBy(20_000);
    expect(fired).not.toHaveBeenCalled();
  });

  it("ensureQueueTick only creates the periodic alarm once", async () => {
    const alarms = new FakeAlarmsPort();
    const scheduler = new Scheduler(alarms);
    await scheduler.ensureQueueTick();
    await scheduler.ensureQueueTick();
    const all = await alarms.getAll();
    expect(all.filter((a) => a.name === QUEUE_TICK_ALARM)).toHaveLength(1);
  });

  it("listScheduledJobIds only reports job alarms, not the queue tick", async () => {
    const alarms = new FakeAlarmsPort();
    const scheduler = new Scheduler(alarms);
    await scheduler.ensureQueueTick();
    await scheduler.scheduleJobAfterDelay("job_a", 1000);
    await scheduler.scheduleJobAfterDelay("job_b", 2000);
    expect(new Set(await scheduler.listScheduledJobIds())).toEqual(new Set(["job_a", "job_b"]));
  });
});
