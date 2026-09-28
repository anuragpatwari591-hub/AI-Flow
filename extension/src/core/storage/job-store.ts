import type { KeyValueStore } from "@/core/storage/kv-store";
import type { Job } from "@/core/jobs/job.model";

const INDEX_KEY = "aiflow:jobs:index";
const jobKey = (id: string) => `aiflow:job:${id}`;

/** Persists job metadata. Attachment file contents live in IndexedDB, never here. */
export class JobStore {
  constructor(private readonly kv: KeyValueStore) {}

  async list(): Promise<Job[]> {
    const ids = (await this.kv.get<string[]>(INDEX_KEY)) ?? [];
    const jobs = await Promise.all(ids.map((id) => this.kv.get<Job>(jobKey(id))));
    return jobs.filter((j): j is Job => Boolean(j));
  }

  async get(id: string): Promise<Job | undefined> {
    return this.kv.get<Job>(jobKey(id));
  }

  async save(job: Job): Promise<void> {
    await this.kv.set(jobKey(job.id), job);
    const ids = (await this.kv.get<string[]>(INDEX_KEY)) ?? [];
    if (!ids.includes(job.id)) {
      await this.kv.set(INDEX_KEY, [...ids, job.id]);
    }
  }

  async delete(id: string): Promise<void> {
    await this.kv.remove(jobKey(id));
    const ids = (await this.kv.get<string[]>(INDEX_KEY)) ?? [];
    await this.kv.set(
      INDEX_KEY,
      ids.filter((existing) => existing !== id),
    );
  }
}
