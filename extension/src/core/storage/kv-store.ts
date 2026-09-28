/**
 * Minimal async key-value store abstraction. Every higher-level store
 * (jobs, checkpoints, settings) depends on this interface rather than on
 * `chrome.storage` directly, so unit tests can run without any browser
 * APIs and the storage backend stays swappable.
 */
export interface KeyValueStore {
  get<T>(key: string): Promise<T | undefined>;
  set<T>(key: string, value: T): Promise<void>;
  remove(key: string): Promise<void>;
  keys(): Promise<string[]>;
  clear(): Promise<void>;
}

export class MemoryKvStore implements KeyValueStore {
  private map = new Map<string, unknown>();

  async get<T>(key: string): Promise<T | undefined> {
    return this.map.get(key) as T | undefined;
  }

  async set<T>(key: string, value: T): Promise<void> {
    this.map.set(key, value);
  }

  async remove(key: string): Promise<void> {
    this.map.delete(key);
  }

  async keys(): Promise<string[]> {
    return Array.from(this.map.keys());
  }

  async clear(): Promise<void> {
    this.map.clear();
  }
}

/** Wraps chrome.storage.local (or .sync, if ever needed) behind the KeyValueStore interface. */
export class ChromeKvStore implements KeyValueStore {
  constructor(private readonly area: chrome.storage.StorageArea = chrome.storage.local) {}

  async get<T>(key: string): Promise<T | undefined> {
    const result = await this.area.get(key);
    return result[key] as T | undefined;
  }

  async set<T>(key: string, value: T): Promise<void> {
    await this.area.set({ [key]: value });
  }

  async remove(key: string): Promise<void> {
    await this.area.remove(key);
  }

  async keys(): Promise<string[]> {
    const all = await this.area.get(null);
    return Object.keys(all);
  }

  async clear(): Promise<void> {
    await this.area.clear();
  }
}
