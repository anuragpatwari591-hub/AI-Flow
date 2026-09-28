import { useRef } from "react";
import { useSettings } from "@/ui/hooks/useSettings";
import { callBackground } from "@/ui/api-client";
import type { ExportBundle } from "@/core/storage/export-import";
import { ExecutionMode } from "@/core/jobs/job.model";

export function SettingsPanel() {
  const { settings, update, reset } = useSettings();
  const fileInputRef = useRef<HTMLInputElement>(null);

  if (!settings) return <p className="af-muted">Loading settings...</p>;

  async function exportData() {
    const bundle = await callBackground<ExportBundle>({ type: "EXPORT_DATA" });
    const blob = new Blob([JSON.stringify(bundle, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `ai-flow-backup-${new Date().toISOString().slice(0, 10)}.json`;
    a.click();
    URL.revokeObjectURL(url);
  }

  async function importData(file: File) {
    const text = await file.text();
    const bundle = JSON.parse(text) as ExportBundle;
    await callBackground({ type: "IMPORT_DATA", bundle });
    alert("Import complete.");
  }

  return (
    <div className="af-stack">
      <h2 style={{ margin: 0, fontSize: 16 }}>Settings</h2>

      <div className="af-card af-stack" style={{ padding: 12 }}>
        <h3 style={{ fontSize: 13, margin: 0 }}>Defaults</h3>
        <div>
          <label className="af-label" htmlFor="settings-default-mode">
            Default execution mode
          </label>
          <select
            id="settings-default-mode"
            className="af-select"
            value={settings.defaultExecutionMode}
            onChange={(e) => update({ defaultExecutionMode: e.target.value as typeof settings.defaultExecutionMode })}
          >
            <option value={ExecutionMode.MANUAL}>Manual</option>
            <option value={ExecutionMode.SEMI_AUTOMATIC}>Semi-automatic</option>
            <option value={ExecutionMode.AUTONOMOUS}>Autonomous</option>
          </select>
        </div>
        <div>
          <label className="af-label" htmlFor="settings-max-retries">
            Maximum retries
          </label>
          <input
            id="settings-max-retries"
            type="number"
            className="af-input"
            min={1}
            max={20}
            value={settings.maxRetries}
            onChange={(e) => update({ maxRetries: Number(e.target.value) })}
          />
        </div>
        <div>
          <label className="af-label" htmlFor="settings-max-continuations">
            Maximum continuations per job
          </label>
          <input
            id="settings-max-continuations"
            type="number"
            className="af-input"
            min={1}
            max={100}
            value={settings.maxContinuations}
            onChange={(e) => update({ maxContinuations: Number(e.target.value) })}
          />
        </div>
      </div>

      <div className="af-card af-stack" style={{ padding: 12 }}>
        <h3 style={{ fontSize: 13, margin: 0 }}>Confirmations</h3>
        <label className="af-row">
          <input type="checkbox" checked={settings.confirmBeforeSubmission} onChange={(e) => update({ confirmBeforeSubmission: e.target.checked })} />
          Confirm before every submission by default
        </label>
        <label className="af-row">
          <input type="checkbox" checked={settings.confirmBeforeUpload} onChange={(e) => update({ confirmBeforeUpload: e.target.checked })} />
          Confirm before every file upload by default
        </label>
      </div>

      <div className="af-card af-stack" style={{ padding: 12 }}>
        <h3 style={{ fontSize: 13, margin: 0 }}>Notifications</h3>
        <label className="af-row">
          <input type="checkbox" checked={settings.notifyOnWaiting} onChange={(e) => update({ notifyOnWaiting: e.target.checked })} />
          Notify when a job starts waiting
        </label>
        <label className="af-row">
          <input type="checkbox" checked={settings.notifyOnResumed} onChange={(e) => update({ notifyOnResumed: e.target.checked })} />
          Notify when a job resumes
        </label>
        <label className="af-row">
          <input type="checkbox" checked={settings.notifyOnRequiresAction} onChange={(e) => update({ notifyOnRequiresAction: e.target.checked })} />
          Notify when a job requires action
        </label>
        <label className="af-row">
          <input type="checkbox" checked={settings.notifyOnCompleted} onChange={(e) => update({ notifyOnCompleted: e.target.checked })} />
          Notify when a job completes
        </label>
        <label className="af-row">
          <input type="checkbox" checked={settings.notifyOnFailed} onChange={(e) => update({ notifyOnFailed: e.target.checked })} />
          Notify when a job fails
        </label>
      </div>

      <div className="af-card af-stack" style={{ padding: 12 }}>
        <h3 style={{ fontSize: 13, margin: 0 }}>Appearance</h3>
        <div>
          <label className="af-label" htmlFor="settings-theme">
            Theme
          </label>
          <select id="settings-theme" className="af-select" value={settings.theme} onChange={(e) => update({ theme: e.target.value as typeof settings.theme })}>
            <option value="system">Match system</option>
            <option value="light">Light</option>
            <option value="dark">Dark</option>
          </select>
        </div>
        <label className="af-row">
          <input type="checkbox" checked={settings.reducedMotion} onChange={(e) => update({ reducedMotion: e.target.checked })} />
          Reduce motion
        </label>
      </div>

      <div className="af-card af-stack" style={{ padding: 12 }}>
        <h3 style={{ fontSize: 13, margin: 0 }}>Storage &amp; debugging</h3>
        <label className="af-row">
          <input type="checkbox" checked={settings.debugLogging} onChange={(e) => update({ debugLogging: e.target.checked })} />
          Verbose debug logging
        </label>
        <div className="af-row">
          <button className="af-btn" onClick={exportData}>
            Export data
          </button>
          <button className="af-btn" onClick={() => fileInputRef.current?.click()}>
            Import data
          </button>
          <input
            ref={fileInputRef}
            type="file"
            accept="application/json"
            style={{ display: "none" }}
            onChange={(e) => {
              const file = e.target.files?.[0];
              if (file) void importData(file);
            }}
          />
        </div>
        <button
          className="af-btn af-btn-danger"
          onClick={() => {
            if (confirm("Reset settings to defaults? This does not delete jobs.")) void reset();
          }}
        >
          Reset settings to defaults
        </button>
      </div>
    </div>
  );
}
