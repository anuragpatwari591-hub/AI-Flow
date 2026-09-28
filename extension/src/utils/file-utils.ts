export const ALLOWED_MIME_TYPES: Record<string, string[]> = {
  "application/pdf": [".pdf"],
  "application/vnd.openxmlformats-officedocument.wordprocessingml.document": [".docx"],
  "text/plain": [".txt", ".md", ".log"],
  "text/csv": [".csv"],
  "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": [".xlsx"],
  "image/png": [".png"],
  "image/jpeg": [".jpg", ".jpeg"],
  "image/webp": [".webp"],
  "application/zip": [".zip"],
  "application/x-zip-compressed": [".zip"],
  "text/x-python": [".py"],
  "text/javascript": [".js"],
  "application/typescript": [".ts"],
  "text/x-java": [".java"],
  "text/x-c": [".c"],
  "text/x-c++": [".cpp"],
  "application/sql": [".sql"],
  "application/json": [".json"],
};

// Extension-based fallback allowlist, since browsers report inconsistent
// MIME types for source files (e.g. ".ts" is often reported as empty).
export const ALLOWED_EXTENSIONS = new Set(
  Object.values(ALLOWED_MIME_TYPES).flat().concat([".tsx", ".jsx", ".yml", ".yaml", ".html", ".css"]),
);

export const MAX_ATTACHMENT_BYTES = 25 * 1024 * 1024; // 25 MB per file
export const MAX_TOTAL_ATTACHMENT_BYTES = 100 * 1024 * 1024; // 100 MB per job

export interface FileValidationResult {
  valid: boolean;
  reason?: string;
}

export function getExtension(filename: string): string {
  const idx = filename.lastIndexOf(".");
  return idx === -1 ? "" : filename.slice(idx).toLowerCase();
}

export function validateFile(file: { name: string; size: number; type: string }): FileValidationResult {
  if (file.size <= 0) {
    return { valid: false, reason: "File appears to be empty or corrupted." };
  }
  if (file.size > MAX_ATTACHMENT_BYTES) {
    return { valid: false, reason: `File exceeds the ${formatBytes(MAX_ATTACHMENT_BYTES)} per-file limit.` };
  }
  const ext = getExtension(file.name);
  const mimeKnown = Boolean(ALLOWED_MIME_TYPES[file.type]);
  const extKnown = ALLOWED_EXTENSIONS.has(ext);
  if (!mimeKnown && !extKnown) {
    return { valid: false, reason: `Unsupported file type: ${file.type || ext || "unknown"}.` };
  }
  return { valid: true };
}

export function formatBytes(bytes: number): string {
  if (bytes === 0) return "0 B";
  const units = ["B", "KB", "MB", "GB"];
  const i = Math.min(units.length - 1, Math.floor(Math.log(bytes) / Math.log(1024)));
  return `${(bytes / Math.pow(1024, i)).toFixed(i === 0 ? 0 : 1)} ${units[i]}`;
}
