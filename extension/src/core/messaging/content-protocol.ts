/**
 * Messages exchanged between a provider adapter (running in the background
 * service worker) and the generic content script injected into a provider
 * tab. Every action here is a plain, visible DOM interaction — reading
 * text, setting a form field's value, clicking a button — never a network
 * call, never a private API.
 */
export interface SerializedFile {
  name: string;
  type: string;
  data: ArrayBuffer;
}

export type ContentScriptRequest =
  | { action: "GET_METADATA" }
  | { action: "INSERT_TEXT"; selector: string; text: string }
  | { action: "CLICK"; selector: string }
  | { action: "READ_TEXT"; selector: string }
  | { action: "ATTACH_FILE"; selector: string; file: SerializedFile }
  | { action: "SCAN_PATTERNS"; patterns: string[] }
  | { action: "ELEMENT_EXISTS"; selector: string };

export type ContentScriptResponse =
  | { ok: true; data?: unknown }
  | { ok: false; error: string };

export const CONTENT_SCRIPT_PING = "AIFLOW_CONTENT_SCRIPT_READY";
