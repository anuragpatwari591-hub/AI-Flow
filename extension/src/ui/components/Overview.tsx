import type { Job } from "@/core/jobs/job.model";
import { JobStatus } from "@/core/jobs/job.model";
import { JobList } from "@/ui/components/JobList";

const ACTIVE_STATUSES = new Set([
  JobStatus.READY,
  JobStatus.RUNNING,
  JobStatus.UPLOADING,
  JobStatus.SUBMITTING,
  JobStatus.PROCESSING,
  JobStatus.WAITING_FOR_RESPONSE,
  JobStatus.CONTINUING,
]);

function Stat({ label, value, tone }: { label: string; value: number; tone?: string }) {
  return (
    <div className="af-card" style={{ padding: 14, flex: 1, minWidth: 100 }}>
      <div style={{ fontSize: 24, fontWeight: 700, color: tone }}>{value}</div>
      <div className="af-muted" style={{ fontSize: 12 }}>
        {label}
      </div>
    </div>
  );
}

export function Overview({ jobs, onSelect, onCreate }: { jobs: Job[]; onSelect: (id: string) => void; onCreate: () => void }) {
  const active = jobs.filter((j) => ACTIVE_STATUSES.has(j.status as never));
  const queued = jobs.filter((j) => j.status === JobStatus.QUEUED);
  const waiting = jobs.filter((j) => j.status === JobStatus.WAITING_FOR_AVAILABILITY);
  const completed = jobs.filter((j) => j.status === JobStatus.COMPLETED);
  const failed = jobs.filter((j) => j.status === JobStatus.FAILED);
  const needsAttention = jobs.filter((j) => j.status === JobStatus.REQUIRES_USER_ACTION || (j.status === JobStatus.PAUSED && j.pendingAction));

  return (
    <div className="af-stack">
      <div className="af-row-between">
        <h2 style={{ margin: 0, fontSize: 16 }}>Overview</h2>
        <button className="af-btn af-btn-primary" onClick={onCreate}>
          + New job
        </button>
      </div>
      <div className="af-row" style={{ flexWrap: "wrap" }}>
        <Stat label="Active" value={active.length} tone="var(--af-primary)" />
        <Stat label="Queued" value={queued.length} />
        <Stat label="Waiting" value={waiting.length} tone="var(--af-warning)" />
        <Stat label="Completed" value={completed.length} tone="var(--af-success)" />
        <Stat label="Failed" value={failed.length} tone="var(--af-danger)" />
      </div>

      {needsAttention.length > 0 && (
        <div>
          <h3 style={{ fontSize: 13, marginBottom: 8 }}>Needs your attention</h3>
          <JobList jobs={needsAttention} onSelect={onSelect} emptyMessage="Nothing needs attention." />
        </div>
      )}

      <div>
        <h3 style={{ fontSize: 13, marginBottom: 8 }}>Recently updated</h3>
        <JobList jobs={jobs.slice(0, 6)} onSelect={onSelect} emptyMessage="No jobs yet. Create your first job to get started." />
      </div>
    </div>
  );
}
