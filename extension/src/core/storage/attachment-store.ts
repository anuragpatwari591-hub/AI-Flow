/**
 * Stores attachment file contents in IndexedDB, kept deliberately separate
 * from job metadata (which lives in chrome.storage.local). This keeps large
 * binary payloads off the quota-limited storage.local area and means
 * exporting job metadata never accidentally drags file contents along.
 */
const DB_NAME = "ai-flow";
const DB_VERSION = 1;
const STORE_NAME = "attachments";

export interface StoredAttachment {
  id: string;
  jobId: string;
  name: string;
  type: string;
  data: ArrayBuffer;
}

function openDb(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    const request = indexedDB.open(DB_NAME, DB_VERSION);
    request.onupgradeneeded = () => {
      const db = request.result;
      if (!db.objectStoreNames.contains(STORE_NAME)) {
        const store = db.createObjectStore(STORE_NAME, { keyPath: "id" });
        store.createIndex("jobId", "jobId", { unique: false });
      }
    };
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error);
  });
}

export class AttachmentStore {
  async put(attachment: StoredAttachment): Promise<void> {
    const db = await openDb();
    await new Promise<void>((resolve, reject) => {
      const tx = db.transaction(STORE_NAME, "readwrite");
      tx.objectStore(STORE_NAME).put(attachment);
      tx.oncomplete = () => resolve();
      tx.onerror = () => reject(tx.error);
    });
    db.close();
  }

  async get(id: string): Promise<StoredAttachment | undefined> {
    const db = await openDb();
    const result = await new Promise<StoredAttachment | undefined>((resolve, reject) => {
      const tx = db.transaction(STORE_NAME, "readonly");
      const req = tx.objectStore(STORE_NAME).get(id);
      req.onsuccess = () => resolve(req.result as StoredAttachment | undefined);
      req.onerror = () => reject(req.error);
    });
    db.close();
    return result;
  }

  async listForJob(jobId: string): Promise<StoredAttachment[]> {
    const db = await openDb();
    const result = await new Promise<StoredAttachment[]>((resolve, reject) => {
      const tx = db.transaction(STORE_NAME, "readonly");
      const index = tx.objectStore(STORE_NAME).index("jobId");
      const req = index.getAll(jobId);
      req.onsuccess = () => resolve(req.result as StoredAttachment[]);
      req.onerror = () => reject(req.error);
    });
    db.close();
    return result;
  }

  async delete(id: string): Promise<void> {
    const db = await openDb();
    await new Promise<void>((resolve, reject) => {
      const tx = db.transaction(STORE_NAME, "readwrite");
      tx.objectStore(STORE_NAME).delete(id);
      tx.oncomplete = () => resolve();
      tx.onerror = () => reject(tx.error);
    });
    db.close();
  }

  async deleteForJob(jobId: string): Promise<void> {
    const attachments = await this.listForJob(jobId);
    await Promise.all(attachments.map((a) => this.delete(a.id)));
  }
}
