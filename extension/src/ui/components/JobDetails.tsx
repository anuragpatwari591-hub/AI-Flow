import { useCallback, useEffect, useState } from "react";
import { callBackground } from "@/ui/api-client";
import { JobStatus, type Job } from "@/core/jobs/job.model";
import type { Checkpoint } from "@/core/checkpoint/checkpoint.model";
import { StatusBadge } from "@/ui/components/StatusBadge";
import { formatBytes } from "@/utils/file-utils";

const LEVEL_COLOR: Record<string, string> = {
  ERROR: "var(--af-danger)",
  WARNING: "var(--af-warning)",
  SUCCESS: "var(--af-success)",
  INFO: "var(--af-text)",
  DEBUG: "var(--af-text-muted)",
};

export function JobDetails({ jobId, onBack, onChanged }: { jobId: string; onBack: () => void; onChanged: () => void }) {
  const [job, setJob] = useState<Job | null>(null);
  const [checkpoints, setCheckpoints] = useState<Checkpoint[]>([]);
  const [busy, setBusy] = useState(false);

  const refresh = useCallback(async () => {
    const [j, c] = await Promise.all([
      callBackground<Job>({ type: "GET_JOB", jobId }),
      callBackground<{ checkpoints: Checkpoint[] }>({ type: "LIST_CHECKPOINTS", jobId }),
    ]);
    setJob(j);
    setCheckpoints(c.checkpoints);
  }, [jobId]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  async function run<T>(action: () => Promise<T>) {
    setBusy(true);
    try {
      await action();
      await refresh();
      onChanged();
    } finally {
      setBusy(false);
    }
  }

  if (!job) return <p className="af-muted">Loading...</p>;

  const canPause = ["QUEUED", "WAITING_FOR_AVAILABILITY", "READY", "RUNNING", "UPLOADING", "SUBMITTING", "PROCESSING", "WAITING_FOR_RESPONSE", "CONTINUING"].includes(
    job.status,
  );
  const canResume = job.status === JobStatus.PAUSED && !job.pendingAction;
  const canRetry = job.status === JobStatus.FAILED || job.status === JobStatus.REQUIRES_USER_ACTION;
  const canCancel = job.status !== JobStatus.COMPLETED && job.status !== JobStatus.CANCELLED;

  return (
    <div className="af-stack">
      <div className="af-row-between">
        <button className="af-btn af-btn-sm" onClick={onBack}>
          &larr; Back
        </button>
        <StatusBadge status={job.status} />
      </div>

      <h2 style={{ margin: 0 }}>{job.title}</h2>
      <div className="af-muted" style={{ fontSize: 12 }}>
        {job.provider} &middot; <a href={job.conversationUrl} target="_blank" rel="noreferrer">{job.conversationTitle ?? job.conversationUrl}</a>
      </div>

      {job.status === JobStatus.PAUSED && job.pendingAction && (
        <div className="af-card" style={{ padding: 12, background: "var(--af-surface-alt)" }}>
          <p style={{ marginTop: 0 }}>Confirmation needed before AI Flow will {job.pendingAction.toLowerCase()}s.</p>
          <button className="af-btn af-btn-primary" disabled={busy} onClick={() => run(() => callBackground({ type: "CONFIRM_PENDING_ACTION", jobId }))}>
            Confirm &amp; continue
          </button>
        </div>
      )}

      {job.lastError && (
        <div className="af-card" style={{ padding: 12, borderColor: "var(--af-danger)" }}>
          <strong style={{ color: "var(--af-danger)" }}>{job.lastError.code}</strong>
          <p style={{ margin: "4px 0 0" }}>{job.lastError.message}</p>
        </div>
      )}

      <div className="af-row" style={{ flexWrap: "wrap" }}>
        {canPause && (
          <button className="af-btn" disabled={busy} onClick={() => run(() => callBackground({ type: "PAUSE_JOB", jobId }))}>
            Pause
          </button>
        )}
        {canResume && (
          <button className="af-btn af-btn-primary" disabled={busy} onClick={() => run(() => callBackground({ type: "RESUME_JOB", jobId }))}>
            Resume
          </button>
        )}
        {canRetry && (
          <button className="af-btn af-btn-primary" disabled={busy} onClick={() => run(() => callBackground({ type: "RETRY_JOB", jobId }))}>
            Retry
          </button>
        )}
        {canCancel && (
          <button className="af-btn af-btn-danger" disabled={busy} onClick={() => run(() => callBackground({ type: "CANCEL_JOB", jobId }))}>
            Cancel
          </button>
        )}
        <button className="af-btn" disabled={busy} onClick={() => run(() => callBackground({ type: "DUPLICATE_JOB", jobId }))}>
          Duplicate
        </button>
        <button
          className="af-btn af-btn-danger"
          disabled={busy}
          onClick={() => {
            if (confirm("Delete this job and its attachments? This cannot be undone.")) {
              void run(() => callBackground({ type: "DELETE_JOB", jobId })).then(onBack);
            }
          }}
        >
          Delete
        </button>
      </div>

      <div className="af-card" style={{ padding: 12 }}>
        <h3 style={{ fontSize: 13, marginTop: 0 }}>Instructions</h3>
        <p style={{ whiteSpace: "pre-wrap" }}>{job.instructions}</p>
      </div>

      <div className="af-card" style={{ padding: 12 }}>
        <h3 style={{ fontSize: 13, marginTop: 0 }}>
          Progress ({job.progress.completedSteps.length}/{job.progress.completedSteps.length + job.progress.remainingSteps.length})
        </h3>
        <ol>
          {job.progress.completedSteps.map((s, i) => (
            <li key={`done-${i}`} style={{ textDecoration: "line-through", color: "var(--af-text-muted)" }}>
              {s}
            </li>
          ))}
          {job.progress.remainingSteps.map((s, i) => (
            <li key={`todo-${i}`}>{s}</li>
          ))}
        </ol>
      </div>

      {job.attachments.length > 0 && (
        <div className="af-card" style={{ padding: 12 }}>
          <h3 style={{ fontSize: 13, marginTop: 0 }}>Attachments</h3>
          <div className="af-stack">
            {job.attachments.map((a) => (
              <div key={a.id} className="af-row-between">
                <span>{a.name}</span>
                <span className="af-muted">
                  {formatBytes(a.size)} &middot; {a.status}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}

      <div className="af-card" style={{ padding: 12 }}>
        <h3 style={{ fontSize: 13, marginTop: 0 }}>Checkpoints ({checkpoints.length})</h3>
        <div className="af-stack">
          {checkpoints.length === 0 && <p className="af-muted">No checkpoints yet.</p>}
          {checkpoints
            .slice()
            .reverse()
            .map((c) => (
              <div key={c.id} className="af-row-between">
                <div>
                  <div style={{ fontSize: 12 }}>{new Date(c.timestamp).toLocaleString()}</div>
                  <div className="af-muted" style={{ fontSize: 11 }}>
                    {c.completedTasks.length} done &middot; {c.remainingTasks.length} remaining
                  </div>
                </div>
                <button className="af-btn af-btn-sm" disabled={busy} onClick={() => run(() => callBackground({ type: "RESTART_FROM_CHECKPOINT", jobId, checkpointId: c.id }))}>
                  Restart here
                </button>
              </div>
            ))}
        </div>
      </div>

      <div className="af-card af-scroll" style={{ padding: 12, maxHeight: 260 }}>
        <h3 style={{ fontSize: 13, marginTop: 0 }}>Log</h3>
        <div className="af-stack" style={{ gap: 4 }}>
          {job.history
            .slice()
            .reverse()
            .map((entry) => (
              <div key={entry.id} style={{ fontSize: 12 }}>
                <span className="af-muted">[{new Date(entry.timestamp).toLocaleTimeString()}]</span>{" "}
                <span style={{ color: LEVEL_COLOR[entry.level] }}>{entry.code}</span> {entry.message}
              </div>
            ))}
        </div>
      </div>
    </div>
  );
}
