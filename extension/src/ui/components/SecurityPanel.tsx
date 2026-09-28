import { callBackground } from "@/ui/api-client";

export function SecurityPanel() {
  async function resetLocalData() {
    if (!confirm("This permanently deletes all jobs, checkpoints, attachments, and settings on this device. Continue?")) return;
    const bundle = await callBackground<{ jobs: { id: string }[] }>({ type: "EXPORT_DATA" });
    for (const job of bundle.jobs) {
      await callBackground({ type: "DELETE_JOB", jobId: job.id });
    }
    await callBackground({ type: "RESET_SETTINGS" });
    alert("Local data has been reset.");
  }

  return (
    <div className="af-stack">
      <h2 style={{ margin: 0, fontSize: 16 }}>Security &amp; privacy</h2>

      <div className="af-card af-stack" style={{ padding: 12 }}>
        <h3 style={{ fontSize: 13, margin: 0 }}>What AI Flow never does</h3>
        <ul>
          <li>Store your passwords, session cookies, or raw authentication credentials.</li>
          <li>Attempt to bypass CAPTCHAs, sign-in requirements, or provider rate limits.</li>
          <li>Send your prompts, files, or conversation contents to any server other than the provider's own site.</li>
          <li>Request access to a provider's site until you explicitly add it to a job.</li>
        </ul>
      </div>

      <div className="af-card af-stack" style={{ padding: 12 }}>
        <h3 style={{ fontSize: 13, margin: 0 }}>Where your data lives</h3>
        <ul>
          <li>Job metadata and settings: <code>chrome.storage.local</code>, on this device only.</li>
          <li>Attachment file contents: IndexedDB, on this device only.</li>
          <li>Nothing is synced to a remote AI Flow server — there isn't one.</li>
        </ul>
        <p className="af-muted">Full details: <code>docs/privacy.md</code> and <code>docs/security.md</code>.</p>
      </div>

      <div className="af-card af-stack" style={{ padding: 12 }}>
        <h3 style={{ fontSize: 13, margin: 0 }}>Danger zone</h3>
        <p className="af-muted">Deletes every job, checkpoint, attachment, and setting stored by AI Flow on this device.</p>
        <button className="af-btn af-btn-danger" onClick={resetLocalData}>
          Reset all local data
        </button>
      </div>
    </div>
  );
}
