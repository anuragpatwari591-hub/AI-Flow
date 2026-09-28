import type { KeyValueStore } from "@/core/storage/kv-store";
import { ExecutionMode } from "@/core/jobs/job.model";

const SETTINGS_KEY = "aiflow:settings";

export interface Settings {
  defaultProvider: string;
  defaultExecutionMode: ExecutionMode;
  maxRetries: number;
  retryStrategyJitter: boolean;
  notifyOnWaiting: boolean;
  notifyOnResumed: boolean;
  notifyOnRequiresAction: boolean;
  notifyOnCompleted: boolean;
  notifyOnFailed: boolean;
  maxContinuations: number;
  confirmBeforeSubmission: boolean;
  confirmBeforeUpload: boolean;
  debugLogging: boolean;
  theme: "system" | "light" | "dark";
  reducedMotion: boolean;
}

export const DEFAULT_SETTINGS: Settings = {
  defaultProvider: "mock",
  defaultExecutionMode: ExecutionMode.SEMI_AUTOMATIC,
  maxRetries: 6,
  retryStrategyJitter: true,
  notifyOnWaiting: true,
  notifyOnResumed: true,
  notifyOnRequiresAction: true,
  notifyOnCompleted: true,
  notifyOnFailed: true,
  maxContinuations: 25,
  confirmBeforeSubmission: false,
  confirmBeforeUpload: false,
  debugLogging: false,
  theme: "system",
  reducedMotion: false,
};

export class SettingsStore {
  constructor(private readonly kv: KeyValueStore) {}

  async get(): Promise<Settings> {
    const stored = await this.kv.get<Settings>(SETTINGS_KEY);
    return { ...DEFAULT_SETTINGS, ...stored };
  }

  async update(patch: Partial<Settings>): Promise<Settings> {
    const current = await this.get();
    const next = { ...current, ...patch };
    await this.kv.set(SETTINGS_KEY, next);
    return next;
  }

  async reset(): Promise<Settings> {
    await this.kv.set(SETTINGS_KEY, DEFAULT_SETTINGS);
    return DEFAULT_SETTINGS;
  }
}
