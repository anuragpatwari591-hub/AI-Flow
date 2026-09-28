import type { Job } from "@/core/jobs/job.model";
import { StatusBadge } from "@/ui/components/StatusBadge";
import { formatRelativeToNow } from "@/utils/time";

export function JobCard({ job, onSelect }: { job: Job; onSelect: (id: string) => void }) {
  const totalSteps = job.progress.completedSteps.length + job.progress.remainingSteps.length;
  const doneSteps = job.progress.completedSteps.length;
  return (
    <button
      className="af-card"
      style={{ width: "100%", textAlign: "left", padding: 12, cursor: "pointer", border: "1px solid var(--af-border)" }}
      onClick={() => onSelect(job.id)}
    >
      <div className="af-row-between">
        <strong style={{ fontSize: 13 }}>{job.title}</strong>
        <StatusBadge status={job.status} />
      </div>
      <div className="af-row af-muted" style={{ fontSize: 12, marginTop: 6, flexWrap: "wrap" }}>
        <span>{job.provider}</span>
        <span>&middot;</span>
        <span>{job.executionMode}</span>
        {totalSteps > 0 && (
          <>
            <span>&middot;</span>
            <span>
              {doneSteps}/{totalSteps} steps
            </span>
          </>
        )}
        {job.attachments.length > 0 && (
          <>
            <span>&middot;</span>
            <span>{job.attachments.length} file(s)</span>
          </>
        )}
      </div>
      <div className="af-row af-muted" style={{ fontSize: 11, marginTop: 4 }}>
        <span>Updated {formatRelativeToNow(job.updatedAt) === "now" ? "just now" : new Date(job.updatedAt).toLocaleString()}</span>
        {job.nextAttemptAt && <span>&middot; Next attempt {formatRelativeToNow(job.nextAttemptAt)}</span>}
      </div>
    </button>
  );
}
