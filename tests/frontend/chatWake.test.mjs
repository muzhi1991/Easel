import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { runInNewContext } from 'node:vm';
import { test } from 'node:test';
const require = createRequire(new URL('../../web/frontend/package.json', import.meta.url));
const ts = require('typescript');
const source = readFileSync(new URL('../../web/frontend/src/lib/api.ts', import.meta.url), 'utf8');
const parsed = ts.createSourceFile('api.ts', source, ts.ScriptTarget.Latest, true);
const declaration = parsed.statements.find(n => ts.isFunctionDeclaration(n) && n.name?.text === 'streamChat');
const { outputText } = ts.transpileModule(declaration.getText(parsed).replace('export ', '') + '\nstreamChat;', { compilerOptions: { target: ts.ScriptTarget.ES2022 } });
const tick = () => new Promise(resolve => setImmediate(resolve));
for (const trigger of ['visibilitychange', 'online', 'pageshow', 'cancel']) {
  test(trigger === 'cancel' ? 'explicit cancellation prevents wake reconnection' : `wake via ${trigger} replaces stalled stream and resumes after last event without resubmitting`, async () => {
    const document = new EventTarget(); document.visibilityState = 'visible';
    const window = new EventTarget();
    const requests = [], tokens = [], errors = [], activities = [];
    let done = 0;
    const streamChat = runInNewContext(outputText, {
      AbortController, TextDecoder, Date, Error, setTimeout, clearTimeout, document, window, BASE: '', agentSessionId: id => id,
      fetch: async (url, options) => {
        requests.push({url, method: options.method});
        return new Response(new ReadableStream({start(controller) {
          if (requests.length === 1) {
            controller.enqueue(new TextEncoder().encode('id: 1\nevent: token\ndata: "before"\n\n'));
            options.signal.addEventListener('abort', () => controller.error(new DOMException('aborted', 'AbortError')), {once:true});
          } else {
            controller.enqueue(new TextEncoder().encode('id: 2\nevent: token\ndata: "after"\n\nid: 3\nevent: done\ndata: {}\n\n')); controller.close();
          }
        }}));
      },
    });
    const ctl = streamChat('hello', undefined, 'session', text => tokens.push(text), () => done++, error => errors.push(error), undefined, status => activities.push(status), undefined, 'turn');
    try {
      await tick();
      if (trigger === 'cancel') {
        ctl.abort(); await tick();
        window.dispatchEvent(new Event('online')); await tick();
        assert.equal(requests.length, 1, 'explicit cancellation must not reconnect');
        assert.equal(done, 0); assert.deepEqual(errors, []);
        return;
      }
      document.visibilityState = 'hidden'; document.dispatchEvent(new Event('visibilitychange'));
      document.visibilityState = 'visible';
      (trigger === 'visibilitychange' ? document : window).dispatchEvent(new Event(trigger));
      for(let i=0;i<10;i++) await tick();
      assert.equal(requests.length, 2, 'wake must replace a stalled connection');
      assert.equal(requests[0].method, 'POST');
      assert.match(requests[1].url, /jobs\/turn\/stream\?after=1$/);
      assert.ok(activities.some(s => s.includes('已重新连接')));
      assert.deepEqual(tokens, ['before','after']); assert.equal(done,1); assert.deepEqual(errors,[]);
      window.dispatchEvent(new Event('online')); await tick(); assert.equal(requests.length,2,'completed streams must remove wake listeners');
    } finally { ctl.abort(); }
  });
}
