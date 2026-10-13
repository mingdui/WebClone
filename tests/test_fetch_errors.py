"""fetch() 的失败诊断测试

核心：请求失败必须记录**具体原因**（原先裸 except 吞掉一切，使用者
只能看到「资源没下下来」却不知为何）。silent=True 的资源失败改为计数，
由 crawl() 结束时汇总。
"""
import os
import sys
from unittest.mock import patch
from urllib.error import HTTPError, URLError

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import app


class _FakeSio:
    def __init__(self):
        self.msgs = []

    def emit(self, token, payload):
        self.msgs.append(payload)


class _Opener:
    """替身 opener：open() 按传入行为抛异常或返回响应。"""

    def __init__(self, behavior):
        self._behavior = behavior

    def open(self, req, timeout=None):
        return self._behavior(req, timeout)


class _FakeResp:
    def __init__(self, body=b'ok', ctype='text/plain'):
        self._body = body
        self.headers = {'Content-Type': ctype}

    def read(self):
        return self._body

    def close(self):
        pass


def _crawler():
    sio = _FakeSio()
    c = app.SimpleCrawler('https://example.com/', '/tmp/x', 'tok', sio)
    return c, sio


def _fetch_with(crawler, behavior, url='https://example.com/a.js', **kw):
    with patch.object(app, 'build_opener', lambda *h: _Opener(behavior)):
        return crawler.fetch(url, **kw)


def test_http_403_records_reason_and_does_not_retry():
    c, sio = _crawler()
    calls = []

    def behavior(req, timeout):
        calls.append(1)
        raise HTTPError(req.full_url, 403, 'Forbidden', {}, None)

    content, _ = _fetch_with(c, behavior)

    assert content is None
    assert c.fetch_errors['HTTP 403'] == 1
    assert len(calls) == 1, '4xx 是明确拒绝，不该重试'


def test_http_500_retries_then_records():
    c, sio = _crawler()
    calls = []

    def behavior(req, timeout):
        calls.append(1)
        raise HTTPError(req.full_url, 500, 'Server Error', {}, None)

    _fetch_with(c, behavior)

    assert c.fetch_errors['HTTP 500'] == 1
    assert len(calls) == 2, '5xx 可能是暂时性的，应重试'


def test_url_error_records_reason():
    c, sio = _crawler()

    def behavior(req, timeout):
        raise URLError('Name or service not known')

    _fetch_with(c, behavior)

    assert any('连接失败' in k for k in c.fetch_errors), c.fetch_errors


def test_timeout_records_reason():
    c, sio = _crawler()

    def behavior(req, timeout):
        raise TimeoutError('timed out')

    _fetch_with(c, behavior)

    assert any('TimeoutError' in k for k in c.fetch_errors), c.fetch_errors


def test_success_returns_content_and_no_error():
    c, sio = _crawler()
    content, ctype = _fetch_with(c, lambda req, timeout: _FakeResp(b'hello', 'image/png'))

    assert content == b'hello'
    assert ctype == 'image/png'
    assert not c.fetch_errors


def test_silent_does_not_log_but_still_counts():
    """资源下载走 silent —— 不逐条刷屏，但必须计入汇总。"""
    c, sio = _crawler()

    def behavior(req, timeout):
        raise HTTPError(req.full_url, 403, 'Forbidden', {}, None)

    _fetch_with(c, behavior, silent=True)

    assert c.fetch_errors['HTTP 403'] == 1
    logged = [m.get('progress', '') for m in sio.msgs]
    assert not any('失败' in m for m in logged), 'silent 时不应逐条打日志'


def test_non_silent_logs_the_reason():
    """页面抓取走非 silent —— 失败必须可见。"""
    c, sio = _crawler()

    def behavior(req, timeout):
        raise HTTPError(req.full_url, 403, 'Forbidden', {}, None)

    _fetch_with(c, behavior, silent=False)

    logged = [m.get('progress', '') for m in sio.msgs]
    assert any('失败' in m and 'HTTP 403' in m for m in logged), logged


def test_crawl_summarizes_fetch_errors_at_the_end(monkeypatch):
    """资源失败不逐条刷屏，但任务结束必须给出汇总 —— 这是本次修复的核心。"""
    c, sio = _crawler()
    c.fetch_errors['HTTP 403'] = 32
    c.fetch_errors['连接失败(TimeoutError())'] = 15
    monkeypatch.setattr(c, 'crawl_page', lambda url: None)   # 不真发请求

    c.crawl()

    logged = [m.get('progress', '') for m in sio.msgs]
    summary = [m for m in logged if '请求失败' in m]
    assert summary, f'未输出失败汇总：{logged}'
    line = summary[0]
    assert '47' in line, line
    assert 'HTTP 403 × 32' in line, line
