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
    sio = _FakeSio()
    c = app.SimpleCrawler('https://example.com/', '/tmp/x', 'tok', sio)
    return c, sio


def test_emit_progress_carries_structured_fields():
    c, sio = _make_crawler()
    c.file_count = 7
    c.visited_pages = {'a', 'b', 'c'}
    c.log('hello')

    token, payload = sio.payloads[-1]
    assert token == 'tok'
    assert payload['progress'] == 'hello'
    assert payload['files'] == 7          # 关键：不再依赖前端从文本里猜
    assert payload['pages'] == 3
    assert payload['stats'] == {}
    assert payload['blocked'] == []


def test_progress_fields_present_on_every_message():
    c, sio = _make_crawler()
    c.log('one')
    c.log('two')
    for _, payload in sio.payloads:
        assert set(payload) >= {'progress', 'files', 'pages', 'stats', 'blocked'}


def test_stats_reflect_visited_pages():
    c, sio = _make_crawler()
    c.path_stats['2026'] = 3
    c.log('x')
    _, payload = sio.payloads[-1]
    assert payload['stats'] == {'2026': 3}
