import { useJobs } from "@/ui/hooks/useJobs";
import { JobStatus, type Job } from "@/core/jobs/job.model";

const ACTIVE_STATUSES: Job["status"][] = [
  JobStatus.READY,
  JobStatus.RUNNING,
  JobStatus.UPLOADING,
  JobStatus.SUBMITTING,
  JobStatus.PROCESSING,
  JobStatus.WAITING_FOR_RESPONSE,
  JobStatus.CONTINUING,
];

async function openSidePanel() {
  const window = await chrome.windows.getCurrent();
  if (window.id !== undefined) {
    await chrome.sidePanel.open({ windowId: window.id });
  }
}

export function App() {
  const { jobs, loading } = useJobs();
  const active = jobs.filter((j) => ACTIVE_STATUSES.includes(j.status));
  const waiting = jobs.filter((j) => j.status === JobStatus.WAITING_FOR_AVAILABILITY);
  const needsAttention = jobs.filter((j) => j.status === JobStatus.REQUIRES_USER_ACTION);

  return (
    <div style={{ width: 260, padding: 14 }}>
      <div className="af-row-between" style={{ marginBottom: 8 }}>
        <strong>AI Flow</strong>
      </div>
      {loading ? (
        <p className="af-muted">Loading...</p>
      ) : (
        <div className="af-stack" style={{ fontSize: 13 }}>
          <div className="af-row-between">
            <span>Active</span>
            <span className="af-badge af-badge-primary">{active.length}</span>
          </div>
          <div className="af-row-between">
            <span>Waiting</span>
            <span className="af-badge af-badge-warning">{waiting.length}</span>
          </div>
          <div className="af-row-between">
            <span>Needs attention</span>
            <span className="af-badge af-badge-danger">{needsAttention.length}</span>
          </div>
        </div>
      )}
      <button className="af-btn af-btn-primary" style={{ width: "100%", marginTop: 12, justifyContent: "center" }} onClick={openSidePanel}>
        Open dashboard
      </button>
    </div>
  );
}
