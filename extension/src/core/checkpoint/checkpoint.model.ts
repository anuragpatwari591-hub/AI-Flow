import { generateId } from "@/utils/id";
import { nowIso } from "@/utils/time";

export interface Checkpoint {
  id: string;
  jobId: string;
  timestamp: string;
  /** Job status at the moment this checkpoint was captured. */
  state: string;
  completedTasks: string[];
  remainingTasks: string[];
  provider: string;
  conversationUrl: string;
  executionSummary: string;
  nextAction: string;
}

export interface CreateCheckpointInput {
  jobId: string;
  state: string;
  completedTasks: string[];
  remainingTasks: string[];
  provider: string;
  conversationUrl: string;
  executionSummary: string;
  nextAction: string;
}

export function createCheckpoint(input: CreateCheckpointInput): Checkpoint {
  return {
    id: generateId("chk"),
    timestamp: nowIso(),
    ...input,
  };
}
