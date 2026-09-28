import { describe, expect, it } from "vitest";
import { MemoryKvStore } from "@/core/storage/kv-store";
import { CheckpointStore } from "@/core/checkpoint/checkpoint-store";
import { createCheckpoint } from "@/core/checkpoint/checkpoint.model";

describe("checkpoint store", () => {
  it("is append-only and returns checkpoints for a job in order", async () => {
    const store = new CheckpointStore(new MemoryKvStore());
    const jobId = "job_1";
    const first = createCheckpoint({
      jobId,
      state: "WAITING_FOR_RESPONSE",
      completedTasks: ["step 1"],
      remainingTasks: ["step 2"],
      provider: "mock",
      conversationUrl: "https://mock.aiflow.local/c/1",
      executionSummary: "did step 1",
      nextAction: "do step 2",
    });
    const second = createCheckpoint({
      jobId,
      state: "WAITING_FOR_RESPONSE",
      completedTasks: ["step 1", "step 2"],
      remainingTasks: [],
      provider: "mock",
      conversationUrl: "https://mock.aiflow.local/c/1",
      executionSummary: "did step 2",
      nextAction: "none",
    });

    await store.append(first);
    await store.append(second);

    const all = await store.listForJob(jobId);
    expect(all.map((c) => c.id)).toEqual([first.id, second.id]);
    expect(await store.latestForJob(jobId)).toEqual(second);
    expect(await store.get(first.id)).toEqual(first);
  });

  it("never mixes checkpoints between different jobs", async () => {
    const store = new CheckpointStore(new MemoryKvStore());
    await store.append(
      createCheckpoint({
        jobId: "job_a",
        state: "X",
        completedTasks: [],
        remainingTasks: [],
        provider: "mock",
        conversationUrl: "url",
        executionSummary: "",
        nextAction: "",
      }),
    );
    expect(await store.listForJob("job_b")).toEqual([]);
  });
});
