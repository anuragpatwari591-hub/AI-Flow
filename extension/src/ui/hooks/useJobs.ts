import { useCallback, useEffect, useState } from "react";
import { callBackground } from "@/ui/api-client";
import type { Job } from "@/core/jobs/job.model";

export function useJobs() {
  const [jobs, setJobs] = useState<Job[]>([]);
  const [loading, setLoading] = useState(true);

  const refresh = useCallback(async () => {
    const { jobs: list } = await callBackground<{ jobs: Job[] }>({ type: "LIST_JOBS" });
    setJobs([...list].sort((a, b) => new Date(b.updatedAt).getTime() - new Date(a.updatedAt).getTime()));
    setLoading(false);
  }, []);

  useEffect(() => {
    void refresh();
    const listener = (changes: Record<string, chrome.storage.StorageChange>, areaName: string) => {
      if (areaName !== "local") return;
      if (Object.keys(changes).some((key) => key.startsWith("aiflow:job"))) {
        void refresh();
      }
    };
    chrome.storage.onChanged.addListener(listener);
    return () => chrome.storage.onChanged.removeListener(listener);
  }, [refresh]);

  return { jobs, loading, refresh };
}
