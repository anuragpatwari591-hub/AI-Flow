import { useEffect, useMemo, useState } from "react";
import { callBackground } from "@/ui/api-client";
import { ExecutionMode, JobPriority, type AttachmentMeta, type Job } from "@/core/jobs/job.model";
import type { ProviderDescriptor } from "@/providers/provider-registry";
import { formatBytes } from "@/utils/file-utils";

const STEPS = ["Basics", "Instructions", "Attachments & Settings", "Review"] as const;

function readFileAsArrayBuffer(file: File): Promise<ArrayBuffer> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(reader.result as ArrayBuffer);
    reader.onerror = () => reject(reader.error);
    reader.readAsArrayBuffer(file);
  });
}

export function JobCreateWizard({ onDone, onCancel }: { onDone: (job: Job) => void; onCancel: () => void }) {
  const [stepIndex, setStepIndex] = useState(0);
  const [providers, setProviders] = useState<ProviderDescriptor[]>([]);
  const [grantedOrigins, setGrantedOrigins] = useState<string[]>([]);
  const [job, setJob] = useState<Job | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const [title, setTitle] = useState("");
  const [provider, setProvider] = useState("mock");
  const [conversationUrl, setConversationUrl] = useState("");
  const [conversationTitle, setConversationTitle] = useState("");
  const [instructions, setInstructions] = useState("");
  const [steps, setSteps] = useState<string[]>([""]);
  const [executionMode, setExecutionMode] = useState<Job["executionMode"]>(ExecutionMode.SEMI_AUTOMATIC);
  const [priority, setPriority] = useState<Job["priority"]>(JobPriority.NORMAL);
  const [requiresConfirmationBeforeSubmit, setRequiresConfirmationBeforeSubmit] = useState(false);
  const [requiresConfirmationBeforeUpload, setRequiresConfirmationBeforeUpload] = useState(false);
  const [maxRetries, setMaxRetries] = useState(6);

  useEffect(() => {
    void callBackground<{ providers: ProviderDescriptor[] }>({ type: "LIST_PROVIDERS" }).then((r) => setProviders(r.providers));
    void callBackground<{ origins: string[] }>({ type: "LIST_PROVIDER_PERMISSIONS" }).then((r) => setGrantedOrigins(r.origins));
  }, []);

  const selectedProvider = providers.find((p) => p.id === provider);
  const domainPattern = selectedProvider ? `https://${selectedProvider.domains[0]}/*` : undefined;
  const hasPermission = !domainPattern || grantedOrigins.some((o) => o === domainPattern);

  const canProceedFromBasics = title.trim().length > 0 && conversationUrl.trim().length > 0 && (!selectedProvider?.experimental || hasPermission);
  const canProceedFromInstructions = instructions.trim().length > 0;

  async function requestPermission() {
    if (!domainPattern) return;
    const { granted } = await callBackground<{ granted: boolean }>({ type: "REQUEST_PROVIDER_PERMISSION", domainPattern });
    if (granted) setGrantedOrigins((prev) => [...prev, domainPattern]);
  }

  async function ensureDraftCreated(): Promise<Job> {
    if (job) return job;
    const created = await callBackground<Job>({
      type: "CREATE_JOB",
      input: {
        title: title.trim(),
        provider,
        conversationUrl: conversationUrl.trim(),
        conversationTitle: conversationTitle.trim() || undefined,
        instructions,
        executionMode,
        priority,
        steps: steps.map((s) => s.trim()).filter(Boolean),
        requiresConfirmationBeforeSubmit,
        requiresConfirmationBeforeUpload,
        retryPolicy: { maxAttempts: maxRetries },
      },
    });
    setJob(created);
    return created;
  }

  async function goNext() {
    setError(null);
    setBusy(true);
    try {
      if (stepIndex === 1) {
        await ensureDraftCreated();
      }
      setStepIndex((i) => Math.min(i + 1, STEPS.length - 1));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  async function handleFiles(fileList: FileList | null) {
    if (!fileList || !job) return;
    setBusy(true);
    setError(null);
    try {
      for (const file of Array.from(fileList)) {
        const data = await readFileAsArrayBuffer(file);
        const meta = await callBackground<AttachmentMeta>({
          type: "STORE_ATTACHMENT",
          jobId: job.id,
          file: { name: file.name, type: file.type, size: file.size, data },
        });
        setJob((prev) => (prev ? { ...prev, attachments: [...prev.attachments, meta] } : prev));
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  async function removeAttachment(attachmentId: string) {
    if (!job) return;
    const updated = await callBackground<Job>({ type: "REMOVE_ATTACHMENT", jobId: job.id, attachmentId });
    setJob(updated);
  }

  async function applySettingsAndQueue(queueNow: boolean) {
    setBusy(true);
    setError(null);
    try {
      const draft = await ensureDraftCreated();
      const updated = await callBackground<Job>({
        type: "UPDATE_JOB_DETAILS",
        jobId: draft.id,
        patch: {
          title: title.trim(),
          instructions,
          conversationTitle: conversationTitle.trim() || undefined,
          executionMode,
          priority,
          requiresConfirmationBeforeSubmit,
          requiresConfirmationBeforeUpload,
          retryPolicy: { maxAttempts: maxRetries, baseDelayMs: 30_000 },
        },
      });
      if (queueNow) {
        const queued = await callBackground<Job>({ type: "QUEUE_JOB", jobId: updated.id });
        onDone(queued);
      } else {
        onDone(updated);
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  const totalAttachmentBytes = useMemo(() => job?.attachments.reduce((sum, a) => sum + a.size, 0) ?? 0, [job]);

  return (
    <div className="af-card af-stack" style={{ padding: 16 }}>
      <div className="af-row-between">
        <h2 style={{ margin: 0, fontSize: 16 }}>New job</h2>
        <button className="af-btn af-btn-sm" onClick={onCancel} aria-label="Cancel job creation">
          Cancel
        </button>
      </div>

      <div className="af-row" role="tablist" aria-label="Job creation steps">
        {STEPS.map((label, i) => (
          <span key={label} className={`af-badge ${i === stepIndex ? "af-badge-primary" : ""}`}>
            {i + 1}. {label}
          </span>
        ))}
      </div>

      {error && <p style={{ color: "var(--af-danger)" }}>{error}</p>}

      {stepIndex === 0 && (
        <div className="af-stack">
          <div>
            <label className="af-label" htmlFor="job-title">
              Task name
            </label>
            <input id="job-title" className="af-input" value={title} onChange={(e) => setTitle(e.target.value)} placeholder="Build my B.Tech project" />
          </div>
          <div>
            <label className="af-label" htmlFor="job-provider">
              AI provider
            </label>
            <select id="job-provider" className="af-select" value={provider} onChange={(e) => setProvider(e.target.value)}>
              {providers.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.displayName}
                  {p.experimental ? " (experimental)" : ""}
                </option>
              ))}
            </select>
          </div>
          {selectedProvider?.experimental && !hasPermission && (
            <div className="af-card" style={{ padding: 10, background: "var(--af-surface-alt)" }}>
              <p className="af-muted" style={{ marginTop: 0 }}>
                AI Flow needs your permission to interact with {selectedProvider.domains.join(", ")}. This is requested on demand,
                never granted broadly.
              </p>
              <button className="af-btn" onClick={requestPermission}>
                Grant access to {selectedProvider.domains[0]}
              </button>
            </div>
          )}
          <div>
            <label className="af-label" htmlFor="job-conversation-url">
              Conversation URL
            </label>
            <input
              id="job-conversation-url"
              className="af-input"
              value={conversationUrl}
              onChange={(e) => setConversationUrl(e.target.value)}
              placeholder="https://claude.ai/chat/..."
            />
          </div>
          <div>
            <label className="af-label" htmlFor="job-conversation-title">
              Conversation title (optional, used to help verify the right chat is open)
            </label>
            <input id="job-conversation-title" className="af-input" value={conversationTitle} onChange={(e) => setConversationTitle(e.target.value)} />
          </div>
        </div>
      )}

      {stepIndex === 1 && (
        <div className="af-stack">
          <div>
            <label className="af-label" htmlFor="job-instructions">
              Instructions
            </label>
            <textarea
              id="job-instructions"
              className="af-textarea"
              rows={6}
              value={instructions}
              onChange={(e) => setInstructions(e.target.value)}
              placeholder="Describe the task in detail..."
            />
          </div>
          <div>
            <label className="af-label">Step checklist (used to track progress and continuation)</label>
            <div className="af-stack">
              {steps.map((step, i) => (
                <div className="af-row" key={i}>
                  <input
                    className="af-input"
                    value={step}
                    onChange={(e) => setSteps((prev) => prev.map((s, idx) => (idx === i ? e.target.value : s)))}
                    placeholder={`Step ${i + 1}`}
                  />
                  <button className="af-btn af-btn-sm" onClick={() => setSteps((prev) => prev.filter((_, idx) => idx !== i))} aria-label="Remove step">
                    &times;
                  </button>
                </div>
              ))}
              <button className="af-btn af-btn-sm" onClick={() => setSteps((prev) => [...prev, ""])}>
                + Add step
              </button>
            </div>
          </div>
        </div>
      )}

      {stepIndex === 2 && job && (
        <div className="af-stack">
          <div>
            <label className="af-label">Attachments ({formatBytes(totalAttachmentBytes)})</label>
            <input type="file" multiple onChange={(e) => handleFiles(e.target.files)} />
            <div className="af-stack" style={{ marginTop: 8 }}>
              {job.attachments.map((a) => (
                <div key={a.id} className="af-row-between af-card" style={{ padding: 8 }}>
                  <div>
                    <div style={{ fontSize: 12 }}>{a.name}</div>
                    <div className="af-muted" style={{ fontSize: 11 }}>
                      {formatBytes(a.size)} &middot; {a.status}
                      {a.rejectionReason ? ` — ${a.rejectionReason}` : ""}
                    </div>
                  </div>
                  <button className="af-btn af-btn-sm" onClick={() => removeAttachment(a.id)}>
                    Remove
                  </button>
                </div>
              ))}
            </div>
          </div>

          <div>
            <label className="af-label" htmlFor="job-execution-mode">
              Execution mode
            </label>
            <select id="job-execution-mode" className="af-select" value={executionMode} onChange={(e) => setExecutionMode(e.target.value as Job["executionMode"])}>
              <option value={ExecutionMode.MANUAL}>Manual — confirm every step</option>
              <option value={ExecutionMode.SEMI_AUTOMATIC}>Semi-automatic — approve each continuation</option>
              <option value={ExecutionMode.AUTONOMOUS}>Autonomous — continue automatically</option>
            </select>
          </div>
          <div>
            <label className="af-label" htmlFor="job-priority">
              Priority
            </label>
            <select id="job-priority" className="af-select" value={priority} onChange={(e) => setPriority(e.target.value as Job["priority"])}>
              <option value={JobPriority.LOW}>Low</option>
              <option value={JobPriority.NORMAL}>Normal</option>
              <option value={JobPriority.HIGH}>High</option>
            </select>
          </div>
          <div>
            <label className="af-label" htmlFor="job-max-retries">
              Maximum retry attempts
            </label>
            <input
              id="job-max-retries"
              className="af-input"
              type="number"
              min={1}
              max={20}
              value={maxRetries}
              onChange={(e) => setMaxRetries(Number(e.target.value))}
            />
          </div>
          <label className="af-row">
            <input type="checkbox" checked={requiresConfirmationBeforeSubmit} onChange={(e) => setRequiresConfirmationBeforeSubmit(e.target.checked)} />
            Confirm with me before every submission
          </label>
          <label className="af-row">
            <input type="checkbox" checked={requiresConfirmationBeforeUpload} onChange={(e) => setRequiresConfirmationBeforeUpload(e.target.checked)} />
            Confirm with me before uploading files
          </label>
        </div>
      )}

      {stepIndex === 3 && (
        <div className="af-stack">
          <h3 style={{ fontSize: 13, margin: 0 }}>Review</h3>
          <div className="af-card" style={{ padding: 12 }}>
            <p>
              <strong>{title}</strong>
            </p>
            <p className="af-muted">
              {selectedProvider?.displayName ?? provider} &middot; {conversationUrl}
            </p>
            <p style={{ whiteSpace: "pre-wrap" }}>{instructions}</p>
            <p className="af-muted">
              {steps.filter(Boolean).length} step(s) &middot; {executionMode} &middot; priority {priority} &middot; {job?.attachments.length ?? 0} attachment(s)
            </p>
          </div>
          <div className="af-row">
            <button className="af-btn" disabled={busy} onClick={() => applySettingsAndQueue(false)}>
              Save as draft
            </button>
            <button className="af-btn af-btn-primary" disabled={busy} onClick={() => applySettingsAndQueue(true)}>
              Queue job now
            </button>
          </div>
        </div>
      )}

      {stepIndex < 3 && (
        <div className="af-row-between">
          <button className="af-btn" disabled={stepIndex === 0 || busy} onClick={() => setStepIndex((i) => Math.max(0, i - 1))}>
            Back
          </button>
          <button
            className="af-btn af-btn-primary"
            disabled={busy || (stepIndex === 0 && !canProceedFromBasics) || (stepIndex === 1 && !canProceedFromInstructions)}
            onClick={goNext}
          >
            Next
          </button>
        </div>
      )}
    </div>
  );
}
