import type { ChatSession } from './store';
import { historyEnd, mergeSessionSummary } from './sessionHistory';

// Separate metadata from bodies: opening the home page never reads every history.
const scope = typeof location === 'undefined' ? '/' : location.pathname.replace(/index\.html$/, '').replace(/\/?$/, '/');
const DB_NAME = `easel-history-v1:${scope}`;
const STORES = ['summaries', 'history', 'usage', 'deleted'];
const MAX_BYTES = 50 * 1024 * 1024;
const MAX_HISTORIES = 50;
const MAX_AGE = 30 * 24 * 60 * 60 * 1000;
type Usage = { id: string; bytes: number; touched: number };
let connection: Promise<IDBDatabase | null> | undefined;

function database(): Promise<IDBDatabase | null> {
  return connection ??= new Promise((resolve) => {
    if (typeof indexedDB === 'undefined') { resolve(null); return; }
    const request = indexedDB.open(DB_NAME, 2);
    const timeout = setTimeout(() => resolve(null), 1000);
    request.onupgradeneeded = () => {
      for (const name of STORES) {
        if (!request.result.objectStoreNames.contains(name)) request.result.createObjectStore(name, { keyPath: 'id' });
      }
    };
    request.onsuccess = () => {
      clearTimeout(timeout);
      const db = request.result;
      db.onversionchange = () => { db.close(); connection = undefined; };
      resolve(db);
    };
    request.onerror = request.onblocked = () => { clearTimeout(timeout); resolve(null); };
  });
}
function result<T>(request: IDBRequest<T>): Promise<T> {
  return new Promise((resolve, reject) => {
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error);
  });
}
async function transact<T>(mode: IDBTransactionMode, work: (tx: IDBTransaction) => Promise<T>): Promise<T | undefined> {
  try {
    const db = await database();
    if (!db) return;
    const tx = db.transaction(STORES, mode);
    const done = new Promise<void>((resolve, reject) => {
      tx.oncomplete = () => resolve();
      tx.onerror = tx.onabort = () => reject(tx.error);
    });
    // Attach a handler immediately, including when work itself fails.
    void done.catch(() => {});
    const value = await work(tx);
    await done;
    return value;
  } catch { /* Private mode, eviction or quota failure must never break chat. */ }
}
export function summaryOnly(s: ChatSession): ChatSession {
  return { ...s, messages: [], messageStart: 0, historyLoaded: s.messageCount === 0, optimistic: undefined };
}
export async function readCachedSummaries(): Promise<ChatSession[]> {
  return (await transact('readonly', (tx) => result<ChatSession[]>(tx.objectStore('summaries').getAll()))) || [];
}

/** Only authoritative network summaries can create/delete cache identities. */
export async function cacheSummaries(incoming: ChatSession[], replace = true, knownIds?: Set<string>): Promise<void> {
  await transact('readwrite', async (tx) => {
    const summaries = tx.objectStore('summaries');
    const previous = await result<ChatSession[]>(summaries.getAll());
    const deleted = tx.objectStore('deleted');
    const tombstones = await result<{ id: string; at: number }[]>(deleted.getAll());
    const removed = new Set(tombstones.filter(t => t.at >= Date.now() - MAX_AGE).map(t => t.id));
    for (const t of tombstones) if (!removed.has(t.id)) deleted.delete(t.id);
    const byId = new Map(previous.map(s => [s.id, s]));
    const ids = new Set(incoming.map(s => s.id));
    for (const old of previous) {
      if (replace && !ids.has(old.id) && (!knownIds || knownIds.has(old.id))) {
        for (const name of ['summaries', 'history', 'usage']) tx.objectStore(name).delete(old.id);
        deleted.put({ id: old.id, at: Date.now() });
      }
    }
    for (const s of incoming) {
      if (removed.has(s.id)) continue;
      const old = byId.get(s.id);
      if (old && (old.revision || 0) > (s.revision || 0)) continue;
      if (old && (old.historyEpoch !== s.historyEpoch || (s.messageCount || 0) < (old.messageCount || 0))) {
        tx.objectStore('history').delete(s.id);
        tx.objectStore('usage').delete(s.id);
      }
      summaries.put(summaryOnly(s));
    }
  });
}
export async function removeCachedSession(id: string): Promise<void> {
  await transact('readwrite', async tx => {
    for (const name of ['summaries', 'history', 'usage']) tx.objectStore(name).delete(id);
    tx.objectStore('deleted').put({ id, at: Date.now() });
  });
}
export async function readCachedHistory(id: string): Promise<ChatSession | undefined> {
  return transact('readwrite', async (tx) => {
    const summary = await result<ChatSession | undefined>(tx.objectStore('summaries').get(id));
    const usage = await result<Usage | undefined>(tx.objectStore('usage').get(id));
    if (!summary || !usage || usage.touched < Date.now() - MAX_AGE) return;
    const history = await result<ChatSession | undefined>(tx.objectStore('history').get(id));
    if (!history || history.historyEpoch !== summary.historyEpoch) return;
    tx.objectStore('usage').put({ ...usage, touched: Date.now() });
    return mergeSessionSummary(history, summary);
  });
}

