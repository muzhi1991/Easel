import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { runInNewContext } from 'node:vm';
import { test } from 'node:test';
const require = createRequire(new URL('../../web/frontend/package.json', import.meta.url));
const ts = require('typescript');
const { outputText } = ts.transpileModule(readFileSync(new URL('../../web/frontend/src/lib/download.ts', import.meta.url), 'utf8'), {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
});
function setup(fetcher, share = async () => {}) {
  const calls = { revoked: [], saved: [], urls: [], timers: new Map() };
  class TestURL extends URL {
    static createObjectURL(file) { calls.urls.push({name:file.name,size:file.size}); return 'blob:test'; }
    static revokeObjectURL(url) { calls.revoked.push(url); }
  }
  const exports = {};
  let id=0;
  runInNewContext(outputText, { exports, File, Error, TypeError, Date, AbortController, URL: TestURL,
    fetch: fetcher, navigator: { canShare: () => true, share },
    setTimeout: (fn, ms) => { calls.timers.set(++id,{fn,ms}); return id; }, clearTimeout: key => calls.timers.delete(key),
    document: { body: { append() {} }, createElement: () => ({ click() { calls.saved.push(this.download); }, remove() {} }) },
  });
  const states=[];
  const task=new exports.DownloadTask(state => states.push(state));
  const expire = ms => { for(const [key,t] of [...calls.timers]) if(t.ms===ms) { calls.timers.delete(key); t.fn(); } };
  return { ...exports, calls, task, states, expire };
}
function response(parts, headers={}) {
  return new Response(new ReadableStream({ start(controller) { for(const n of parts) controller.enqueue(new Uint8Array(n)); controller.close(); } }), {headers});
}
test('streams exact progress, assigns image extension and frees file/chunks after browser handoff', async () => {
  const v=setup(async () => response([2,3],{'content-length':'5','content-type':'image/png'}));
  await v.task.start('/file','render',false);
  assert.equal(v.states.at(-1).received,5);
  assert.equal(v.states.at(-1).total,5);
  assert.deepEqual(v.calls.saved,['render.png']);
  assert.equal(v.task.file,undefined);
  assert.equal(v.task.chunks.length,0);
  v.expire(v.SAVE_GRACE);
  assert.deepEqual(v.calls.revoked,['blob:test']);
});
test('unknown and encoded lengths remain indeterminate', async () => {
  for(const headers of [{},{'content-length':'2','content-encoding':'gzip'}]) {
    const v=setup(async () => response([3],headers));
    await v.task.start('/file','file',false);
    assert.equal(v.states.at(-1).total,undefined);
    assert.equal(v.states.at(-1).received,3);
    v.task.dispose();
  }
});
test('known oversized files never enter a reader or create a Blob URL', async () => {
  let read=false,signal;
  const v=setup(async (url,options) => {signal=options.signal;return {ok:true,headers:new Headers({'content-length':String(40*1024*1024)}),body:{getReader(){read=true;}}};});
  await v.task.start('/file','large.mp4',false);
  assert.equal(read,false);
  assert.equal(v.states.at(-1).phase,'browser');
  assert.equal(signal.aborted,true);
  assert.equal(v.calls.urls.length,0);
});
test('unknown oversized streams stop at the cap and discard all accumulated chunks', async () => {
  const v=setup(async () => response([16*1024*1024,16*1024*1024,1]));
  await v.task.start('/file','large.mp4',false);
  assert.equal(v.states.at(-1).phase,'browser');
  assert.equal(v.task.chunks.length,0);
  assert.equal(v.task.file,undefined);
  assert.equal(v.calls.urls.length,0);
});
test('cancel stops a waiting reader, drops chunks, and releases the single-task limit', async () => {
  let streamController;
  const v=setup(async () => new Response(new ReadableStream({start(c){ streamController=c; c.enqueue(new Uint8Array(7)); }})));
  const pending=v.task.start('/file','file',false);
  await new Promise(resolve=>setImmediate(resolve));
  const otherStates=[];
  const other=new v.DownloadTask(s=>otherStates.push(s));
  await other.start('/other','other',false);
  assert.equal(otherStates.at(-1).phase,'error');
  v.task.cancel();
  await pending;
  assert.equal(v.task.chunks.length,0);
  assert.equal(v.states.at(-1).phase,'cancelled');
  const next=new v.DownloadTask(()=>{});
  const nextPending=next.start('/other','other',false);
  await new Promise(resolve=>setImmediate(resolve));
  streamController.close();
  await nextPending;
  assert.equal(v.calls.saved.length,1);
  next.dispose();
});
test('share files expire and successful or cancelled sharing drops references', async () => {
  for(const outcome of ['expire','success','cancel']) {
    let shares=0;
    const v=setup(async()=>response([4],{'content-type':'image/png'}),async()=>{shares++;if(outcome==='cancel')throw Object.assign(new Error(),{name:'AbortError'});});
    await v.task.start('/image','image',true);
    assert.equal(v.states.at(-1).phase,'ready');
    assert.ok(v.task.file);
    if(outcome==='expire') v.expire(v.SHARE_TTL); else await v.task.share();
    assert.equal(v.task.file,undefined);
    assert.equal(v.task.chunks.length,0);
    assert.equal(v.calls.timers.size,0);
    await v.task.share();
    assert.equal(shares,outcome==='expire'?0:1);
  }
});
test('unmount disposal revokes object URLs and clears pending timers', async () => {
  const v=setup(async()=>response([4]));
  await v.task.start('/file','file',false);
  v.task.dispose();
  assert.equal(v.task.file,undefined);
  assert.equal(v.calls.timers.size,0);
  assert.deepEqual(v.calls.revoked,['blob:test']);
});
test('network failure frees memory and permits retry without restoring partial data', async () => {
  let fail=true;
  const v=setup(async()=>{if(fail) throw new TypeError('Failed to fetch'); return response([2]);});
  await v.task.start('/file','file',false);
  assert.equal(v.states.at(-1).phase,'error');
  fail=false;
  const next=new v.DownloadTask(()=>{});
  await next.start('/file','file',false);
  assert.deepEqual(v.calls.saved,['file']);
  next.dispose();
});
test('native local download adds attachment flag without altering external signed URLs',()=>{
  const v=setup(()=>{});
  assert.equal(v.browserDownloadUrl('/easel/api/media/video.mp4?x=1','https://easel.test'),'https://easel.test/easel/api/media/video.mp4?x=1&download=true');
  assert.equal(v.browserDownloadUrl('https://cdn.test/image?token=1','https://easel.test'),'https://cdn.test/image?token=1');
});

test('final 39 MB video can be prepared for native saving without browser handoff', async () => {
  const size = 39175553;
  let shared;
  const v = setup(async () => response([size], {'content-length': String(size), 'content-type': 'video/mp4'}),
    async data => { shared = data.files[0]; });
  await v.task.start('/api/media/final.mp4', 'final.mp4', true);
  assert.equal(v.states.at(-1).phase, 'ready');
  assert.equal(v.task.file.size, size);
  await v.task.share();
  assert.equal(shared.size, size);
  assert.equal(shared.type, 'video/mp4');
  assert.equal(v.task.file, undefined);
});

test('native sharing remains bounded for both declared and unknown large files', async () => {
  for (const known of [true, false]) {
    const v = setup(async () => response([32*1024*1024, 32*1024*1024, 1],
      known ? {'content-length': String(64*1024*1024+1)} : {}));
    await v.task.start('/large.mp4', 'large.mp4', true);
    assert.equal(v.states.at(-1).phase, 'browser');
    assert.equal(v.task.file, undefined);
    assert.equal(v.task.chunks.length, 0);
    assert.equal(v.calls.urls.length, 0);
  }
});
