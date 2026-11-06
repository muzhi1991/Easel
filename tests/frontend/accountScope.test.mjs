import { test } from 'node:test';
import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { installAccountScope } from '../../agents/account-scope/hooks.mjs';

test('OpenClaw resolves each exec from its server-owned session, including general mode', () => {
  let hook;
  const bindings = new Map(['one', 'two', 'general'].map((id, i) => [
    createHash('sha256').update(id).digest('hex') + '.json', JSON.stringify({ persona: ['养生', '科技', ''][i] }),
  ]));
  installAccountScope({ on(name, fn) { assert.equal(name, 'resolve_exec_env'); hook = fn; } }, {
    root: '/easel', read(path) { const value = bindings.get(path.split('/').at(-1)); if (!value) throw new Error(); return value; },
  });
  const run = id => hook({ sessionKey: `agent:main:${id}`, toolName: 'exec', host: 'gateway' }, {});
  assert.deepEqual(run('one'), { EASEL_ACCOUNT_PERSONA: '养生' });
  assert.deepEqual(run('two'), { EASEL_ACCOUNT_PERSONA: '科技' });
  assert.deepEqual(run('general'), { EASEL_ACCOUNT_PERSONA: '' });
  assert.deepEqual(run('unknown'), { EASEL_ACCOUNT_PERSONA: '_unbound' });
});
