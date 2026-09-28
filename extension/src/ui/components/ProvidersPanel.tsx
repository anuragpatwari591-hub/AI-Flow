import { useEffect, useState } from "react";
import { callBackground } from "@/ui/api-client";
import type { ProviderDescriptor } from "@/providers/provider-registry";

export function ProvidersPanel() {
  const [providers, setProviders] = useState<ProviderDescriptor[]>([]);
  const [granted, setGranted] = useState<string[]>([]);

  async function refresh() {
    const [p, g] = await Promise.all([
      callBackground<{ providers: ProviderDescriptor[] }>({ type: "LIST_PROVIDERS" }),
      callBackground<{ origins: string[] }>({ type: "LIST_PROVIDER_PERMISSIONS" }),
    ]);
    setProviders(p.providers);
    setGranted(g.origins);
  }

  useEffect(() => {
    void refresh();
  }, []);

  async function grant(domain: string) {
    await callBackground({ type: "REQUEST_PROVIDER_PERMISSION", domainPattern: `https://${domain}/*` });
    await refresh();
  }

  return (
    <div className="af-stack">
      <h2 style={{ margin: 0, fontSize: 16 }}>Providers</h2>
      <p className="af-muted">
        AI Flow only requests access to a provider's site when you add it to a job, and never more than that one domain. See{" "}
        <code>docs/provider-adapters.md</code> for how each adapter works and its known limitations.
      </p>
      <div className="af-stack">
        {providers.map((p) => {
          const domainPattern = `https://${p.domains[0]}/*`;
          const hasAccess = granted.includes(domainPattern);
          return (
            <div key={p.id} className="af-card af-row-between" style={{ padding: 12 }}>
              <div>
                <strong>{p.displayName}</strong>
                {p.experimental && <span className="af-badge af-badge-warning" style={{ marginLeft: 8 }}>experimental</span>}
                <div className="af-muted" style={{ fontSize: 12 }}>
                  {p.domains.join(", ")}
                </div>
              </div>
              {p.experimental && p.domains[0] && (
                <button className="af-btn" disabled={hasAccess} onClick={() => grant(p.domains[0]!)}>
                  {hasAccess ? "Access granted" : "Grant access"}
                </button>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
