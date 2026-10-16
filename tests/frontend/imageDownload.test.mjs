import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { runInNewContext } from 'node:vm';
import { test } from 'node:test';
const require = createRequire(new URL('../../web/frontend/package.json', import.meta.url));
const ts = require('typescript');
const { outputText } = ts.transpileModule(readFileSync(new URL('../../web/frontend/src/components/ImageDownload.tsx', import.meta.url), 'utf8'), {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX },
});
function setup({ fail = false } = {}) {
  const states = [];
  let cursor = 0;
  const calls = { fetch: 0, downloads: [], shares: [] };
  const exports = {};
  const jsx = (type, props) => ({ type, props });
  runInNewContext(outputText, {
    exports, File, Error, AbortSignal,
    require: id => id === 'react' ? { useState: initial => {
      const i = cursor++;
      if (!(i in states)) states[i] = initial;
      return [states[i], value => { states[i] = value; }];
    } } : { jsx, jsxs: jsx },
    fetch: async () => { calls.fetch++; if (fail) throw new Error('CORS');
      return { ok: true, blob: async () => new Blob(['image'], { type: 'image/png' }) }; },
    navigator: { canShare: () => true, share: async data => calls.shares.push(data) },
    URL: { createObjectURL: () => 'blob:test', revokeObjectURL() {} },
    window: { setTimeout() {} },
    document: { body: { append() {} }, createElement: () => ({ click() { calls.downloads.push(this.download); }, remove() {} }) },
  });
  const render = () => { cursor = 0; return exports.default({ artifact: { url: 'https://cdn.test/render?id=1', name: 'render', kind: 'image' } }); };
  const click = async index => {
    render().props.children[0].props.children[index].props.onClick();
    await new Promise(resolve => setImmediate(resolve));
  };
  return { calls, click, render, states };
}
test('download fetches the actual image and supplies an extension for URL endpoints', async () => {
  const view = setup();
  await view.click(0);
  assert.deepEqual(view.calls.downloads, ['render.png']);
  await view.click(0);
  assert.equal(view.calls.fetch, 1);
});
test('sharing is prepared first and invoked on the next user click without another fetch', async () => {
  const view = setup();
  await view.click(1);
  assert.equal(view.calls.shares.length, 0);
  assert.match(view.states[2], /再次/);
  await view.click(1);
  assert.equal(view.calls.shares.length, 1);
  assert.equal(view.calls.shares[0].files[0].name, 'render.png');
  assert.equal(view.calls.fetch, 1);
});
test('blocked remote downloads display an actionable fallback and release the button', async () => {
  const view = setup({ fail: true });
  await view.click(0);
  assert.equal(view.calls.downloads.length, 0);
  assert.equal(view.states[1], false);
  assert.match(view.states[2], /打开/);
});
