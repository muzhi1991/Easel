import { createHash } from 'node:crypto';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';

/** Official per-exec environment hook: no shell rewriting or global environment mutation. */
export function installAccountScope(api, { root = process.env.EASEL_ROOT, read = readFileSync } = {}) {
  if (!root) return;
  api.on('resolve_exec_env', (event, ctx) => {
    const session = (ctx?.sessionKey || event.sessionKey)?.replace(/^agent:[^:]+:/, '');
    if (!session) return { EASEL_ACCOUNT_PERSONA: '_unbound' };
    try {
      const hash = createHash('sha256').update(session).digest('hex');
      const binding = JSON.parse(read(join(root, 'outputs', '_sessions', 'account-scopes', hash + '.json'), 'utf8'));
      if (typeof binding.persona !== 'string') throw new Error('Invalid scope');
      return { EASEL_ACCOUNT_PERSONA: binding.persona };
    } catch (error) {
      // Web owns this mapping. Unknown sessions must not borrow the general account.
      return { EASEL_ACCOUNT_PERSONA: '_unbound' };
    }
  });
}
