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

const historySource = readFileSync(new URL('../../web/frontend/src/lib/sessionHistory.ts', import.meta.url), 'utf8');
const history = {};
runInNewContext(ts.transpileModule(historySource, {
  compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.CommonJS },
}).outputText, { exports: history });
const plain = value => JSON.parse(JSON.stringify(value));
const summary = value => ({ ...value, messages: [], historyLoaded: false });

const session = () => ({ id: 'shared_test', source: 'server', revision: 1, historyEpoch: 0, messageCount: 1, messageStart: 0, historyLoaded: true, messages: [{ role: 'assistant', content: 'history' }] });
async function refresh(current, incoming, streaming = false) {
  let result;
  const context = {
    mergeSessionSummary: history.mergeSessionSummary,
    sessionsRef: { current }, historyBusy: { current: new Set() },
    streamCtl: { current: streaming ? { shared_test: {} } : {} },
    loadSharedSessions: async () => structuredClone(incoming.map(summary)), loadSessions: () => [],
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

test('new server summaries preserve cached messages for incremental loading and still remove deletions', async () => {
  const current = session();
  const updated = { ...current, revision: 2, messageCount: 2 };
  const result = (await refresh([current], [updated]))[0];
  assert.equal(result.messages, current.messages);
  assert.equal(result.messageCount, 2);
  assert.equal((await refresh([current], [])).length, 0);
});

test('failed optimistic messages are reconciled even when the revision is unchanged', async () => {
  const server = session();
  const optimistic = { ...server, optimistic: true, pendingTurnId: 'failed', messages: [...server.messages, { role: 'user', content: 'unsaved' }] };
  const result = await refresh([optimistic], [server]);
  assert.deepEqual(plain(result[0]), server);
  assert.notEqual(result[0], optimistic);
});

test('active streams retain optimistic state until completion', async () => {
  const server = session();
  const optimistic = { ...server, pendingTurnId: 'running' };
  assert.equal((await refresh([optimistic], [server], true))[0], optimistic);
});


test('older and appended pages are contiguous, deduplicated, and keep absolute offsets', () => {
  const current = { ...session(), messageStart: 50, messageCount: 52, messages: [{ content: '50' }, { content: '51' }] };
  const older = { ...current, messageStart: 0, messages: Array.from({ length: 50 }, (_, i) => ({ content: String(i) })) };
  const merged = history.mergeMessagePage(current, older, 'older');
  assert.equal(merged.messageStart, 0);
  assert.equal(merged.messages.length, 52);
  assert.equal(history.mergeMessagePage(merged, older, 'older'), merged);
  const next = { ...current, revision: 2, messageCount: 53, messageStart: 52, messages: [{ content: '52' }] };
  const appended = history.mergeMessagePage(merged, next, 'newer');
  assert.equal(appended.messages.length, 53);
  assert.equal(appended.messages[52].content, '52');
  assert.equal(history.mergeMessagePage(appended, next, 'newer'), appended);
});

test('retry invalidates cached history, and stale pages cannot resurrect it', () => {
  const current = session();
  const retried = { ...summary(current), revision: 3, historyEpoch: 1 };
  const reset = history.mergeSessionSummary(current, retried);
  assert.equal(reset.historyLoaded, false);
  assert.equal(reset.messages.length, 0);
  assert.equal(history.mergeMessagePage(reset, current, 'latest'), reset);
  assert.equal(history.mergeMessagePage(reset, current, 'older'), reset);
});

test('same-size metadata edits do not download or reserialize cached message bodies', () => {
  const current = session();
  current.messages[0].toJSON = () => { throw Error('must not serialize message bodies'); };
  const renamed = history.mergeSessionSummary(current, { ...summary(current), revision: 2, title: 'renamed' });
  assert.equal(renamed.messages, current.messages);
  assert.equal(renamed.historyLoaded, true);
});

test('a page from another session or before an optimistic send cannot overwrite the active window', () => {
  const current = { ...session(), optimistic: true };
  assert.equal(history.mergeMessagePage(current, { ...session(), revision: 2 }, 'latest'), current);
  assert.equal(history.mergeMessagePage(session(), { ...session(), id: 'other' }, 'latest').id, current.id);
});
