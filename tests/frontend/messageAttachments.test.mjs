import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { runInNewContext } from 'node:vm';
import { test } from 'node:test';
const require = createRequire(new URL('../../web/frontend/package.json', import.meta.url));
const ts = require('typescript');
const { outputText } = ts.transpileModule(readFileSync(new URL('../../web/frontend/src/components/MessageBubble.tsx', import.meta.url), 'utf8'), {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX },
});
const exports = {};
const jsx = (type, props) => ({ type, props });
runInNewContext(outputText, { exports, require: id => id === 'react'
  ? { useMemo: fn => fn() } : id === 'react/jsx-runtime' ? { jsx, jsxs: jsx }
  : id === './MessageAttachments' ? { __esModule: true, default: 'attachments' } : {} });
function nodes(tree, type) {
  if (!tree || typeof tree !== 'object') return [];
  const children = tree.props?.children;
  return [...(tree.type === type ? [tree] : []), ...(Array.isArray(children) ? children.flat(Infinity) : [children]).flatMap(child => nodes(child, type))];
}
const files = [{ id: '1', name: 'video.mp4', path: '_inbox/scope/video.mp4' }];
test('attachment-only user turns remain visible in loaded history', () => {
  const tree = exports.default({ message: { role: 'user', content: '', attachments: files } });
  assert.ok(tree);
  assert.equal(nodes(tree, 'attachments')[0].props.files, files);
});
test('text and attachment references stay together on the original user turn', () => {
  const tree = exports.default({ message: { role: 'user', content: '处理这个视频', attachments: files } });
  assert.equal(nodes(tree, 'attachments').length, 1);
  assert.ok(nodes(tree, 'div').some(node => node.props.children === '处理这个视频'));
});
test('truly empty turns stay hidden and plain text does not gain an attachment container', () => {
  assert.equal(exports.default({ message: { role: 'user', content: ' ' } }), null);
  assert.equal(nodes(exports.default({ message: { role: 'user', content: '你好' } }), 'attachments').length, 0);
});
