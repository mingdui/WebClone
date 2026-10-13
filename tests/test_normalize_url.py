"""URL 规范化测试

核心：同一页面在 HTML 里可能以多种写法出现，规范化后必须收敛成同一个字符串，
否则 visited_pages 去重失效，同一页会被反复抓取。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import app


def _crawler():
    # normalize_url 只用 self.scheme，不需要真的 socketio 实例
    return app.SimpleCrawler('https://example.com/', '/tmp/x', 'tok', None)


BASE = 'https://www.deep-drama.com/'


def test_raw_arabic_and_percent_encoded_are_the_same():
    """原始字符与百分号编码指向同一页面，必须归一为同一字符串。"""
    c = _crawler()
    raw = c.normalize_url('/search/label/مسلسل', BASE)
    encoded = c.normalize_url('/search/label/%D9%85%D8%B3%D9%84%D8%B3%D9%84', BASE)
    assert raw == encoded, f'未归一：\n  {raw}\n  {encoded}'


def test_space_is_percent_encoded():
    """空格是非法 URL 字符，必须编码为 %20。"""
    c = _crawler()
    got = c.normalize_url('/search/label/مسلسل مدبلج', BASE)
    assert ' ' not in got
    assert '%20' in got


def test_hostname_case_is_normalized():
    c = _crawler()
    a = c.normalize_url('https://WWW.Example.COM/Path', BASE)
    b = c.normalize_url('https://www.example.com/Path', BASE)
    assert a == b
    # 路径大小写敏感，不应被改动
    assert '/Path' in a


def test_fragment_is_stripped():
    c = _crawler()
    got = c.normalize_url('/page?a=1#section', BASE)
    assert '#' not in got
    assert got.endswith('?a=1')


def test_plain_ascii_url_unchanged():
    """普通 ASCII URL 不应被改动 —— 确保归一化没有副作用。"""
    c = _crawler()
    got = c.normalize_url('/css/main.css', BASE)
    assert got == 'https://www.deep-drama.com/css/main.css'


def test_protocol_relative_url():
    c = _crawler()
    got = c.normalize_url('//cdn.example.com/a.js', BASE)
    assert got == 'https://cdn.example.com/a.js'


def test_non_http_schemes_rejected():
    c = _crawler()
    assert c.normalize_url('mailto:a@b.com', BASE) is None
    assert c.normalize_url('javascript:void(0)', BASE) is None
    assert c.normalize_url('data:image/png;base64,AAA', BASE) is None
    assert c.normalize_url('#anchor', BASE) is None
    assert c.normalize_url('', BASE) is None


def test_query_string_is_preserved():
    """查询串不能被规范化吃掉。"""
    c = _crawler()
    got = c.normalize_url('/search?updated-max=2026-09-22T10:34:00-07:00&max-results=7', BASE)
    assert 'updated-max=2026-09-22T10:34:00-07:00' in got
    assert 'max-results=7' in got


def test_normalization_is_idempotent():
    """规范化两次必须等于规范化一次，否则去重在第二轮仍会失效。"""
    c = _crawler()
    once = c.normalize_url('/search/label/مسلسل مدبلج', BASE)
    twice = c.normalize_url(once, BASE)
    assert once == twice, f'非幂等：\n  {once}\n  {twice}'
