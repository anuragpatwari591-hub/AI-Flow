import type { JobStore } from "@/core/storage/job-store";
import type { CheckpointStore } from "@/core/checkpoint/checkpoint-store";
import type { SettingsStore, Settings } from "@/core/storage/settings-store";
import type { Job } from "@/core/jobs/job.model";
import type { Checkpoint } from "@/core/checkpoint/checkpoint.model";
import { encryptJson, decryptJson, type EncryptedPayload } from "@/security/encryption/encryption";

export const EXPORT_FORMAT_VERSION = 1;

export interface ExportBundle {
  formatVersion: number;
  exportedAt: string;
  jobs: Job[];
  checkpoints: Checkpoint[];
  settings: Settings;
}

export class ImportValidationError extends Error {}

export async function buildExportBundle(
  jobStore: JobStore,
  checkpointStore: CheckpointStore,
  settingsStore: SettingsStore,
): Promise<ExportBundle> {
  const jobs = await jobStore.list();
  const checkpoints = (await Promise.all(jobs.map((j) => checkpointStore.listForJob(j.id)))).flat();
  const settings = await settingsStore.get();
  return {
    formatVersion: EXPORT_FORMAT_VERSION,
    exportedAt: new Date().toISOString(),
    jobs,
    checkpoints,
    settings,
  };
}

function validateBundle(value: unknown): ExportBundle {
  if (!value || typeof value !== "object") throw new ImportValidationError("Backup file is not valid JSON.");
  const bundle = value as Partial<ExportBundle>;
  if (bundle.formatVersion !== EXPORT_FORMAT_VERSION) {
    throw new ImportValidationError(`Unsupported backup format version: ${String(bundle.formatVersion)}`);
  }
  if (!Array.isArray(bundle.jobs) || !Array.isArray(bundle.checkpoints)) {
    throw new ImportValidationError("Backup file is missing jobs or checkpoints.");
  }
  return bundle as ExportBundle;
}

export async function importExportBundle(
  raw: unknown,
  jobStore: JobStore,
  checkpointStore: CheckpointStore,
  settingsStore: SettingsStore,
): Promise<{ importedJobs: number; importedCheckpoints: number }> {
  const bundle = validateBundle(raw);
  for (const job of bundle.jobs) await jobStore.save(job);
  for (const checkpoint of bundle.checkpoints) await checkpointStore.append(checkpoint);
  if (bundle.settings) await settingsStore.update(bundle.settings);
  return { importedJobs: bundle.jobs.length, importedCheckpoints: bundle.checkpoints.length };
}

export async function exportEncrypted(bundle: ExportBundle, passphrase: string): Promise<EncryptedPayload> {
  return encryptJson(bundle, passphrase);
}

export async function importEncrypted(
  payload: EncryptedPayload,
  passphrase: string,
  jobStore: JobStore,
  checkpointStore: CheckpointStore,
  settingsStore: SettingsStore,
): Promise<{ importedJobs: number; importedCheckpoints: number }> {
  const bundle = await decryptJson<ExportBundle>(payload, passphrase);
  return importExportBundle(bundle, jobStore, checkpointStore, settingsStore);
}
