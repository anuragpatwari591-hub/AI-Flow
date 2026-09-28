import type { ContentScriptRequest, ContentScriptResponse } from "@/core/messaging/content-protocol";

/**
 * Generic DOM bridge injected into a provider tab on demand (never
 * declared as an always-on content script in the manifest). It only reads
 * visible page text/attributes and interacts with standard form elements
 * that a human user could click or type into themselves — there is no
 * network access, no private API calls, and no attempt to defeat any
 * security control. Provider-specific selectors live in the adapter that
 * sends these requests, never here.
 */

function queryRequired(selector: string): Element {
  const el = document.querySelector(selector);
  if (!el) throw new Error(`Element not found for selector: ${selector}`);
  return el;
}

function insertText(selector: string, text: string): void {
  const el = queryRequired(selector);
  if (el instanceof HTMLTextAreaElement || el instanceof HTMLInputElement) {
    el.focus();
    el.value = text;
    el.dispatchEvent(new Event("input", { bubbles: true }));
    el.dispatchEvent(new Event("change", { bubbles: true }));
    return;
  }
  if (el instanceof HTMLElement && el.isContentEditable) {
    el.focus();
    el.textContent = text;
    el.dispatchEvent(new InputEvent("input", { bubbles: true }));
    return;
  }
  throw new Error(`Element for selector "${selector}" is not a recognized text input.`);
}

function click(selector: string): void {
  const el = queryRequired(selector);
  if (el instanceof HTMLElement) {
    el.click();
    return;
  }
  throw new Error(`Element for selector "${selector}" is not clickable.`);
}

function readText(selector: string): string {
  const el = queryRequired(selector);
  return (el.textContent ?? "").trim();
}

function elementExists(selector: string): boolean {
  return Boolean(document.querySelector(selector));
}

function attachFile(selector: string, file: { name: string; type: string; data: ArrayBuffer }): void {
  const el = queryRequired(selector);
  if (!(el instanceof HTMLInputElement) || el.type !== "file") {
    throw new Error(`Element for selector "${selector}" is not a file input.`);
  }
  const blob = new Blob([file.data], { type: file.type });
  const domFile = new File([blob], file.name, { type: file.type });
  const dataTransfer = new DataTransfer();
  dataTransfer.items.add(domFile);
  el.files = dataTransfer.files;
  el.dispatchEvent(new Event("change", { bubbles: true }));
}

function scanPatterns(patterns: string[]): boolean {
  const bodyText = document.body?.innerText ?? "";
  return patterns.some((source) => {
    try {
      return new RegExp(source, "i").test(bodyText);
    } catch {
      return false;
    }
  });
}

function getMetadata() {
  return { url: location.href, title: document.title };
}

function handle(request: ContentScriptRequest): ContentScriptResponse {
  try {
    switch (request.action) {
      case "GET_METADATA":
        return { ok: true, data: getMetadata() };
      case "INSERT_TEXT":
        insertText(request.selector, request.text);
        return { ok: true };
      case "CLICK":
        click(request.selector);
        return { ok: true };
      case "READ_TEXT":
        return { ok: true, data: readText(request.selector) };
      case "ATTACH_FILE":
        attachFile(request.selector, request.file);
        return { ok: true };
      case "SCAN_PATTERNS":
        return { ok: true, data: scanPatterns(request.patterns) };
      case "ELEMENT_EXISTS":
        return { ok: true, data: elementExists(request.selector) };
      default:
        return { ok: false, error: `Unknown action: ${JSON.stringify(request)}` };
    }
  } catch (error) {
    return { ok: false, error: error instanceof Error ? error.message : String(error) };
  }
}

chrome.runtime.onMessage.addListener((message: ContentScriptRequest, _sender, sendResponse) => {
  sendResponse(handle(message));
  return true;
});
