"""Run Vite, then .venv/bin/python tests/frontend/download_browser.py [url].

Exercises the real download controls with a 39 MB response and simulated PWA /
native sharing APIs. This does not emulate the phone's OS share sheet.
All application APIs are mocked; no live conversation is modified.
"""
import json
import sys
from urllib.parse import urlparse

from playwright.sync_api import sync_playwright


def check(browser, url):
    context = browser.new_context(viewport={"width": 390, "height": 844},
                                  is_mobile=True, has_touch=True)
    page = context.new_page()
    page.add_init_script("""
      localStorage.setItem('easel_onboarding_seen', '1');
      Object.defineProperty(navigator, 'standalone', {value: true});
      navigator.canShare = data => data.files[0].type === 'video/mp4';
      navigator.share = async data => {
        if (!navigator.userActivation.isActive) throw new Error('Missing user activation');
        window.savedFile = {size: data.files[0].size, name: data.files[0].name};
      };
      Object.defineProperty(navigator, 'clipboard', {value: {
        writeText: async text => {
          if (window.denyClipboard) throw new Error('Clipboard denied');
          window.copiedLink = text;
        }
      }});
    """)
    size = 39175553
    session = {"id": "shared_download_test", "source": "server", "revision": 1,
               "title": "Download regression", "created": 1, "historyEpoch": 0,
               "messages": [{"role": "assistant", "content": "[final.mp4](/api/media/project/final.mp4)"}]}
    summary = {**{key: value for key, value in session.items() if key != "messages"}, "messageCount": 1}

    def api(route):
        path = urlparse(route.request.url).path
        if path == "/api/media/project/final.mp4":
            route.fulfill(content_type="video/mp4", body=bytes(size))
            return
        if path == "/api/conversations":
            data = [summary]
        elif path == "/api/conversations/shared_download_test":
            data = {**summary, "messageStart": 0, "messages": session["messages"]}
        elif path == "/api/status":
            data = {"gateway": True, "transport": "api", "personas": []}
        elif path == "/api/settings/bootstrap":
            data = {"modelConfigured": True}
        elif path == "/api/upload/limits":
            data = {"max_mb": 50}
        else:
            route.fulfill(status=404, content_type="application/json", body='{}')
            return
        route.fulfill(content_type="application/json", body=json.dumps(data))

    page.route("**/api/**", api)
    page.goto(url, wait_until="domcontentloaded")
    page.locator('.session-item-title').first.wait_for(state='attached')
    page.get_by_role("button", name="打开导航").click()
    page.get_by_text("Download regression", exact=True).click()
    control = page.locator('.artifact-gallery .download-control')
    control.wait_for()
    draft = page.locator('textarea').last
    draft.fill('Download return must preserve this draft')
    # PWA raw-media navigation must retain an app-owned return control.
    page.get_by_role("link", name="打开 ↗").click()
    dialog = page.get_by_role("dialog", name="文件预览与保存")
    dialog.wait_for(timeout=2000)
    assert dialog.locator('video').count() == 1
    assert len(context.pages) == 1, 'preview must not open a bare file tab'

    dialog.get_by_role("button", name="返回 Easel").click()
    assert page.url.rstrip('/') == url.rstrip('/')
    assert draft.input_value() == 'Download return must preserve this draft'
    assert control.get_by_role("button", name="下载", exact=True).count() == 0
    control.get_by_role("button", name="准备分享/保存", exact=True).click()
    control.get_by_role("button", name="分享/保存", exact=True).click(timeout=15000)
    assert page.evaluate("window.savedFile") == {"size": size, "name": "final.mp4"}
    control.get_by_role("button", name="复制链接到 Safari 下载").click()
    page.wait_for_function("window.copiedLink")
    assert page.evaluate("window.copiedLink").endswith('/api/media/project/final.mp4?download=true')
    page.evaluate("window.denyClipboard = true")
    control.get_by_role("button", name="复制链接到 Safari 下载").click()
    field = control.get_by_role("textbox", name="下载链接")
    field.wait_for()
    assert field.input_value().endswith('?download=true')
    # A failed browser handoff must leave native saving reachable.
    page.route("**/api/media/project/final.mp4?download=true", lambda route: route.abort())
    assert control.get_by_role("link", name="使用浏览器下载").count() == 0
    control.get_by_role("button", name="准备分享/保存", exact=True).click()
    control.get_by_role("button", name="分享/保存", exact=True).click(timeout=15000)
    assert page.evaluate("window.savedFile.size") == size
    context.close()


if __name__ == "__main__":
    with sync_playwright() as playwright:
        for engine in (playwright.chromium, playwright.webkit):
            browser = engine.launch()
            check(browser, sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:5178")
            print(f"PASS {engine.name}: PWA video saving, clipboard fallback, browser fallback recovery")
            browser.close()
