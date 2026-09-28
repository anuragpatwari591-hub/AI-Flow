import type { UiRequest, UiResponse } from "@/core/messaging/protocol";

/** Thin wrapper around chrome.runtime.sendMessage shared by the side panel, popup, and options pages. */
export async function callBackground<T = unknown>(request: UiRequest): Promise<T> {
  const response = (await chrome.runtime.sendMessage(request)) as UiResponse<T>;
  if (!response.ok) throw new Error(response.error);
  return response.data;
}
