"""Offline integration: existing rich subscriptions use upstream collectors and cache."""
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread
import json

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from easel import overseas_trends as rss
from easel.trends import service as service_module
from easel.trends import management
from easel.trends.protocol import CollectorError, MAX_BYTES, validate_payload, utc_now
from easel.trends.rss import parse_feed
from easel.trends.service import TrendService
from easel.trends.sources import load_sources


def item(identity='a', source='x', heat='', **fields):
    values = {'title': '测试标题', 'link': f'https://example.com/{identity}', 'guid': identity,
              'source': source, 'publisher': 'X', 'author': 'Author',
              'pubDate': 'Mon, 19 Oct 2026 09:00:00 +0000', 'description': '中文摘要', **fields}
    return '<item>' + ''.join(f'<{key}>{value}</{key}>' for key, value in values.items()) + f'<heat>{heat}</heat></item>'


def feed(*items):
    return ('<rss version="2.0"><channel><lastBuildDate>Mon, 19 Oct 2026 10:00:00 +0000</lastBuildDate>'
            + ''.join(items) + '</channel></rss>').encode()


def parse(body, source_map=None):
    payload = parse_feed(body, 'https://example.com/feed')
    mapping = source_map or {key: key for key in rss.SOURCES}
    result = rss.present(payload, {key: key for key in mapping.values()}, mapping)
    return [item for group in result['groups'] for item in group['items']], result['feed_updated_at']


def test_rss_keeps_order_identity_and_structured_heat():
    items, updated = parse(feed(
        item('b', heat='<heat_score>20.9285</heat_score><impressions>3011808</impressions><likes>0</likes><unknown>99</unknown>'),
        item('a', 'reddit', '<heat_score>13.8</heat_score><reddit_rank>3</reddit_rank>', publisher='r/programming'),
        item('b'),
    ))
    assert [i['id'] for i in items] == ['b', 'a']
    assert items[0]['heat_score'] == 20.9285
    assert items[0]['metrics'] == {'impressions': 3011808, 'likes': 0}
    assert items[1]['publisher'] == 'r/programming'
    assert items[0]['summary'] == '中文摘要'
    assert items[0]['published_at'] < updated


def test_optional_and_invalid_values_do_not_drop_valid_items():
    items, _ = parse(feed(item(guid='', pubDate='bad date', author='',
        heat='<heat_score>NaN</heat_score><likes>-1</likes><reposts>inf</reposts>')))
    assert items[0]['id'] == 'https://example.com/a'
    assert items[0]['published_at'] is None
    assert items[0]['heat_score'] is None
    assert items[0]['metrics'] == {}


def test_skips_bad_entries_and_preserves_news_after_first_thirty():
    body = feed(*[item(str(n)) for n in range(40)], item('news', 'news'),
                item('bad', link='javascript:alert(1)'), item('empty', title=''), item('unknown', 'other'))
    items, _ = parse(body)
    assert len(items) == 41
    assert items[-1]['source'] == 'news'


@pytest.mark.parametrize('body', [b'not xml', b'<rss/>', b'<!DOCTYPE rss><rss/>', b'x' * (MAX_BYTES + 1)])
def test_invalid_feed_rejected(body):
    with pytest.raises(CollectorError):
        parse(body)


def test_ithome_mapping_preserves_order_and_deduplication():
    items, _ = parse(feed(item('b', 'news', '<heat_score>11.88</heat_score>', publisher='IT之家·24h热榜'),
                         item('a', 'news'), item('b', 'news'), item('x', 'x')), {'news': 'ithome'})
    assert [i['id'] for i in items] == ['b', 'a']
    assert all(i['source'] == 'ithome' for i in items)
    assert items[0]['heat_score'] == 11.88
    assert items[0]['publisher'] == 'IT之家·24h热榜'


@pytest.fixture
def configured(tmp_path, monkeypatch):
    monkeypatch.delenv('EASEL_OVERSEAS_RSS_URL', raising=False)
    monkeypatch.delenv('EASEL_ITHOME_RSS_URL', raising=False)
    env = tmp_path / '.env'
    env.write_text('EASEL_OVERSEAS_RSS_URL=https://example.com/overseas\nEASEL_ITHOME_RSS_URL=https://example.com/ithome\n')
    service = TrendService()
    app = FastAPI()
    app.include_router(rss.create_router(env, service))
    with TestClient(app) as client:
        yield env, service, client


def expire(service):
    for entry in service._entries.values():
        entry.attempted_at = 0


