import { useState } from "react";
import { SettingsPanel } from "@/ui/components/SettingsPanel";
import { ProvidersPanel } from "@/ui/components/ProvidersPanel";
import { SecurityPanel } from "@/ui/components/SecurityPanel";

const TABS = ["Settings", "Providers", "Security"] as const;

export function App() {
  const [tab, setTab] = useState<(typeof TABS)[number]>("Settings");
  return (
    <div style={{ maxWidth: 640, margin: "0 auto", padding: 24 }}>
      <h1 style={{ fontSize: 20 }}>AI Flow options</h1>
      <div className="af-row" style={{ marginBottom: 16 }}>
        {TABS.map((t) => (
          <button key={t} className={`af-btn ${tab === t ? "af-btn-primary" : ""}`} onClick={() => setTab(t)}>
            {t}
          </button>
        ))}
      </div>
      {tab === "Settings" && <SettingsPanel />}
      {tab === "Providers" && <ProvidersPanel />}
      {tab === "Security" && <SecurityPanel />}
    </div>
  );
}
