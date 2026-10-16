import { readFileSync } from 'node:fs';
import { test } from 'node:test';
import assert from 'node:assert/strict';

const source = readFileSync(new URL('../../web/frontend/src/components/ChatPage.tsx', import.meta.url), 'utf8');
const body = source.match(/const handleKeyDown = \(e: React.KeyboardEvent<HTMLTextAreaElement>\) => \{([\s\S]*?)\n  \};/)[1];
const handleKeyDown = new Function('e', 'isComposingRef', 'handleSend', 'window', body);
function press({ touch = false, shiftKey = false, composing = false, keyCode = 13, ctrlKey = false, metaKey = false } = {}) {
  let sends = 0;
  let prevented = false;
  handleKeyDown({ key: 'Enter', shiftKey, ctrlKey, metaKey,
    nativeEvent: { isComposing: composing, keyCode }, preventDefault() { prevented = true; } },
  { current: composing }, () => sends++, { matchMedia: () => ({ matches: touch }) });
  return { sends, prevented };
}
test('touch keyboard Return preserves native newline without sending', () => {
  assert.deepEqual(press({ touch: true }), { sends: 0, prevented: false });
});
test('desktop Enter sends and Shift+Enter preserves newline', () => {
  assert.deepEqual(press(), { sends: 1, prevented: true });
  assert.deepEqual(press({ shiftKey: true }), { sends: 0, prevented: false });
  assert.deepEqual(press({ ctrlKey: true }), { sends: 1, prevented: true });
  assert.deepEqual(press({ metaKey: true }), { sends: 1, prevented: true });
});
test('IME confirmation never sends on either device', () => {
  for (const touch of [false, true]) {
    assert.deepEqual(press({ touch, composing: true }), { sends: 0, prevented: false });
    assert.deepEqual(press({ touch, keyCode: 229 }), { sends: 0, prevented: false });
  }
});
