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


def test_loop_stops_at_max_pages(monkeypatch):
    c = _make_crawler()
    crawled = []

    def fake_crawl_page(url):
        c.visited_pages.add(url)
        crawled.append(url)

    monkeypatch.setattr(c, 'crawl_page', fake_crawl_page)
    monkeypatch.setattr(app, 'MAX_PAGES', 3)

    c.pending_pages.extend([f'https://x.com/p/{i}' for i in range(10)])
    c.crawl()

    assert len(crawled) == 3
    assert any('已达最大页面数' in p['progress']
               for _, p in c.sio.payloads)
