import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { runInNewContext } from 'node:vm';
import { test } from 'node:test';

const require = createRequire(new URL('../../web/frontend/package.json', import.meta.url));
const ts = require('typescript');
const app = readFileSync(new URL('../../web/frontend/src/App.tsx', import.meta.url), 'utf8');
const start = app.indexOf('  const refreshShared =');
const source = app.slice(start, app.indexOf('\n  useEffect(', start));
const { outputText } = ts.transpileModule(`${source}\nglobalThis.refresh = refreshShared;`, {
  compilerOptions: { target: ts.ScriptTarget.ES2022 },
});

const session = () => ({ id: 'shared_test', source: 'server', revision: 1, messages: [{ role: 'assistant', content: 'history' }] });
async function refresh(current, incoming, streaming = false) {
  let result;
  const context = {
    sessionsRef: { current }, historyBusy: { current: new Set() },
    streamCtl: { current: streaming ? { shared_test: {} } : {} },
    loadSharedSessions: async () => structuredClone(incoming), loadSessions: () => [],
    setSessions: updater => { result = updater(current); }, useCallback: fn => fn,
  };
  runInNewContext(outputText, context);
  await context.refresh();
  return result;
}

test('idle history polling keeps message identity and server ordering', async () => {
  const current = session();
  const other = { ...session(), id: 'shared_other' };
  const result = await refresh([current, other], [other, current]);
  assert.equal(result[0], other);
  assert.equal(result[1], current);
  assert.equal(result[1].messages, current.messages);
});

test('new server revisions update messages and remote deletion still removes sessions', async () => {
  const current = session();
  const updated = { ...current, revision: 2, messages: [...current.messages, { role: 'assistant', content: 'new' }] };
  assert.deepEqual((await refresh([current], [updated]))[0], updated);
  assert.equal((await refresh([current], [])).length, 0);
});

test('failed optimistic messages are reconciled even when the revision is unchanged', async () => {
  const server = session();
  const optimistic = { ...server, pendingTurnId: 'failed', messages: [...server.messages, { role: 'user', content: 'unsaved' }] };
  const result = await refresh([optimistic], [server]);
  assert.deepEqual(result[0], server);
  assert.notEqual(result[0], optimistic);
});

test('active streams retain optimistic state until completion', async () => {
  const server = session();
  const optimistic = { ...server, pendingTurnId: 'running' };
  assert.equal((await refresh([optimistic], [server], true))[0], optimistic);
});
