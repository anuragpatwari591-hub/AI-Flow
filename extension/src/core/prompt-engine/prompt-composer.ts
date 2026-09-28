import type { Job } from "@/core/jobs/job.model";
import type { Checkpoint } from "@/core/checkpoint/checkpoint.model";

/**
 * Builds the message that actually gets typed into the provider's compose
 * box. On the first submission there is no checkpoint yet, so the prompt is
 * just the user's task + attachments. On every subsequent submission the
 * prompt is a structured continuation that explicitly tells the model what
 * is already done, so it never restarts or duplicates work.
 */
export function composePrompt(job: Job, checkpoint?: Checkpoint): string {
  if (!checkpoint) {
    return composeInitialPrompt(job);
  }
  return composeContinuationPrompt(job, checkpoint);
}

function composeInitialPrompt(job: Job): string {
  const sections: string[] = [];
  sections.push(`CURRENT OBJECTIVE\n${job.instructions.trim()}`);
  if (job.attachments.length > 0) {
    sections.push(`ATTACHED FILES\n${job.attachments.map((a) => `- ${a.name} (${a.type || "unknown type"})`).join("\n")}`);
  }
  sections.push(
    "IMPORTANT CONSTRAINTS\n" +
      "- Work only from the objective and attached files above.\n" +
      "- If anything is ambiguous, state your assumption explicitly rather than guessing silently.",
  );
  sections.push("NEXT ACTION\nBegin the task described in CURRENT OBJECTIVE.");
  return sections.join("\n\n");
}

function composeContinuationPrompt(job: Job, checkpoint: Checkpoint): string {
  const sections: string[] = [];
  sections.push(`CURRENT OBJECTIVE\n${job.instructions.trim()}`);
  sections.push(`CURRENT STATE\n${checkpoint.executionSummary || "In progress."}`);
  sections.push(
    `COMPLETED WORK\n${
      checkpoint.completedTasks.length > 0
        ? checkpoint.completedTasks.map((t) => `- ${t}`).join("\n")
        : "- Nothing recorded yet."
    }`,
  );
  sections.push(
    `REMAINING WORK\n${
      checkpoint.remainingTasks.length > 0
        ? checkpoint.remainingTasks.map((t) => `- ${t}`).join("\n")
        : "- (none explicitly listed — use your judgement based on the objective)"
    }`,
  );
  if (job.attachments.length > 0) {
    sections.push(`ATTACHED FILES\n${job.attachments.map((a) => `- ${a.name} (${a.type || "unknown type"})`).join("\n")}`);
  }
  sections.push(
    "IMPORTANT CONSTRAINTS\n" +
      "- DO NOT DUPLICATE COMPLETED WORK.\n" +
      "- DO NOT START OVER UNLESS EXPLICITLY REQUESTED.\n" +
      "- Continue from CURRENT STATE using REMAINING WORK as your guide.",
  );
  sections.push(`NEXT ACTION\n${checkpoint.nextAction || "Continue with the next logical step of the remaining work."}`);
  sections.push(
    "VALIDATION REQUIREMENTS\n" +
      "- Briefly confirm what you completed in this step before moving on.\n" +
      "- Call out anything that could not be completed and why.",
  );
  return sections.join("\n\n");
}

/** A short, stable summary used for the loop-protection fingerprint — not the full prompt. */
export function summarizeForFingerprint(job: Job, checkpoint?: Checkpoint): string {
  return [job.id, job.provider, job.conversationUrl, checkpoint?.id ?? "initial", job.progress.continuationCount].join("|");
}
