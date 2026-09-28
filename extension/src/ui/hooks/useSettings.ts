import { useCallback, useEffect, useState } from "react";
import { callBackground } from "@/ui/api-client";
import type { Settings } from "@/core/storage/settings-store";

export function useSettings() {
  const [settings, setSettings] = useState<Settings | null>(null);

  const refresh = useCallback(async () => {
    setSettings(await callBackground<Settings>({ type: "GET_SETTINGS" }));
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const update = useCallback(async (patch: Partial<Settings>) => {
    const next = await callBackground<Settings>({ type: "UPDATE_SETTINGS", patch });
    setSettings(next);
    return next;
  }, []);

  const reset = useCallback(async () => {
    const next = await callBackground<Settings>({ type: "RESET_SETTINGS" });
    setSettings(next);
    return next;
  }, []);

  return { settings, update, reset, refresh };
}
