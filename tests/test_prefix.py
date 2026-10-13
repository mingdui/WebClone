import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import app


def test_prefix_of_nested_path():
    assert app.SimpleCrawler.prefix_of(
        'https://www.deep-drama.com/2026/07/blog-post_1628.html') == '2026'


def test_prefix_of_single_segment():
    assert app.SimpleCrawler.prefix_of('https://x.com/p/about.html') == 'p'


def test_prefix_of_root_url():
    assert app.SimpleCrawler.prefix_of('https://x.com/') == '/'


def test_prefix_of_no_path():
    assert app.SimpleCrawler.prefix_of('https://x.com') == '/'


def test_prefix_of_trailing_slash():
    assert app.SimpleCrawler.prefix_of('https://x.com/search/') == 'search'


def test_prefix_of_query_is_ignored():
    assert app.SimpleCrawler.prefix_of('https://x.com/search?q=a/b') == 'search'
