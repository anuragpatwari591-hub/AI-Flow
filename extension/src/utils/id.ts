/** Generates a random, collision-resistant identifier for jobs, checkpoints, attachments, etc. */
export function generateId(prefix?: string): string {
  const uuid = crypto.randomUUID();
  return prefix ? `${prefix}_${uuid}` : uuid;
}
