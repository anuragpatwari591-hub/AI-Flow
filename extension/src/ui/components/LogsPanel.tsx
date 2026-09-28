import { useMemo, useState } from "react";
import type { Job, JobHistoryEntry } from "@/core/jobs/job.model";

type Level = JobHistoryEntry["level"];
const LEVELS: Level[] = ["ERROR", "WARNING", "SUCCESS", "INFO", "DEBUG"];

const LEVEL_COLOR: Record<Level, string> = {
  ERROR: "var(--af-danger)",
  WARNING: "var(--af-warning)",
  SUCCESS: "var(--af-success)",
  INFO: "var(--af-text)",
  DEBUG: "var(--af-text-muted)",
};

export function LogsPanel({ jobs }: { jobs: Job[] }) {
  const [activeLevels, setActiveLevels] = useState<Set<Level>>(new Set(LEVELS));

  const entries = useMemo(() => {
    return jobs
      .flatMap((job) => job.history.map((entry) => ({ ...entry, jobTitle: job.title, jobId: job.id })))
      .sort((a, b) => new Date(b.timestamp).getTime() - new Date(a.timestamp).getTime());
  }, [jobs]);

  const filtered = entries.filter((e) => activeLevels.has(e.level));

  function toggleLevel(level: Level) {
    setActiveLevels((prev) => {
      const next = new Set(prev);
      if (next.has(level)) next.delete(level);
      else next.add(level);
      return next;
    });
  }

  function exportLogs() {
    const text = filtered.map((e) => `[${e.timestamp}] ${e.level} ${e.code} (${e.jobTitle}): ${e.message}`).join("\n");
    const blob = new Blob([text], { type: "text/plain" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `ai-flow-logs-${new Date().toISOString().slice(0, 10)}.txt`;
    a.click();
    URL.revokeObjectURL(url);
  }

  return (
    <div className="af-stack">
      <div className="af-row-between">
        <h2 style={{ margin: 0, fontSize: 16 }}>Logs</h2>
        <button className="af-btn af-btn-sm" onClick={exportLogs}>
          Export
        </button>
      </div>
      <div className="af-row">
        {LEVELS.map((level) => (
          <button
            key={level}
            className={`af-badge ${activeLevels.has(level) ? "af-badge-primary" : ""}`}
            style={{ cursor: "pointer", border: "none" }}
            onClick={() => toggleLevel(level)}
          >
            {level}
          </button>
        ))}
      </div>
      <div className="af-card af-scroll" style={{ padding: 12, maxHeight: 480 }}>
        {filtered.length === 0 && <p className="af-muted">No log entries match the selected levels.</p>}
        <div className="af-stack" style={{ gap: 4 }}>
          {filtered.map((entry) => (
            <div key={entry.id} style={{ fontSize: 12 }}>
              <span className="af-muted">[{new Date(entry.timestamp).toLocaleTimeString()}]</span>{" "}
              <span style={{ color: LEVEL_COLOR[entry.level] }}>{entry.code}</span>{" "}
              <span className="af-muted">({entry.jobTitle})</span> {entry.message}
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
