import type { ChatSession } from './store';
import { loadSessions, MIGRATED_KEY } from './store';

const base = window.location.pathname.replace(/\/index\.html$/, '').replace(/\/$/, '');
async function request<T>(path = '', method = 'GET', body?: unknown): Promise<T> {
  const response = await fetch(`${base}/api/conversations${path}`, {
    method, headers: { 'Content-Type': 'application/json' },
    ...(body === undefined ? {} : { body: JSON.stringify(body) }),
  });
  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    throw Object.assign(new Error(typeof error.detail === 'string' ? error.detail : `会话保存失败 (${response.status})`), { status: response.status });
  }
  return response.json() as Promise<T>;
}
const summarySession = (summary: Omit<ChatSession, 'messages'>): ChatSession => ({ ...summary, messages: [],
  messageStart: 0, historyLoaded: summary.messageCount === 0 });
export const loadSharedSessions = async () => (await request<Omit<ChatSession, 'messages'>[]>()).map(summarySession);
export const getSharedSession = (id: string, options: { before?: number; after?: number; epoch?: number } = {}) => {
  const query = new URLSearchParams({ limit: '50' });
  for (const [key, value] of Object.entries(options)) if (value !== undefined) query.set(key, String(value));
  return request<ChatSession>(`/${encodeURIComponent(id)}?${query}`);
};
export const ensureSharedSession = (s: ChatSession) => s.revision
  ? Promise.resolve(s) : request<Omit<ChatSession, 'messages'>>('', 'POST', s).then(summarySession);
export async function patchSharedSession(s: ChatSession, changes: Partial<ChatSession>): Promise<ChatSession> {
  const current = await ensureSharedSession(s);
  return summarySession(await request(`/${encodeURIComponent(s.id)}`, 'PATCH', { ...changes, ...(Object.hasOwn(changes, 'persona') ? { persona: changes.persona || null } : {}), revision: current.revision }));
}
export const deleteSharedSession = (s: ChatSession) => s.revision
  ? request(`/${encodeURIComponent(s.id)}?revision=${s.revision}`, 'DELETE') : Promise.resolve();

/** This runs only after an explicit click in the browser chosen for migration. */
export async function importLocalSessions(): Promise<number> {
  const local = loadSessions().filter((s) => s.messages.length > 0);
  if (!local.length) return 0;
  // If backup cannot be written, abort before uploading anything.
  const raw = localStorage.getItem('easel_sessions') || '[]';
  if (!localStorage.getItem('easel_sessions_before_shared_import')) {
    localStorage.setItem('easel_sessions_before_shared_import', raw);
  }
  await request<(ChatSession | null)[]>('/import', 'POST', local.map((s) => ({
    ...s, id: `shared_${s.id}`, messages: s.messages,
  })));
  const migrated = new Set<string>(JSON.parse(localStorage.getItem(MIGRATED_KEY) || '[]'));
  local.forEach((s) => migrated.add(s.id));
  localStorage.setItem(MIGRATED_KEY, JSON.stringify([...migrated]));
  return local.length;
}
