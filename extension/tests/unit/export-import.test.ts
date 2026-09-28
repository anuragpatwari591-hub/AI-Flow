import { describe, expect, it } from "vitest";
import { MemoryKvStore } from "@/core/storage/kv-store";
import { JobStore } from "@/core/storage/job-store";
import { CheckpointStore } from "@/core/checkpoint/checkpoint-store";
import { SettingsStore } from "@/core/storage/settings-store";
import { JobManager } from "@/core/jobs/job-manager";
import { createCheckpoint } from "@/core/checkpoint/checkpoint.model";
import { buildExportBundle, importExportBundle, exportEncrypted, importEncrypted, ImportValidationError } from "@/core/storage/export-import";

async function makeStores() {
  const kv = new MemoryKvStore();
  return { jobStore: new JobStore(kv), checkpoints: new CheckpointStore(kv), settings: new SettingsStore(kv) };
}

describe("export/import", () => {
  it("round-trips jobs, checkpoints, and settings through a plain JSON bundle", async () => {
    const source = await makeStores();
    const manager = new JobManager(source.jobStore);
    const job = await manager.create({ title: "Exportable", provider: "mock", conversationUrl: "u", instructions: "i" });
    await source.checkpoints.append(
      createCheckpoint({ jobId: job.id, state: "X", completedTasks: [], remainingTasks: [], provider: "mock", conversationUrl: "u", executionSummary: "", nextAction: "" }),
    );
    await source.settings.update({ maxRetries: 9 });

    const bundle = await buildExportBundle(source.jobStore, source.checkpoints, source.settings);
    expect(bundle.jobs).toHaveLength(1);
    expect(bundle.checkpoints).toHaveLength(1);
    expect(bundle.settings.maxRetries).toBe(9);

    const target = await makeStores();
    const result = await importExportBundle(bundle, target.jobStore, target.checkpoints, target.settings);
    expect(result.importedJobs).toBe(1);
    expect(await target.jobStore.get(job.id)).toEqual(job);
    expect(await target.settings.get()).toEqual(await source.settings.get());
  });

  it("rejects a bundle with the wrong format version", async () => {
    const target = await makeStores();
    await expect(
      importExportBundle({ formatVersion: 999, jobs: [], checkpoints: [] }, target.jobStore, target.checkpoints, target.settings),
    ).rejects.toBeInstanceOf(ImportValidationError);
  });

  it("supports an encrypted export/import round trip", async () => {
    const source = await makeStores();
    const manager = new JobManager(source.jobStore);
    await manager.create({ title: "Secret job", provider: "mock", conversationUrl: "u", instructions: "i" });
    const bundle = await buildExportBundle(source.jobStore, source.checkpoints, source.settings);

    const encrypted = await exportEncrypted(bundle, "correct horse battery staple");
    const target = await makeStores();
    const result = await importEncrypted(encrypted, "correct horse battery staple", target.jobStore, target.checkpoints, target.settings);
    expect(result.importedJobs).toBe(1);

    const wrongPassphrase = await makeStores();
    await expect(importEncrypted(encrypted, "wrong passphrase", wrongPassphrase.jobStore, wrongPassphrase.checkpoints, wrongPassphrase.settings)).rejects.toThrow();
  });
});