/** Persist network pages, never optimistic messages or partial streaming tokens. */
export async function cacheMessagePage(page: ChatSession): Promise<void> {
  await transact('readwrite', async (tx) => {
    const summaries = tx.objectStore('summaries');
    const summary = await result<ChatSession | undefined>(summaries.get(page.id));
    // A deleted conversation or a reply from a replaced history cannot reappear.
    if (!summary || (summary.historyEpoch || 0) > (page.historyEpoch || 0)) return;
    const history = tx.objectStore('history');
    const old = await result<ChatSession | undefined>(history.get(page.id));
    if (old && (old.historyEpoch || 0) > (page.historyEpoch || 0)) return;
    let merged: ChatSession = { ...page, historyLoaded: true };
    if (old && old.historyEpoch === page.historyEpoch) {
      const start = Math.min(old.messageStart || 0, page.messageStart || 0);
      const end = Math.max(historyEnd(old), historyEnd(page));
      // Retain the union of contiguous or overlapping pages, including races
      // from multiple tabs. A disjoint newer window replaces the old window.
      if ((old.messageStart || 0) <= historyEnd(page) && (page.messageStart || 0) <= historyEnd(old)) {
        const messages = Array.from({ length: end - start }, (_, i) => {
          const index = start + i;
          return old.messages[index - (old.messageStart || 0)] ?? page.messages[index - (page.messageStart || 0)];
        });
        merged = { ...((old.revision || 0) > (page.revision || 0) ? old : page), messages, messageStart: start, historyLoaded: true };
      } else if ((old.revision || 0) > (page.revision || 0)) return;
    }
    const latest = (summary.revision || 0) > (merged.revision || 0) ? summary : summaryOnly(merged);
    merged = mergeSessionSummary(merged, latest);
    summaries.put(latest);
    const bytes = new Blob([JSON.stringify(merged)]).size;
    const usage = tx.objectStore('usage');
    const entries = (await result<Usage[]>(usage.getAll())).filter(e => e.id !== page.id && e.touched >= Date.now() - MAX_AGE);
    entries.push({ id: page.id, bytes, touched: Date.now() });
    entries.sort((a, b) => b.touched - a.touched || (a.id === page.id ? -1 : b.id === page.id ? 1 : 0));
    let total = 0;
    const keep = new Set<string>();
    for (const entry of entries) {
      if (keep.size < MAX_HISTORIES && total + entry.bytes <= MAX_BYTES) {
        keep.add(entry.id);
        total += entry.bytes;
      }
    }
    for (const entry of await result<Usage[]>(usage.getAll())) {
      if (!keep.has(entry.id)) { history.delete(entry.id); usage.delete(entry.id); }
    }
    if (keep.has(page.id)) {
      history.put(merged);
      usage.put({ id: page.id, bytes, touched: Date.now() });
    }
  });
}
