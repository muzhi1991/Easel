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
    throw new Error(typeof error.detail === 'string' ? error.detail : `会话保存失败 (${response.status})`);
  }
  return response.json() as Promise<T>;
}
export const loadSharedSessions = () => request<ChatSession[]>();
export const getSharedSession = (id: string) => request<ChatSession>(`/${encodeURIComponent(id)}`);
export const ensureSharedSession = (s: ChatSession) => s.revision
  ? Promise.resolve(s) : request<ChatSession>('', 'POST', s);
export async function patchSharedSession(s: ChatSession, changes: Partial<ChatSession>): Promise<ChatSession> {
  const current = await ensureSharedSession(s);
  return request(`/${encodeURIComponent(s.id)}`, 'PATCH', { ...changes, ...(Object.hasOwn(changes, 'persona') ? { persona: changes.persona || null } : {}), revision: current.revision });
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
