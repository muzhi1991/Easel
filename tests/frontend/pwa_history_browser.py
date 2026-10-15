"""Production-shell regression with mocked APIs and real Service Worker/IndexedDB.

Serve web/frontend/dist on localhost:5179 before running. No real messages are sent.
"""
import argparse
import json
import subprocess
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[2]


def app_check(browser, url, mobile):
    context = browser.new_context(viewport={"width": 390 if mobile else 1440, "height": 844 if mobile else 900},
                                  is_mobile=mobile, has_touch=mobile)
    context.add_init_script("localStorage.setItem('easel_onboarding_seen','1')")
    if browser.browser_type.name == 'webkit':
        context.add_init_script("Object.defineProperty(navigator,'onLine',{get:()=>localStorage.getItem('test-offline')!=='1'})")
    page = context.new_page()
    errors = []
    page.on('pageerror', lambda error: errors.append(str(error)))
    session = {'id': 'cached', 'title': 'Cached conversation', 'source': 'server', 'revision': 1,
               'historyEpoch': 0, 'created': 1,
               'messages': [{'role': 'assistant', 'content': f'Cached message {i}'} for i in range(123)]}
    details = []
    offline = False
    deleted = False

    def summary():
        return {**{k: v for k, v in session.items() if k != 'messages'}, 'messageCount': len(session['messages'])}

    def api(route):
        if offline:
            route.abort('internetdisconnected')
            return
        path = urlparse(route.request.url).path
        if path.endswith('/api/conversations'):
            data = [] if deleted else [summary()]
        elif path.endswith('/api/conversations/cached'):
            q = parse_qs(urlparse(route.request.url).query)
            details.append(q)
            if 'epoch' in q and int(q['epoch'][0]) != session['historyEpoch']:
                route.fulfill(status=409, content_type='application/json', body='{"detail":"history replaced"}')
                return
            total = len(session['messages'])
            end = min(int(q.get('before', [total])[0]), total)
            start = max(0, end - 50)
            if 'after' in q:
                start = int(q['after'][0]) + 1
                end = min(total, start + 50)
            data = {**summary(), 'messageStart': start, 'messages': session['messages'][start:end]}
        elif path.endswith('/api/status'):
            data = {'gateway': True, 'transport': 'api', 'personas': []}
        elif path.endswith('/api/settings/bootstrap'):
            data = {'modelConfigured': True}
        elif path.endswith('/api/upload/limits'):
            data = {'max_mb': 50}
        else:
            route.fulfill(status=404, content_type='application/json', body='{}')
            return
        route.fulfill(content_type='application/json', body=json.dumps(data))

    server = None
    if browser.browser_type.name == 'webkit':
        # WebKit routes controlled requests differently from Chromium. Use real
        # HTTP API fixtures so SW behavior is tested, not Playwright interception.
        class Handler(SimpleHTTPRequestHandler):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, directory=str(ROOT / 'web/frontend/dist'), **kwargs)
            def log_message(self, *args):
                pass
            def do_GET(self):
                if offline:
                    self.send_error(503)
                    return
                if '/api/' not in self.path:
                    return super().do_GET()
                handler = self
                class Route:
                    request = SimpleNamespace(url='http://test' + handler.path)
                    def fulfill(self, status=200, content_type='application/json', body=''):
                        payload = body.encode()
                        handler.send_response(status)
                        handler.send_header('Content-Type', content_type)
                        handler.send_header('Content-Length', str(len(payload)))
                        handler.end_headers()
                        handler.wfile.write(payload)
                    def abort(self, *_):
                        handler.send_error(503)
                api(Route())
        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        url = f'http://127.0.0.1:{server.server_port}/'
    else:
        context.route('**/api/**', api)

    def open_chat():
        page.locator('.session-item-title').filter(has_text='Cached conversation').wait_for(state='attached')
        if mobile:
            page.get_by_role('button', name='打开导航').click()
        page.get_by_text('Cached conversation', exact=True).click()

    page.goto(url, wait_until='domcontentloaded')
    page.evaluate('navigator.serviceWorker.ready.then(() => true)')
    page.wait_for_function('!!navigator.serviceWorker.controller')
    assert not details, 'home must not prefetch messages'
    open_chat()
    page.get_by_text('Cached message 122', exact=True).wait_for()
    assert len(details) == 1 and 'after' not in details[0]
    page.reload(wait_until='domcontentloaded')
    open_chat()
    page.get_by_text('Cached message 122', exact=True).wait_for()
    page.wait_for_timeout(300)
    assert len(details) == 1, 'reload should restore cached messages without a full page request'

    session['messages'] += [{'role': 'assistant', 'content': 'Appended 123'}, {'role': 'assistant', 'content': 'Appended 124'}]
    session['revision'] += 1
    page.evaluate("window.dispatchEvent(new Event('focus'))")
    page.get_by_text('Appended 124', exact=True).wait_for()
    assert details[-1].get('after') == ['122'], details
    page.get_by_role('button', name='加载更早消息').click()
    page.get_by_text('Cached message 23', exact=True).wait_for()
    requests_before = len(details)

    # Restart the page offline, with only the real SW shell and IndexedDB available.
    offline = True
    if server:
        # Playwright WebKit's forced offline mode aborts navigation before SW.
        # Fail every real HTTP request instead, including HTML/assets, and
        # dispatch the browser connectivity event for the app's read-only UI.
        page.evaluate("localStorage.setItem('test-offline','1'); window.dispatchEvent(new Event('offline'))")
    else:
        context.set_offline(True)
    page.reload(wait_until='domcontentloaded')
    open_chat()
    page.get_by_text('Cached message 23', exact=True).wait_for()
    page.get_by_text('Appended 124', exact=True).wait_for()
    assert len(details) == requests_before
    page.locator('textarea').fill('offline draft')
    assert page.get_by_title('发送', exact=True).is_disabled()
    page.locator('textarea').fill('')
    page.screenshot(path=f'/tmp/easel-pwa-{"mobile" if mobile else "desktop"}.png', animations='disabled')
    cache_urls = page.evaluate('''async () => {
      const urls=[]; for (const key of await caches.keys()) {
        for (const request of await (await caches.open(key)).keys()) urls.push(request.url);
      } return urls;
    }''')
    assert cache_urls and not any('/api/' in item for item in cache_urls)

    # A retry in a different client replaced history while this client was offline.
    session['historyEpoch'] += 1
    session['revision'] += 2
    session['messages'] = [{'role': 'assistant', 'content': 'Replacement history'}]
    offline = False
    if server:
        page.evaluate("localStorage.removeItem('test-offline'); window.dispatchEvent(new Event('online'))")
    else:
        context.set_offline(False)
    page.get_by_text('Replacement history', exact=True).wait_for()
    assert page.get_by_text('Cached message 23', exact=True).count() == 0
    assert 'after' not in details[-1], details[-1]

    deleted = True
    page.evaluate("window.dispatchEvent(new Event('focus'))")
    page.wait_for_function("!Array.from(document.querySelectorAll('.session-item-title')).some(el => el.textContent === 'Cached conversation')")
    page.reload(wait_until='domcontentloaded')
    page.wait_for_timeout(300)
    assert page.get_by_text('Cached conversation', exact=True).count() == 0
    assert not errors, errors
    if not mobile and browser.browser_type.name == 'chromium':
        cdp = context.new_cdp_session(page)
        install_errors = cdp.send('Page.getInstallabilityErrors')['installabilityErrors']
        assert not install_errors, install_errors
    context.close()
    if server:
        server.shutdown()
        server.server_close()
    print('app offline/pagination/epoch/deletion:', 'mobile' if mobile else 'desktop', 'PASS')


