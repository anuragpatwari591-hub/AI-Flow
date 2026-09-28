import { describe, expect, it } from "vitest";
import { validateFile, formatBytes, MAX_ATTACHMENT_BYTES } from "@/utils/file-utils";

describe("file-utils", () => {
  it("accepts a known-good PDF", () => {
    expect(validateFile({ name: "requirements.pdf", size: 1024, type: "application/pdf" }).valid).toBe(true);
  });

  it("accepts source files by extension even with a generic/empty mime type", () => {
    expect(validateFile({ name: "main.ts", size: 100, type: "" }).valid).toBe(true);
  });

  it("rejects empty/corrupted files", () => {
    const result = validateFile({ name: "a.pdf", size: 0, type: "application/pdf" });
    expect(result.valid).toBe(false);
  });

  it("rejects files over the per-file size limit", () => {
    const result = validateFile({ name: "big.zip", size: MAX_ATTACHMENT_BYTES + 1, type: "application/zip" });
    expect(result.valid).toBe(false);
  });

  it("rejects unsupported types", () => {
    const result = validateFile({ name: "virus.exe", size: 10, type: "application/x-msdownload" });
    expect(result.valid).toBe(false);
  });

  it("formats byte counts for display", () => {
    expect(formatBytes(0)).toBe("0 B");
    expect(formatBytes(1024)).toBe("1.0 KB");
    expect(formatBytes(1_500_000)).toContain("MB");
  });
});