def test_routes_share_upstream_cache_and_keep_feeds_independent(configured, monkeypatch):
    env, service, client = configured
    calls = []
    def collect(source, environment):
        calls.append(source.id)
        return parse_feed(feed(*[item(str(n)) for n in range(40)], item(source.id, 'news')), source.options['url'])
    monkeypatch.setattr(service_module, 'collect', collect)
    with ThreadPoolExecutor(max_workers=3) as pool:
        results = list(pool.map(lambda _: client.get('/api/overseas-trends').json(), range(3)))
    assert calls == ['overseas-rss']
    assert len(results[0]['groups'][0]['items']) == 40
    assert len(results[0]['groups'][2]['items']) == 1
    ithome = client.get('/api/ithome-trends').json()
    assert ithome['groups'][0]['items'][0]['id'] == 'ithome-rss'
    assert ithome['groups'][0]['items'][0]['source'] == 'ithome'
    environment = rss.read_settings(env)
    source = next(s for s in load_sources(env.parent, environment) if s.id == 'overseas-rss')
    assert service.get(source, environment)['ok']
    assert calls == ['overseas-rss', 'ithome-rss']  # unified API uses the very same entry
    env.write_text('EASEL_OVERSEAS_RSS_URL=https://example.com/overseas\n')
    assert not client.get('/api/ithome-trends').json()['configured']


def test_failure_cache_etag_empty_and_url_change(configured, monkeypatch):
    env, service, client = configured
    state = {'mode': 'good', 'calls': 0}
    def collect(source, environment):
        state['calls'] += 1
        if state['mode'] == 'bad':
            raise CollectorError('invalid_feed')
        if state['mode'] == '304':
            assert source.options['_etag'] == 'good'
            return {'version': 1, 'fetched_at': utc_now(), 'items': [], 'not_modified': True}
        payload = parse_feed(feed() if state['mode'] == 'empty' else feed(item()), source.options['url'])
        return {**payload, 'etag': 'good'}
    monkeypatch.setattr(service_module, 'collect', collect)
    good = client.get('/api/overseas-trends').json()
    state['mode'] = 'bad'
    expire(service)
    failed = client.get('/api/overseas-trends').json()
    assert failed['stale'] and failed['groups'] == good['groups']
    assert failed['fetched_at'] == good['fetched_at']
    client.get('/api/overseas-trends')
    assert state['calls'] == 2
    state['mode'] = '304'
    expire(service)
    fresh = client.get('/api/overseas-trends').json()
    assert not fresh['stale'] and not fresh['error'] and fresh['groups'] == good['groups']
    state['mode'] = 'empty'
    expire(service)
    assert not any(g['items'] for g in client.get('/api/overseas-trends').json()['groups'])
    state['mode'] = 'bad'
    env.write_text('EASEL_OVERSEAS_RSS_URL=https://different.example/feed\n')
    changed = client.get('/api/overseas-trends').json()
    assert not changed['stale'] and not any(g['items'] for g in changed['groups'])
    env.write_text('EASEL_OVERSEAS_RSS_URL=\n')
    removed = client.get('/api/overseas-trends').json()
    assert not removed['configured'] and not removed['error'] and removed['fetched_at'] is None


def test_presets_manage_disable_enable_and_local_override(configured):
    env, _, client = configured
    environment = rss.read_settings(env)
    assert {'overseas-rss', 'ithome-rss'} <= {s['id'] for s in management.describe(env.parent, environment)['sources']}
    management.update(env.parent, environment, {'action': 'toggle', 'id': 'overseas-rss', 'enabled': False})
    assert not client.get('/api/overseas-trends').json()['configured']
    management.update(env.parent, environment, {'action': 'toggle', 'id': 'overseas-rss', 'enabled': True})
    assert 'overseas-rss' in {s.id for s in load_sources(env.parent, environment)}
    config = env.parent / 'config/trend-sources.json'
    config.write_text(json.dumps({'version': 1, 'sources': [{'id': 'overseas-rss', 'refresh_seconds': 600}]}))
    source = next(s for s in load_sources(env.parent, environment) if s.id == 'overseas-rss')
    assert source.refresh == 600 and source.options['url'] == 'https://example.com/overseas'


def test_actual_isolated_worker_etag_roundtrip(tmp_path):
    calls = []
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args): pass
        def do_GET(self):
            etag = self.headers.get('If-None-Match')
            calls.append(etag)
            if etag == 'v1':
                self.send_response(304)
                self.end_headers()
                return
            self.send_response(200)
            self.send_header('ETag', 'v1')
            self.end_headers()
            self.wfile.write(feed(item(heat='<heat_score>20.9</heat_score><likes>0</likes>')))
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        environment = {'EASEL_OVERSEAS_RSS_URL': f'http://127.0.0.1:{server.server_port}/feed'}
        source = next(s for s in load_sources(tmp_path, environment) if s.id == 'overseas-rss')
        service = TrendService()
        good = service.get(source, environment)
        assert good['ok'], good
        assert good['items'][0]['rss']['metrics'] == {'likes': 0}
        expire(service)
        fresh = service.get(source, environment)
        assert fresh['ok'] and not fresh['error'] and fresh['items'] == good['items']
        assert calls == [None, 'v1']
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def test_metadata_cannot_smuggle_invalid_values_or_headers():
    payload = parse_feed(feed(item()), 'https://example.com/feed')
    with pytest.raises(CollectorError):
        validate_payload({**payload, 'etag': 'good\r\nAuthorization: bad'})
    payload['items'][0]['rss']['metrics']['likes'] = float('nan')
    with pytest.raises(CollectorError):
        validate_payload(payload)
