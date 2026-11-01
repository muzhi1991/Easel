import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { runInNewContext } from 'node:vm';
import { webcrypto } from 'node:crypto';
import { test } from 'node:test';

const require = createRequire(new URL('../../web/frontend/package.json', import.meta.url));
const ts = require('typescript');
const React = require('react');
const { renderToString } = require('react-dom/server');
function load(path, crypto) {
  const source = readFileSync(new URL(`../../web/frontend/src/${path}`, import.meta.url), 'utf8');
  const { outputText } = ts.transpileModule(source, {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022,
      jsx: ts.JsxEmit.ReactJSX },
  });
  const exports = {};
  runInNewContext(outputText, { exports, crypto, URL, require: id => {
    if (id === 'react' || id === 'react/jsx-runtime') return require(id);
    if (id === '../lib/artifacts') return load('lib/artifacts.ts', crypto);
    return { __esModule: true, default: () => null, IconOutputs: () => null, IconChevron: () => null };
  } });
  return exports;
}

for (const secure of [false, true]) {
  test(`HTML conversation preview renders with randomUUID ${secure ? 'available' : 'unavailable (LAN HTTP)'}`, () => {
    const crypto = secure ? webcrypto : { getRandomValues: webcrypto.getRandomValues.bind(webcrypto) };
    const Gallery = load('components/ArtifactGallery.tsx', crypto).default;
    const html = renderToString(React.createElement(Gallery, { artifacts: [{
      kind: 'html', name: 'card.html', url: '/api/media/project/card.html',
    }] }));
    assert.match(html, /正在加载预览/);
    assert.match(html, /card.html/);
  });
}
