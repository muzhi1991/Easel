"""Run Vite, then .venv/bin/python tests/frontend/mobile_keyboard_browser.py [url].

Real app/CSS with mocked APIs and VisualViewport events. Covers clipping and
resume geometry; does not emulate an OS keyboard or third-party app callback.
"""
import json
import sys
from urllib.parse import urlparse

from playwright.sync_api import sync_playwright


def check(browser, url):
    context = browser.new_context(viewport={"width": 390, "height": 844}, is_mobile=True, has_touch=True)
    page = context.new_page()
    page.add_init_script("""
      localStorage.setItem('easel_onboarding_seen', '1');
      const viewport = new EventTarget();
      Object.assign(viewport, {height: 844, width: 390, offsetTop: 0, offsetLeft: 0, scale: 1});
      Object.defineProperty(window, 'visualViewport', {value: viewport});
      window.setViewport = (values, event = 'resize') => {
        Object.assign(viewport, values);
        if (event) viewport.dispatchEvent(new Event(event));
      };
    """)
    sessions = [{"id": f"shared_keyboard_{i}", "source": "server", "revision": 1,
                 "title": f"Keyboard conversation {i}", "created": i + 1, "historyEpoch": 0,
                 "messageCount": 1} for i in range(20)]

    def api(route):
        path = urlparse(route.request.url).path
        if path == '/api/conversations':
            data = sessions
        elif path.startswith('/api/conversations/'):
            data = {**sessions[0], 'messageStart': 0, 'messages': [{'role': 'assistant', 'content': 'History\n\n' * 80}]}
        elif path == '/api/status':
            data = {'gateway': True, 'transport': 'api', 'personas': []}
        elif path == '/api/settings/bootstrap':
            data = {'modelConfigured': True}
        elif path == '/api/upload/limits':
            data = {'max_mb': 50}
        else:
            route.fulfill(status=404, content_type='application/json', body='{}')
            return
        route.fulfill(content_type='application/json', body=json.dumps(data))

    page.route('**/api/**', api)
    page.goto(url, wait_until='domcontentloaded')
    page.locator('.session-item-title').first.wait_for(state='attached')
    page.get_by_role('button', name='打开导航').click()
    page.locator('.session-item').last.hover()
    page.locator('.session-item').last.get_by_title('重命名', exact=True).click()
    page.evaluate('setViewport({height: 430})')
    page.wait_for_timeout(900)

    def visible(selector):
        return page.locator(selector).evaluate("""el => {
          const r = el.getBoundingClientRect(), v = visualViewport;
          let top = v.offsetTop, bottom = top + v.height;
          for (let p = el.parentElement; p; p = p.parentElement) {
            if (/(auto|scroll|hidden|clip)/.test(getComputedStyle(p).overflowY)) {
              const b = p.getBoundingClientRect(); top = Math.max(top, b.top); bottom = Math.min(bottom, b.bottom);
            }
          }
          return {ok: r.top >= top - 1 && r.bottom <= bottom + 1, top: r.top, bottom: r.bottom, clipTop: top, clipBottom: bottom};
        }""")

    result = visible('.session-rename-input')
    assert result['ok'], f'rename field clipped by keyboard/layout: {result}'
    page.locator('.session-rename-input').press('Escape')
    page.evaluate('setViewport({height: 844})')
    # Escape closes the naming dialog; navigation remains available beneath it.
    if page.get_by_role('button', name='打开导航').get_attribute('aria-expanded') != 'true':
        page.get_by_role('button', name='打开导航').click()
    page.locator('.session-item-title').first.click()
    field = page.locator('.chat-input')
    field.fill('Unsent voice-input draft')
    for i in range(8):
        page.evaluate('setViewport({height: 430, offsetTop: 0})')
        page.wait_for_timeout(100)
        # iOS can pan independently of resize after focus/keyboard animation.
        page.evaluate('setViewport({offsetTop: 140}, "scroll")')
        page.wait_for_timeout(100)
        header = visible('.mobile-header')
        composer = visible('.composer')
        assert header['ok'] and composer['ok'], f'keyboard cycle {i}: header={header}, composer={composer}'
        page.evaluate('setViewport({height: 844, offsetTop: 0})')
        page.wait_for_timeout(100)

    # A suspended WebView may briefly report zero, then recover without resize.
    page.evaluate("""() => {
      setViewport({height: 0});
      window.dispatchEvent(new PageTransitionEvent('pageshow', {persisted: true}));
      setTimeout(() => setViewport({height: 430, offsetTop: 80}, null), 150);
    }""")
    page.wait_for_timeout(1000)
    result = visible('.composer')
    assert result['ok'], f'resume left composer outside viewport: {result}'
    assert field.input_value() == 'Unsent voice-input draft', 'resume must preserve draft'
    page.evaluate('setViewport({height: 844, offsetTop: 0})')
    page.wait_for_timeout(100)
    assert visible('.composer')['ok']
    context.close()


if __name__ == '__main__':
    with sync_playwright() as playwright:
        for engine in (playwright.chromium, playwright.webkit):
            browser = engine.launch()
            check(browser, sys.argv[1] if len(sys.argv) > 1 else 'http://127.0.0.1:5179')
            print(f'PASS {engine.name}: rename clipping, repeated keyboard/pan, delayed resume, draft retention')
            browser.close()
