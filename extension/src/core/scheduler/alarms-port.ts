/**
 * Thin abstraction over chrome.alarms so the scheduler can be unit tested
 * with a fake clock instead of a real browser.
 */
export interface AlarmInfo {
  name: string;
  scheduledTime: number;
}

export interface AlarmsPort {
  create(name: string, options: { when?: number; delayInMinutes?: number }): Promise<void>;
  clear(name: string): Promise<boolean>;
  getAll(): Promise<AlarmInfo[]>;
  onAlarm(listener: (alarm: AlarmInfo) => void): void;
}

export class ChromeAlarmsPort implements AlarmsPort {
  async create(name: string, options: { when?: number; delayInMinutes?: number }): Promise<void> {
    await chrome.alarms.create(name, options);
  }

  async clear(name: string): Promise<boolean> {
    return chrome.alarms.clear(name);
  }

  async getAll(): Promise<AlarmInfo[]> {
    const alarms = await chrome.alarms.getAll();
    return alarms.map((a) => ({ name: a.name, scheduledTime: a.scheduledTime }));
  }

  onAlarm(listener: (alarm: AlarmInfo) => void): void {
    chrome.alarms.onAlarm.addListener((alarm) => listener({ name: alarm.name, scheduledTime: alarm.scheduledTime }));
  }
}

/** In-memory alarms port for tests. `advanceTo`/`advanceBy` fire due alarms synchronously. */
export class FakeAlarmsPort implements AlarmsPort {
  private alarms = new Map<string, AlarmInfo>();
  private listeners: Array<(alarm: AlarmInfo) => void> = [];
  /** Seeded from the real clock so alarms created via `{ when: Date.now() + delay }` (as Scheduler does) compare correctly against it. */
  public now = Date.now();

  async create(name: string, options: { when?: number; delayInMinutes?: number }): Promise<void> {
    const when = options.when ?? this.now + (options.delayInMinutes ?? 0) * 60_000;
    this.alarms.set(name, { name, scheduledTime: when });
  }

  async clear(name: string): Promise<boolean> {
    return this.alarms.delete(name);
  }

  async getAll(): Promise<AlarmInfo[]> {
    return Array.from(this.alarms.values());
  }

  onAlarm(listener: (alarm: AlarmInfo) => void): void {
    this.listeners.push(listener);
  }

  advanceTo(timestamp: number): void {
    this.now = timestamp;
    const due = Array.from(this.alarms.values()).filter((a) => a.scheduledTime <= this.now);
    for (const alarm of due) {
      this.alarms.delete(alarm.name);
      for (const listener of this.listeners) listener(alarm);
    }
  }

  advanceBy(ms: number): void {
    this.advanceTo(this.now + ms);
  }
}
