import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import app


class _FakeSio:
    def __init__(self):
        self.payloads = []

    def emit(self, token, payload):
        self.payloads.append((token, payload))


def _make_crawler():
    return app.SimpleCrawler('https://x.com/', '/tmp/x', 'tok', _FakeSio())


def test_is_blocked_false_by_default():
    c = _make_crawler()
    assert c.is_blocked('https://x.com/2026/07/a.html') is False


def test_is_blocked_true_after_adding_prefix():
    c = _make_crawler()
    c.blocked_prefixes.add('2026')
    assert c.is_blocked('https://x.com/2026/07/a.html') is True
    assert c.is_blocked('https://x.com/p/about.html') is False


def test_root_prefix_never_matches_other_paths():
    c = _make_crawler()
    c.blocked_prefixes.add('/')
    assert c.is_blocked('https://x.com/2026/a.html') is False
    assert c.is_blocked('https://x.com/') is True


def test_extract_links_skips_blocked_prefix():
    from bs4 import BeautifulSoup
    c = _make_crawler()
    c.blocked_prefixes.add('2026')
    html = '<a href="/2026/07/a.html">a</a><a href="/p/about.html">b</a>'
    soup = BeautifulSoup(html, 'html.parser')
    links = c.extract_links(soup, 'https://x.com/')
    assert 'https://x.com/p/about.html' in links
    assert not any('/2026/' in l for l in links)


def test_dequeue_skips_blocked_prefix(monkeypatch):
    """拦截点 2：已在队列中的被封禁 URL 在出队时被跳过，不会被 crawl_page 处理。"""
    c = _make_crawler()
    c.pending_pages = ['https://x.com/2026/a.html', 'https://x.com/p/b.html']
    c.blocked_prefixes.add('2026')

    crawled = []
    monkeypatch.setattr(c, 'crawl_page', lambda url: crawled.append(url))

    c.crawl()

    assert 'https://x.com/2026/a.html' not in crawled
    assert 'https://x.com/p/b.html' in crawled


def test_handle_block_prefix_unknown_token_emits_error(monkeypatch):
    """未知 token：handler 不应抛异常，且要推送「任务已结束」错误。"""
    sio = _FakeSio()
    monkeypatch.setattr(app, 'socketio', sio)

    app.handle_block_prefix({'token': 'no-such-token', 'prefix': '2026'})

    assert len(sio.payloads) == 1
    token, payload = sio.payloads[0]
    assert token == 'no-such-token'
    assert payload.get('progress') == '错误：任务已结束'


def test_handle_block_prefix_root_disallowed(monkeypatch):
    """根路径守卫：ALLOW_BLOCK_ROOT 为假时，'/' 不入封禁集合，并推送错误。"""
    monkeypatch.setattr(app, 'ALLOW_BLOCK_ROOT', False)
    sio = _FakeSio()
    monkeypatch.setattr(app, 'socketio', sio)

    c = _make_crawler()
    monkeypatch.setitem(app.ACTIVE_CRAWLERS, 'tok-root', c)

    app.handle_block_prefix({'token': 'tok-root', 'prefix': '/'})

    assert '/' not in c.blocked_prefixes
    assert any('不允许停止根路径' in p.get('progress', '') for _, p in sio.payloads)


def test_handle_unblock_prefix_removes_prefix(monkeypatch):
    """恢复：已封禁的前缀被移出 blocked_prefixes。"""
    monkeypatch.setattr(app, 'socketio', _FakeSio())

    c = _make_crawler()
    c.blocked_prefixes.add('2026')
    monkeypatch.setitem(app.ACTIVE_CRAWLERS, 'tok-unblock', c)

    app.handle_unblock_prefix({'token': 'tok-unblock', 'prefix': '2026'})

    assert '2026' not in c.blocked_prefixes
