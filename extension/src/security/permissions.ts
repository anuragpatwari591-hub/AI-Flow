/**
 * Host permissions for provider domains are requested on demand (optional
 * permissions), never declared broadly in the manifest. This keeps the
 * extension's footprint minimal and lets the user see exactly which sites
 * they're granting access to, and when.
 */
export async function hasProviderPermission(domainPattern: string): Promise<boolean> {
  return chrome.permissions.contains({ origins: [domainPattern] });
}

export async function requestProviderPermission(domainPattern: string): Promise<boolean> {
  return chrome.permissions.request({ origins: [domainPattern] });
}

export async function revokeProviderPermission(domainPattern: string): Promise<boolean> {
  return chrome.permissions.remove({ origins: [domainPattern] });
}

export async function listGrantedProviderPermissions(): Promise<string[]> {
  const permissions = await chrome.permissions.getAll();
  return permissions.origins ?? [];
}
