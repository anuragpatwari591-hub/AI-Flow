import { generateId } from "@/utils/id";
import { nowIso } from "@/utils/time";
import type { JobHistoryEntry } from "@/core/jobs/job.model";

// Best-effort redaction. Logging must never contain secrets, so any text
// resembling a credential, token, or bearer header is masked before a log
// entry is created — defense in depth on top of "never collect these in
// the first place".
const SECRET_PATTERNS: RegExp[] = [
  /bearer\s+[a-z0-9._-]{10,}/gi,
  /sk-[a-z0-9]{16,}/gi,
  /(api[_-]?key|token|password|secret)\s*[:=]\s*\S+/gi,
];

export function sanitizeForLog(message: string): string {
  let sanitized = message;
  for (const pattern of SECRET_PATTERNS) {
    sanitized = sanitized.replace(pattern, "[redacted]");
  }
  return sanitized;
}

export function createLogEntry(
  level: JobHistoryEntry["level"],
  code: string,
  message: string,
): JobHistoryEntry {
  return {
    id: generateId("evt"),
    timestamp: nowIso(),
    level,
    code,
    message: sanitizeForLog(message),
  };
}
