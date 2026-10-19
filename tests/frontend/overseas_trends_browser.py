"""RSS card/browser regression with mocked APIs. Start Vite before running this file."""
import argparse
import json
from pathlib import Path
from urllib.parse import urlparse

from playwright.sync_api import sync_playwright

FRONTEND = Path(__file__).resolve().parents[2] / 'web' / 'frontend'


def check(browser, base, mobile):
    context = browser.new_context(viewport={'width': 390 if mobile else 1280, 'height': 900},
                                  is_mobile=mobile, has_touch=mobile)
    page = context.new_page()
    errors, calls, saved = [], [], []
    page.on('pageerror', lambda error: errors.append(str(error)))
    state = {'fail': False}
    def api(route):
        path = urlparse(route.request.url).path
        calls.append(path)
        if path.endswith('/api/overseas-trends'):
            if state['fail']:
                route.fulfill(status=503, body='unavailable')
                return
            groups = []
            for key, label, publisher in [('x', 'X', 'X'), ('reddit', 'Reddit', 'r/programming'), ('news', '海外资讯', 'TechCrunch')]:
                groups.append({'source': key, 'label': label, 'items': [{
                    'id': key, 'source': key, 'title': f'{label}测试标题', 'url': f'https://example.com/{key}',
                    'publisher': publisher, 'author': '作者', 'summary': '<p>中文摘要 &amp; 内容</p><script>alert(1)</script>',
                    'published_at': 1792400400, 'heat_score': 20.9285,
                    'metrics': {'impressions': 3011808, 'likes': 0} if key == 'x' else {},
                }]})
            data = {'configured': True, 'error': '', 'stale': False, 'fetched_at': 1792400400,
                    'feed_updated_at': 1792400000, 'groups': groups}
        elif path.endswith('/api/trends'):
            data = {'trends': [{'platform': 'weibo', 'label': '微博', 'ok': True,
                                'items': [{'title': '国内测试热搜', 'url': 'https://example.com', 'hot': '100万'}]}], 'updated': 1792400400}
        elif path.endswith('/api/ideas'):
            saved.append(route.request.post_data_json)
            data = {'id': 'saved', **saved[-1]}
        else:
            raise AssertionError(f'Unexpected request: {path}')
        route.fulfill(content_type='application/json', body=json.dumps(data))
    page.route('**/api/**', api)
    page.goto(base.rstrip('/') + '/__overseas_smoke__.html')
    page.get_by_text('国内测试热搜', exact=True).wait_for()
    assert not any(path.endswith('/api/overseas-trends') for path in calls)
    domestic_calls = sum(path.endswith('/api/trends') for path in calls)
    page.get_by_role('button', name='X', exact=True).click()
    x = page.get_by_role('region', name='X热点', exact=True)
    x.get_by_text('X测试标题', exact=True).wait_for()
    page.get_by_role('button', name='Reddit', exact=True).click()
    page.get_by_role('button', name='海外资讯', exact=True).click()
    page.get_by_role('region', name='海外资讯热点').get_by_text('海外资讯测试标题', exact=True).wait_for()
    assert sum(path.endswith('/api/overseas-trends') for path in calls) == 1
    assert sum(path.endswith('/api/trends') for path in calls) == domestic_calls
    assert x.get_by_text('综合分 20.93', exact=True).is_visible()
    assert '0赞' in x.inner_text()
    x.get_by_text('查看摘要', exact=True).click()
    assert x.get_by_text('中文摘要 & 内容', exact=True).is_visible()
    x.get_by_role('button', name='收藏到选题库', exact=True).click()
    x.get_by_role('button', name='已收藏', exact=True).wait_for()
    page.get_by_role('button', name='X', exact=True).click()
    page.get_by_role('button', name='X', exact=True).click()
    assert x.get_by_role('button', name='已收藏', exact=True).is_disabled()
    assert saved[0]['title'] == 'X测试标题'
    assert 'https://example.com/x' in saved[0]['note'] and '中文摘要 & 内容' in saved[0]['note']
    x.get_by_role('button', name='做内容', exact=True).click()
    assert 'https://example.com/x' in page.evaluate('window.__overseasTopic')
    state['fail'] = True
    page.get_by_role('button', name='刷新', exact=True).click()
    x.get_by_role('alert').wait_for()
    assert '当前显示上次获取的内容' in x.inner_text()
    assert page.get_by_text('国内测试热搜', exact=True).is_visible()
    assert x.get_by_text('X测试标题', exact=True).is_visible()
    assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth')
    if not mobile:
        page.screenshot(path='/tmp/easel-overseas-trends-desktop.png', full_page=True)
    else:
        page.screenshot(path='/tmp/easel-overseas-trends-mobile.png', full_page=True)
    assert not errors, errors
    context.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--url', default='http://127.0.0.1:5189')
    args = parser.parse_args()
    html = FRONTEND / '__overseas_smoke__.html'
    entry = FRONTEND / 'src' / '__overseas_smoke__.tsx'
    if html.exists() or entry.exists():
        raise RuntimeError('Smoke fixture already exists; refusing to overwrite it')
    try:
        html.write_text('<meta name="viewport" content="width=device-width, initial-scale=1"><div id="root"></div><script type="module" src="/src/__overseas_smoke__.tsx"></script>')
        entry.write_text("import { createRoot } from 'react-dom/client'; import './index.css'; import TrendsPage from './components/TrendsPage'; createRoot(document.getElementById('root')!).render(<TrendsPage onUseTopic={(text) => { (window as any).__overseasTopic = text; }} />);")
        with sync_playwright() as p:
            browser = p.chromium.launch()
            for mobile in [False, True]:
                check(browser, args.url, mobile)
            browser.close()
        print('PASS: desktop/mobile, shared fetch, domestic isolation, summaries, save/context, stale cards')
    finally:
        html.unlink(missing_ok=True)
        entry.unlink(missing_ok=True)
