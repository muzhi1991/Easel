"""Offline regression tests for the independent RSS channel."""
from concurrent.futures import ThreadPoolExecutor
import urllib.error

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from easel import overseas_trends as rss


def item(identity='a', source='x', heat='', **fields):
    values = {'title': '测试标题', 'link': f'https://example.com/{identity}', 'guid': identity,
              'source': source, 'publisher': 'X', 'author': 'Author',
              'pubDate': 'Mon, 19 Oct 2026 09:00:00 +0000', 'description': '中文摘要', **fields}
    return '<item>' + ''.join(f'<{key}>{value}</{key}>' for key, value in values.items()) + f'<heat>{heat}</heat></item>'


def feed(*items):
    return ('<rss version="2.0"><channel><lastBuildDate>Mon, 19 Oct 2026 10:00:00 +0000</lastBuildDate>'
            + ''.join(items) + '</channel></rss>').encode()


@pytest.fixture
def service(tmp_path, monkeypatch):
    env = tmp_path / '.env'
    env.write_text('EASEL_OVERSEAS_RSS_URL=https://example.com/feed.xml\n')
    monkeypatch.delenv('EASEL_OVERSEAS_RSS_URL', raising=False)
    return rss.OverseasFeed(env)


def test_rss_keeps_order_identity_and_structured_heat():
    items, updated = rss.parse_feed(feed(
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
    items, _ = rss.parse_feed(feed(item(guid='', pubDate='bad date', author='',
        heat='<heat_score>NaN</heat_score><likes>-1</likes><reposts>inf</reposts>')))
    assert items[0]['id'] == 'https://example.com/a'
    assert items[0]['published_at'] is None
    assert items[0]['heat_score'] is None
    assert items[0]['metrics'] == {}


def test_skips_bad_entries_and_preserves_news_after_first_fifteen():
    body = feed(*[item(str(n)) for n in range(20)], item('news', 'news'),
                item('bad', link='javascript:alert(1)'), item('empty', title=''), item('unknown', 'other'))
    items, _ = rss.parse_feed(body)
    assert len(items) == 21
    assert items[-1]['source'] == 'news'


@pytest.mark.parametrize('body', [b'not xml', b'<rss/>', b'<!DOCTYPE rss><rss/>', b'x' * (rss.MAX_FEED_BYTES + 1)])
def test_invalid_feed_rejected(body):
    with pytest.raises((ValueError, rss.ET.ParseError)):
        rss.parse_feed(body)


def test_concurrent_groups_share_one_download(service, monkeypatch):
    calls = []
    def download(*args):
        calls.append(args)
        return feed(item('x'), item('r', 'reddit'), item('n', 'news')), 'etag'
    monkeypatch.setattr(service, '_download', download)
    with ThreadPoolExecutor(max_workers=3) as pool:
        results = list(pool.map(lambda _: service.get(), range(3)))
    assert len(calls) == 1
    assert [len(g['items']) for g in results[0]['groups']] == [1, 1, 1]
    assert results[0]['feed_updated_at'] is not None
    assert results[0]['fetched_at'] is not None


def test_failure_retains_previous_success_and_does_not_retry_each_request(service, monkeypatch):
    monkeypatch.setattr(service, '_download', lambda *_: (feed(item()), 'good'))
    good = service.get()
    service._checked_at = 0
    calls = []
    def fail(*_):
        calls.append(1)
        raise OSError('secret URL or upstream response')
    monkeypatch.setattr(service, '_download', fail)
    failed = service.get()
    service.get()
    assert len(calls) == 1
    assert failed['stale'] is True
    assert failed['groups'] == good['groups']
    assert failed['fetched_at'] == good['fetched_at']
    assert 'secret' not in failed['error']
    assert service._etag == 'good'


def test_bad_xml_does_not_replace_cache_or_validator(service, monkeypatch):
    monkeypatch.setattr(service, '_download', lambda *_: (feed(item()), 'good'))
    good = service.get()
    service._checked_at = 0
    monkeypatch.setattr(service, '_download', lambda *_: (b'bad xml', 'bad'))
    assert service.get()['groups'] == good['groups']
    assert service._etag == 'good'


def test_new_or_removed_url_never_shows_old_feed(service, monkeypatch):
    monkeypatch.setattr(service, '_download', lambda *_: (feed(item()), 'good'))
    service.get()
    service.env_file.write_text('EASEL_OVERSEAS_RSS_URL=https://different.example/feed.xml')
    def fail(*_):
        raise OSError()
    monkeypatch.setattr(service, '_download', fail)
    changed = service.get()
    assert not changed['stale']
    assert not any(g['items'] for g in changed['groups'])
    service.env_file.write_text('EASEL_OVERSEAS_RSS_URL=')
    removed = service.get()
    assert removed['configured'] is False
    assert removed['error'] == ''
    assert removed['fetched_at'] is None


def test_etag_and_304_refresh_keep_content(service, monkeypatch):
    with monkeypatch.context() as download_patch:
        download_patch.setattr(service, '_download', lambda *_: (feed(item()), 'validator'))
        good = service.get()
    service._checked_at = 0
    class Opener:
        def open(self, request, timeout):
            assert request.get_header('If-none-match') == 'validator'
            raise urllib.error.HTTPError(request.full_url, 304, 'Not Modified', {}, None)
    monkeypatch.setattr(rss.urllib.request, 'build_opener', lambda *_: Opener())
    fresh = service.get()
    assert fresh['error'] == '' and fresh['stale'] is False
    assert fresh['groups'] == good['groups']


def test_empty_feed_clears_old_items(service, monkeypatch):
    monkeypatch.setattr(service, '_download', lambda *_: (feed(item()), 'one'))
    service.get()
    service._checked_at = 0
    monkeypatch.setattr(service, '_download', lambda *_: (feed(), 'empty'))
    result = service.get()
    assert result['error'] == ''
    assert not any(g['items'] for g in result['groups'])


def test_route_unconfigured_is_read_only(tmp_path, monkeypatch):
    monkeypatch.delenv('EASEL_OVERSEAS_RSS_URL', raising=False)
    app = FastAPI()
    app.include_router(rss.create_router(tmp_path / '.env'))
    with TestClient(app) as client:
        response = client.get('/api/overseas-trends')
    assert response.status_code == 200
    assert response.json()['configured'] is False
    assert [g['source'] for g in response.json()['groups']] == ['x', 'reddit', 'news']
    assert not (tmp_path / '.env').exists()
