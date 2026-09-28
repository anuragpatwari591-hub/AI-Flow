import { ChromeKvStore } from "@/core/storage/kv-store";
import { JobStore } from "@/core/storage/job-store";
import { CheckpointStore } from "@/core/checkpoint/checkpoint-store";
import { SettingsStore } from "@/core/storage/settings-store";
import { AttachmentStore } from "@/core/storage/attachment-store";
import { JobManager } from "@/core/jobs/job-manager";
import { JobRunner } from "@/core/jobs/job-runner";
import { Scheduler } from "@/core/scheduler/scheduler";
import { ChromeAlarmsPort } from "@/core/scheduler/alarms-port";
import { createDefaultProviderRegistry } from "@/providers/provider-registry";
import { handleUiRequest, type RouterContext } from "@/background/message-router";
import { reconcileOnStartup, reconcileQueueTick } from "@/background/reconciliation";
import { notifyForEvent } from "@/background/notifications";
import type { UiRequest, UiResponse } from "@/core/messaging/protocol";

const kv = new ChromeKvStore();
const jobStore = new JobStore(kv);
const checkpointStore = new CheckpointStore(kv);
const settingsStore = new SettingsStore(kv);
const attachmentStore = new AttachmentStore();
const providerRegistry = createDefaultProviderRegistry();
const jobManager = new JobManager(jobStore);
const scheduler = new Scheduler(new ChromeAlarmsPort());
const jobRunner = new JobRunner(jobManager, checkpointStore, scheduler, providerRegistry, attachmentStore, notifyForEvent);

const routerContext: RouterContext = {
  jobStore,
  jobs: jobManager,
  runner: jobRunner,
  scheduler,
  checkpoints: checkpointStore,
  settings: settingsStore,
  attachments: attachmentStore,
  providers: providerRegistry,
};

scheduler.onAlarm((parsed) => {
  if (parsed.type === "job") {
    void jobRunner.runStep(parsed.jobId);
  } else if (parsed.type === "queue-tick") {
    void reconcileQueueTick(jobManager, scheduler, jobRunner);
  }
});

chrome.runtime.onInstalled.addListener(() => {
  void reconcileOnStartup(jobManager, scheduler, jobRunner);
});

chrome.runtime.onStartup.addListener(() => {
  void reconcileOnStartup(jobManager, scheduler, jobRunner);
});

chrome.runtime.onMessage.addListener((message: UiRequest, _sender, sendResponse: (response: UiResponse) => void) => {
  handleUiRequest(message, routerContext).then(sendResponse);
  return true;
});

// Best-effort immediate reconciliation for the case where the service
// worker itself was just (re)started outside of onInstalled/onStartup
// (e.g. woken by an alarm after being idle).
void reconcileOnStartup(jobManager, scheduler, jobRunner);
