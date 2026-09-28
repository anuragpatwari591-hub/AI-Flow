import { describe, expect, it } from "vitest";
import { composePrompt } from "@/core/prompt-engine/prompt-composer";
import { createJob } from "@/core/jobs/job.model";
import { createCheckpoint } from "@/core/checkpoint/checkpoint.model";

describe("prompt composer", () => {
  const job = createJob({
    title: "Build my B.Tech project",
    provider: "mock",
    conversationUrl: "https://mock.aiflow.local/c/1",
    instructions: "Build a full-stack app with a login page and a dashboard.",
    steps: ["Design the schema", "Build the backend", "Build the frontend"],
  });

  it("builds a plain initial prompt with no checkpoint", () => {
    const prompt = composePrompt(job);
    expect(prompt).toContain("CURRENT OBJECTIVE");
    expect(prompt).toContain("Build a full-stack app");
    expect(prompt).not.toContain("DO NOT DUPLICATE");
  });

  it("builds a structured continuation prompt that tells the model what's already done", () => {
    const checkpoint = createCheckpoint({
      jobId: job.id,
      state: "WAITING_FOR_RESPONSE",
      completedTasks: ["Design the schema"],
      remainingTasks: ["Build the backend", "Build the frontend"],
      provider: "mock",
      conversationUrl: job.conversationUrl,
      executionSummary: "Schema designed with users and projects tables.",
      nextAction: "Build the backend",
    });
    const prompt = composePrompt(job, checkpoint);
    expect(prompt).toContain("COMPLETED WORK");
    expect(prompt).toContain("Design the schema");
    expect(prompt).toContain("REMAINING WORK");
    expect(prompt).toContain("Build the backend");
    expect(prompt).toContain("DO NOT DUPLICATE COMPLETED WORK");
    expect(prompt).toContain("DO NOT START OVER UNLESS EXPLICITLY REQUESTED");
    expect(prompt).toContain("VALIDATION REQUIREMENTS");
  });

  it("includes attached files in the prompt when present", () => {
    const jobWithFiles = createJob({
      title: job.title,
      provider: job.provider,
      conversationUrl: job.conversationUrl,
      instructions: job.instructions,
      attachments: [
        { id: "a1", name: "requirements.pdf", size: 100, type: "application/pdf", checksum: "x", addedAt: "now", status: "UPLOADED" },
      ],
    });
    expect(composePrompt(jobWithFiles)).toContain("requirements.pdf");
  });
});
