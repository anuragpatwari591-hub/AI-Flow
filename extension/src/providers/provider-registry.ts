import type { AIProviderAdapter } from "@/providers/interface/types";
import { MockAIProvider } from "@/providers/mock/mock-provider";
import { ClaudeAdapter } from "@/providers/claude/claude-adapter";
import { ChatGptAdapter } from "@/providers/chatgpt/chatgpt-adapter";
import { GeminiAdapter } from "@/providers/gemini/gemini-adapter";

export interface ProviderDescriptor {
  id: string;
  displayName: string;
  domains: string[];
  experimental: boolean;
}

/**
 * Central place that knows about every provider adapter. Core logic (job
 * runner, UI) looks providers up by id here instead of importing adapter
 * classes directly, so adding a provider never requires touching the
 * scheduler, state machine, or job manager.
 */
export class ProviderRegistry {
  private adapters = new Map<string, AIProviderAdapter>();
  private experimentalIds = new Set<string>();

  register(adapter: AIProviderAdapter, experimental = false): void {
    this.adapters.set(adapter.id, adapter);
    if (experimental) this.experimentalIds.add(adapter.id);
  }

  get(id: string): AIProviderAdapter {
    const adapter = this.adapters.get(id);
    if (!adapter) throw new Error(`Unknown provider: ${id}`);
    return adapter;
  }

  list(): ProviderDescriptor[] {
    return Array.from(this.adapters.values()).map((adapter) => ({
      id: adapter.id,
      displayName: adapter.displayName,
      domains: adapter.domains,
      experimental: this.experimentalIds.has(adapter.id),
    }));
  }

  findByUrl(url: string): AIProviderAdapter | undefined {
    let hostname: string;
    try {
      hostname = new URL(url).hostname;
    } catch {
      return undefined;
    }
    return Array.from(this.adapters.values()).find((adapter) =>
      adapter.domains.some((domain) => hostname === domain || hostname.endsWith(`.${domain}`)),
    );
  }
}

export function createDefaultProviderRegistry(): ProviderRegistry {
  const registry = new ProviderRegistry();
  registry.register(new MockAIProvider(), false);
  registry.register(new ClaudeAdapter(), true);
  registry.register(new ChatGptAdapter(), true);
  registry.register(new GeminiAdapter(), true);
  return registry;
}