def cache_check(browser, url):
    # Exercise the real cache module against native IndexedDB, including cross-tab races.
    transpile = """const fs=require('fs'); const ts=require('./web/frontend/node_modules/typescript');
const out={}; for(const name of ['sessionHistory','historyCache']) out[name]=ts.transpileModule(fs.readFileSync('web/frontend/src/lib/'+name+'.ts','utf8'), {compilerOptions:{target:ts.ScriptTarget.ES2022,module:ts.ModuleKind.CommonJS}}).outputText;
process.stdout.write(JSON.stringify(out));"""
    modules = json.loads(subprocess.check_output(['node', '-e', transpile], cwd=ROOT))
    context = browser.new_context()
    context.route('**/cache-test/', lambda route: route.fulfill(content_type='text/html', body='<html>cache test</html>'))
    page = context.new_page()
    page.goto(url + 'cache-test/')
    page.evaluate('''modules => {
      const history={}; new Function('exports', modules.sessionHistory)(history);
      const cache={}; new Function('exports','require', modules.historyCache)(cache, () => history);
      window.cache=cache;
    }''', modules)
    page.evaluate('''async () => {
      const assert = (ok, message) => { if(!ok) throw Error(message); };
      const s={id:'race',source:'server',title:'Race',created:1,revision:1,historyEpoch:0,messageCount:100,messages:[]};
      const page=(start,end,revision=1,epoch=0) => ({...s,revision,historyEpoch:epoch,messageStart:start,messageCount:Math.max(100,end),
        messages:Array.from({length:end-start},(_,i)=>({role:'assistant',content:String(start+i)}))});
      await cache.cacheSummaries([s]);
      await Promise.all([cache.cacheMessagePage(page(50,100)),cache.cacheMessagePage(page(0,50))]);
      let loaded=await cache.readCachedHistory('race');
      assert(loaded.messages.length===100 && loaded.messageStart===0,'concurrent pages must merge');
      assert((await cache.readCachedSummaries())[0].messages.length===0,'summaries contain no bodies');
      await cache.cacheMessagePage(page(75,100));
      assert((await cache.readCachedHistory('race')).messages.length===100,'overlap must not duplicate');
      await cache.cacheSummaries([{...s,revision:3,historyEpoch:1,messageCount:1}]);
      await cache.cacheMessagePage(page(50,100));
      assert(!await cache.readCachedHistory('race'),'old epoch resurrected');
      await cache.cacheMessagePage({...page(0,1,3,1),messageCount:1});
      assert((await cache.readCachedHistory('race')).messages.length===1,'new epoch missing');
      await cache.cacheSummaries([]);
      await cache.cacheMessagePage(page(0,50));
      assert(!await cache.readCachedHistory('race'),'deleted history resurrected');
      await cache.cacheSummaries([s]);
      assert(!(await cache.readCachedSummaries()).some(s=>s.id==='race'),'late list resurrected deletion');
      // An oversized page should not prevent other conversations from being cached.
      const huge={...s,id:'huge',messageCount:1};
      await cache.cacheSummaries([huge]);
      await cache.cacheMessagePage({...huge,messageStart:0,messages:[{role:'assistant',content:'x'.repeat(51*1024*1024)}]});
      assert(!await cache.readCachedHistory('huge'),'cache size limit not applied');
    }''')
    # The cache is optional: browsers denying IndexedDB must still resolve operations.
    disabled = context.new_page()
    disabled.goto(url + 'cache-test/')
    disabled.evaluate('''modules => {
      Object.defineProperty(window, 'indexedDB', { get() { throw Error('storage denied'); } });
      const history={}; new Function('exports', modules.sessionHistory)(history);
      const cache={}; new Function('exports','require', modules.historyCache)(cache, () => history);
      window.cache=cache;
    }''', modules)
    assert disabled.evaluate('cache.readCachedSummaries()') == []
    assert disabled.evaluate("cache.readCachedHistory('race')") is None
    context.close()
    print('native IndexedDB races/epoch/deletion/quota: PASS')


