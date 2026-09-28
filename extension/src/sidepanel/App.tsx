import { useEffect, useState } from "react";
import { useJobs } from "@/ui/hooks/useJobs";
import { useSettings } from "@/ui/hooks/useSettings";
import { JobStatus, type Job } from "@/core/jobs/job.model";
import { Overview } from "@/ui/components/Overview";
import { JobList } from "@/ui/components/JobList";
import { JobDetails } from "@/ui/components/JobDetails";
import { JobCreateWizard } from "@/ui/components/JobCreateWizard";
import { SettingsPanel } from "@/ui/components/SettingsPanel";
import { ProvidersPanel } from "@/ui/components/ProvidersPanel";
import { SecurityPanel } from "@/ui/components/SecurityPanel";
import { LogsPanel } from "@/ui/components/LogsPanel";

const SECTIONS = [
  "Overview",
  "Active",
  "Queue",
  "Waiting",
  "Completed",
  "Failed",
  "History",
  "Providers",
  "Security",
  "Logs",
  "Settings",
] as const;
type Section = (typeof SECTIONS)[number];

const ACTIVE_STATUSES = new Set<string>([
  JobStatus.READY,
  JobStatus.RUNNING,
  JobStatus.UPLOADING,
  JobStatus.SUBMITTING,
  JobStatus.PROCESSING,
  JobStatus.WAITING_FOR_RESPONSE,
  JobStatus.CONTINUING,
]);

function filterBySection(jobs: Job[], section: Section): Job[] {
  switch (section) {
    case "Active":
      return jobs.filter((j) => ACTIVE_STATUSES.has(j.status));
    case "Queue":
      return jobs.filter((j) => j.status === JobStatus.QUEUED);
    case "Waiting":
      return jobs.filter((j) => j.status === JobStatus.WAITING_FOR_AVAILABILITY || j.status === JobStatus.PAUSED || j.status === JobStatus.REQUIRES_USER_ACTION);
    case "Completed":
      return jobs.filter((j) => j.status === JobStatus.COMPLETED);
    case "Failed":
      return jobs.filter((j) => j.status === JobStatus.FAILED);
    case "History":
      return jobs;
    default:
      return jobs;
  }
}

export function App() {
  const { jobs, refresh } = useJobs();
  const { settings } = useSettings();
  const [section, setSection] = useState<Section>("Overview");
  const [selectedJobId, setSelectedJobId] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);

  useEffect(() => {
    if (!settings) return;
    document.documentElement.dataset.theme = settings.theme === "system" ? "" : settings.theme;
  }, [settings]);

  if (selectedJobId) {
    return (
      <div style={{ padding: 16 }}>
        <JobDetails jobId={selectedJobId} onBack={() => setSelectedJobId(null)} onChanged={refresh} />
      </div>
    );
  }

  if (creating) {
    return (
      <div style={{ padding: 16 }}>
        <JobCreateWizard
          onCancel={() => setCreating(false)}
          onDone={(job) => {
            setCreating(false);
            setSelectedJobId(job.id);
            void refresh();
          }}
        />
      </div>
    );
  }

  return (
    <div style={{ display: "flex", minHeight: "100vh" }}>
      <nav
        className="af-scroll"
        style={{ width: 150, borderRight: "1px solid var(--af-border)", padding: 12, flexShrink: 0 }}
        aria-label="AI Flow sections"
      >
        <div style={{ fontWeight: 700, marginBottom: 12 }}>AI Flow</div>
        <div className="af-stack" style={{ gap: 2 }}>
          {SECTIONS.map((s) => (
            <button
              key={s}
              className="af-btn af-btn-sm"
              style={{
                justifyContent: "flex-start",
                border: "none",
                background: section === s ? "var(--af-surface-alt)" : "transparent",
                fontWeight: section === s ? 700 : 400,
              }}
              onClick={() => setSection(s)}
              aria-current={section === s}
            >
              {s}
            </button>
          ))}
        </div>
      </nav>
      <main className="af-scroll" style={{ flex: 1, padding: 16 }}>
        {section === "Overview" && <Overview jobs={jobs} onSelect={setSelectedJobId} onCreate={() => setCreating(true)} />}
        {section === "Providers" && <ProvidersPanel />}
        {section === "Security" && <SecurityPanel />}
        {section === "Logs" && <LogsPanel jobs={jobs} />}
        {section === "Settings" && <SettingsPanel />}
        {!["Overview", "Providers", "Security", "Logs", "Settings"].includes(section) && (
          <div className="af-stack">
            <div className="af-row-between">
              <h2 style={{ margin: 0, fontSize: 16 }}>{section}</h2>
              <button className="af-btn af-btn-primary" onClick={() => setCreating(true)}>
                + New job
              </button>
            </div>
            <JobList jobs={filterBySection(jobs, section)} onSelect={setSelectedJobId} emptyMessage={`No jobs in ${section.toLowerCase()}.`} />
          </div>
        )}
      </main>
    </div>
  );
}
