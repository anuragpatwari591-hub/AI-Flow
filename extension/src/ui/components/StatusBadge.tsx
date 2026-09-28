import { JobStatus } from "@/core/jobs/job.model";

const VARIANTS: Record<string, string> = {
  [JobStatus.DRAFT]: "af-badge",
  [JobStatus.QUEUED]: "af-badge-primary",
  [JobStatus.WAITING_FOR_AVAILABILITY]: "af-badge-warning",
  [JobStatus.READY]: "af-badge-primary",
  [JobStatus.RUNNING]: "af-badge-primary",
  [JobStatus.UPLOADING]: "af-badge-primary",
  [JobStatus.SUBMITTING]: "af-badge-primary",
  [JobStatus.PROCESSING]: "af-badge-primary",
  [JobStatus.WAITING_FOR_RESPONSE]: "af-badge-primary",
  [JobStatus.CONTINUING]: "af-badge-primary",
  [JobStatus.COMPLETED]: "af-badge-success",
  [JobStatus.FAILED]: "af-badge-danger",
  [JobStatus.PAUSED]: "af-badge-warning",
  [JobStatus.CANCELLED]: "af-badge",
  [JobStatus.REQUIRES_USER_ACTION]: "af-badge-danger",
};

const LABELS: Record<string, string> = {
  [JobStatus.WAITING_FOR_AVAILABILITY]: "Waiting for availability",
  [JobStatus.REQUIRES_USER_ACTION]: "Needs your action",
  [JobStatus.WAITING_FOR_RESPONSE]: "Waiting for response",
};

export function StatusBadge({ status }: { status: string }) {
  const variant = VARIANTS[status] ?? "af-badge";
  const label = LABELS[status] ?? status.replace(/_/g, " ").toLowerCase();
  return <span className={`af-badge ${variant}`}>{label}</span>;
}