def update_check(browser, url):
    # Change only the built worker version, then restore it; app assets remain identical.
    worker = ROOT / 'web/frontend/dist/sw.js'
    original = worker.read_text()
    busy_other = False
    context = browser.new_context()
    context.add_init_script("localStorage.setItem('easel_onboarding_seen','1')")
    def api(route):
        path = urlparse(route.request.url).path
        if path.endswith('/conversations'):
            data = []
            if busy_other and route.request.frame.page == other:
                data = [{'id': 'busy', 'title': 'Busy', 'source': 'server', 'revision': 1,
                         'historyEpoch': 0, 'messageCount': 0, 'created': 1, 'pendingTurnId': 'running'}]
        elif path.endswith('/status') or path.endswith('/settings/bootstrap'):
            data = {'gateway': True, 'transport': 'api', 'personas': [], 'modelConfigured': True}
        else:
            route.fulfill(status=404, content_type='application/json', body='{}')
            return
        route.fulfill(content_type='application/json', body=json.dumps(data))
    context.route('**/api/**', api)
    page = context.new_page()
    other = context.new_page()
    try:
        for tab in [page, other]:
            tab.goto(url, wait_until='domcontentloaded')
            tab.evaluate('navigator.serviceWorker.ready.then(() => true)')
            tab.wait_for_function('!!navigator.serviceWorker.controller')
        old_caches = page.evaluate('caches.keys()')
        # A draft in another tab must block an update initiated in this tab.
        other.evaluate("document.body.insertAdjacentHTML('beforeend', '<textarea id=update-draft>unfinished draft</textarea>')")
        worker.write_text(original.replace("const VERSION = '", "const VERSION = 'update-test-"))
        page.evaluate('navigator.serviceWorker.getRegistration().then(reg => reg.update()).then(() => true)')
        page.get_by_role('button', name='更新并刷新').wait_for()
        page.get_by_role('button', name='更新并刷新').click()
        page.get_by_text('请先结束其他窗口的对话，并发送或清空草稿后更新。').wait_for()
        assert page.evaluate('caches.keys()') != old_caches, 'new worker should be staged'
        assert other.locator('#update-draft').input_value() == 'unfinished draft'
        other.evaluate("document.querySelector('#update-draft').remove()")
        busy_other = True
        other.evaluate("window.dispatchEvent(new Event('focus'))")
        other.get_by_role('button', name='对话结束后可更新').wait_for()
        assert other.get_by_role('button', name='对话结束后可更新').is_disabled()
        page.get_by_role('button', name='更新并刷新').click()
        page.get_by_role('button', name='更新并刷新').wait_for()
        assert page.evaluate('navigator.serviceWorker.getRegistration().then(r=>!!r.waiting)')
        busy_other = False
        other.evaluate("window.dispatchEvent(new Event('focus'))")
        other.get_by_role('button', name='更新并刷新').wait_for()
        page.get_by_role('button', name='更新并刷新').click()
        page.wait_for_function("!document.body.textContent.includes('新版本已准备好')")
        page.wait_for_function("caches.keys().then(keys => keys.length === 1 && keys[0].includes('update-test-'))")
        assert other.locator('#update-draft').count() == 0
        assert page.evaluate('navigator.serviceWorker.controller.state') == 'activated'
    finally:
        worker.write_text(original)
        context.close()
    print('PWA staged update / cross-tab draft protection / cache cleanup: PASS')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--url', default='http://127.0.0.1:5179/')
    parser.add_argument('--browser', choices=['chromium', 'webkit'], default='chromium')
    args = parser.parse_args()
    with sync_playwright() as p:
        browser = getattr(p, args.browser).launch()
        cache_check(browser, args.url)
        app_check(browser, args.url, False)
        app_check(browser, args.url, True)
        if args.browser == 'chromium':
            update_check(browser, args.url)
        browser.close()
