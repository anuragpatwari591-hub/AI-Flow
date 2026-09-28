import type { KeyValueStore } from "@/core/storage/kv-store";
import type { Checkpoint } from "@/core/checkpoint/checkpoint.model";

const indexKey = (jobId: string) => `aiflow:checkpoints:index:${jobId}`;
const checkpointKey = (id: string) => `aiflow:checkpoint:${id}`;

/**
 * Append-only checkpoint log. Checkpoints are never deleted or overwritten
 * by the system — only the user can explicitly clear a job's history, and
 * even then via an explicit destructive action, never automatically.
 */
export class CheckpointStore {
  constructor(private readonly kv: KeyValueStore) {}

  async listForJob(jobId: string): Promise<Checkpoint[]> {
    const ids = (await this.kv.get<string[]>(indexKey(jobId))) ?? [];
    const checkpoints = await Promise.all(ids.map((id) => this.kv.get<Checkpoint>(checkpointKey(id))));
    return checkpoints.filter((c): c is Checkpoint => Boolean(c));
  }

  async get(id: string): Promise<Checkpoint | undefined> {
    return this.kv.get<Checkpoint>(checkpointKey(id));
  }

  async latestForJob(jobId: string): Promise<Checkpoint | undefined> {
    const checkpoints = await this.listForJob(jobId);
    return checkpoints[checkpoints.length - 1];
  }

  async append(checkpoint: Checkpoint): Promise<void> {
    await this.kv.set(checkpointKey(checkpoint.id), checkpoint);
    const ids = (await this.kv.get<string[]>(indexKey(checkpoint.jobId))) ?? [];
    await this.kv.set(indexKey(checkpoint.jobId), [...ids, checkpoint.id]);
  }
}
