import importlib
import sys


def _reload_app(monkeypatch):
    """屏蔽 .env 加载后重新导入 app，确保读到的是代码内默认值。"""
    import dotenv
    monkeypatch.setattr(dotenv, 'load_dotenv', lambda *a, **k: None)
    if 'app' in sys.modules:
        return importlib.reload(sys.modules['app'])
    import app
    return app


def test_max_pages_default_is_5000(monkeypatch):
    monkeypatch.delenv('MAX_PAGES', raising=False)
    app = _reload_app(monkeypatch)
    assert app.MAX_PAGES == 5000


def test_max_pages_can_be_overridden_by_env(monkeypatch):
    monkeypatch.setenv('MAX_PAGES', '123')
    app = _reload_app(monkeypatch)
    assert app.MAX_PAGES == 123


def test_allow_block_root_defaults_to_false(monkeypatch):
    monkeypatch.delenv('ALLOW_BLOCK_ROOT', raising=False)
    app = _reload_app(monkeypatch)
    assert app.ALLOW_BLOCK_ROOT is False


def test_max_pages_rejects_non_numeric(monkeypatch):
    monkeypatch.setenv('MAX_PAGES', 'abc')
    try:
        _reload_app(monkeypatch)
    except ValueError:
        return
    raise AssertionError('非法配置应抛 ValueError，而不是静默回退')
