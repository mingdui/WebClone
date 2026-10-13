# WebClone 爬取范围控制 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让扒站任务的抓取范围可观测、可干预、有硬上限，同时修复「文件计数恒为 0」的协议缺陷。

**Architecture:** 分三道闸——事前 `MAX_PAGES` 硬上限兜底、事中按第一层路径段归类统计并允许用户点击停止、纵深上在「链接发现」与「队列出队」两个点同时拦截已停止的前缀。所有这一切的前置条件是先把 socket.io 通信从「纯文本 + 前端正则解析」升级为「结构化字段 + 前端直接读取」。

**Tech Stack:** Python 3.9+ / Flask / Flask-SocketIO（`async_mode='threading'`）/ BeautifulSoup4 / python-dotenv / pytest（仅开发依赖）

**设计文档:** `docs/superpowers/specs/2026-09-23-crawl-scope-control-design.md`

## Global Constraints

- **配置必须有代码内默认值**：一律写 `os.environ.get('KEY', default)`，**禁止** `os.environ['KEY']`。新克隆的仓库在缺少 `.env` 时必须能正常启动。
- **不得新增除 `python-dotenv` 与 `pytest` 之外的运行时依赖**；`pytest` 只能出现在 `requirements-dev.txt`，不得进 `requirements.txt`。
- **`.env` 值非法时启动即失败**（如 `MAX_PAGES=abc` 抛 `ValueError`），不做静默回退。
- **`grep` 验证时注意**：本项目的 `app.py` 含中文注释，所有 Python 文件保持 UTF-8。
- **Git 操作需经用户明确确认**：本计划中各任务的 commit 步骤是工程建议，执行前必须征得用户同意，不得自动提交。
- **行号仅供定位参考**：`app.py` 在各任务中会被持续修改，行号必然漂移。每个步骤都以**代码片段**作为锚点，一律按片段内容匹配定位，**不要依赖行号**。
- **测试运行器**：Windows 下统一使用 `.venv/Scripts/python.exe -m pytest`。
- **不改动** `SimpleCrawler` 之外的既有行为；本次不引入 AI/LLM 分类。

---

## File Structure

| 文件 | 职责 | 动作 |
|---|---|---|
| `app.py` | 全部后端逻辑（配置、爬虫、socketio 事件） | 修改 |
| `static/js/main.js` | 前端交互、进度渲染、路径面板 | 修改 |
| `templates/index.html` | 路径分类面板容器 | 修改 |
| `static/css/style.css` | 面板样式 | 修改 |
| `requirements.txt` | 运行时依赖（新增 python-dotenv） | 修改 |
| `requirements-dev.txt` | 开发依赖（pytest） | 新建 |
| `.env.example` | 配置模板与说明 | 新建 |
| `.gitignore` | 忽略 `.env`、`.venv/`、`server.log` 等 | 新建 |
| `tests/test_config.py` | 配置层测试 | 新建 |
| `tests/test_progress.py` | 结构化推送测试 | 新建 |
| `tests/test_prefix.py` | 路径归类测试 | 新建 |
| `tests/test_block.py` | 停止收集（双点拦截）测试 | 新建 |
| `tests/test_max_pages.py` | 硬上限测试 | 新建 |

**为什么 `app.py` 不拆分：** 设计文档未要求重构，且 `SimpleCrawler` 与 socketio handler 有共享状态（`ACTIVE_CRAWLERS`）。拆分带来的收益不足以覆盖本次改动的风险，留作后续独立重构。

---

## Task 1: 配置层与测试基础设施

**Files:**
- Create: `requirements-dev.txt`
- Create: `.env.example`
- Create: `.gitignore`
- Create: `tests/test_config.py`
- Modify: `app.py:26-58`（import 段与配置段）
- Modify: `requirements.txt`

**Interfaces:**
- Consumes: 无（首个任务）
- Produces: 模块级常量 `app.MAX_PAGES: int`、`app.ALLOW_BLOCK_ROOT: bool`、`app.PORT: int`、`app.DEBUG: bool`，供后续任务使用。

- [ ] **Step 1: 创建开发依赖文件**

`requirements-dev.txt`：
```
pytest>=8.0.0
```

- [ ] **Step 2: 安装 pytest**

Run: `.venv/Scripts/python.exe -m pip install -r requirements-dev.txt -i https://pypi.tuna.tsinghua.edu.cn/simple`
Expected: 输出 `Successfully installed ... pytest-...`

- [ ] **Step 3: 写失败测试**

`tests/test_config.py`：
```python
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
```

- [ ] **Step 4: 运行测试，确认失败**

Run: `.venv/Scripts/python.exe -m pytest tests/test_config.py -v`
Expected: 4 个测试全部 FAIL，报 `AttributeError: module 'app' has no attribute 'MAX_PAGES'`

- [ ] **Step 5: 实现配置层**

修改 `app.py`，把 `import sys` 之后到 `socketio = SocketIO(...)` 之间（当前第 26-50 行）替换为：

```python
import sys
from dotenv import load_dotenv

# 加载 .env（文件不存在时静默跳过）。缺失 python-dotenv 会在此 ImportError——
# 这是刻意的：静默降级会导致「改了 .env 却不生效」的困惑，排查成本更高。
load_dotenv()

# Windows 控制台/重定向的 stdout 默认为 GBK，当日志含 GBK 无法表示的字符（阿拉伯文、
# emoji 等）时 print 会抛 UnicodeEncodeError，异常沿调用栈冒出去会中断整个抓取任务。
# 这里将无法编码的字符降级为转义输出（如 م），保证日志不致命。
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(errors='backslashreplace')
    except (AttributeError, ValueError):
        pass

# ===== 配置（.env 可覆盖，代码内保留默认值）=====
# 注意：必须使用 os.environ.get(key, default) 形式，禁止 os.environ[key]。
# 非法值（如 MAX_PAGES=abc）会在此抛 ValueError 并阻止启动，这是预期行为。
PORT = int(os.environ.get('PORT', 8000))
DEBUG = os.environ.get('DEBUG', 'false').lower() == 'true'
SECRET_KEY = os.environ.get('SECRET_KEY') or secrets.token_hex(32)
ALLOWED_ORIGINS = os.environ.get(
    'ALLOWED_ORIGINS',
    ','.join((
        'https://wget.hackbyte.io',
        f'http://localhost:{PORT}',
        f'http://127.0.0.1:{PORT}',
    )),
).split(',')
MAX_PAGES = int(os.environ.get('MAX_PAGES', 5000))
ALLOW_BLOCK_ROOT = os.environ.get('ALLOW_BLOCK_ROOT', 'false').lower() == 'true'

app = Flask(__name__)
app.config['SECRET_KEY'] = SECRET_KEY
socketio = SocketIO(app, cors_allowed_origins=ALLOWED_ORIGINS, async_mode='threading')
```

同时删除文件末尾 `if __name__ == '__main__':` 块中重复的 `debug` 读取——该处当前为：
```python
if __name__ == '__main__':
    port = PORT
    debug = os.environ.get('DEBUG', 'false').lower() == 'true'
```
改为：
```python
if __name__ == '__main__':
    port = PORT
    debug = DEBUG
```

- [ ] **Step 6: 更新运行时依赖**

`requirements.txt` 在 `beautifulsoup4>=4.12.0` 之后插入一行：
```
python-dotenv>=1.0.0
```

- [ ] **Step 7: 创建 `.env.example`**

```ini
# 复制为 .env 后按需修改。所有项都有代码内默认值，缺失不影响启动。

# ===== 服务 =====
PORT=8000
DEBUG=false
# 留空则每次启动随机生成。多进程部署时必须显式设置，否则各进程 SECRET_KEY 不一致
SECRET_KEY=
ALLOWED_ORIGINS=https://wget.hackbyte.io,http://localhost:8000,http://127.0.0.1:8000

# ===== 爬取范围控制 =====
# 单次任务最大页面数（硬护栏）。0 = 不限制
MAX_PAGES=5000
# 是否允许停止根路径 '/'。默认禁止，防止误操作导致任务立即终止
ALLOW_BLOCK_ROOT=false
```

- [ ] **Step 8: 创建 `.gitignore`**

```
.env
.venv/
server.log
__pycache__/
*.pyc
downloads/
static/sites/
.playwright-mcp/
```

- [ ] **Step 9: 运行测试，确认通过**

Run: `.venv/Scripts/python.exe -m pytest tests/test_config.py -v`
Expected: 4 passed

- [ ] **Step 10: 启动服务做冒烟验证**

Run: `.venv/Scripts/python.exe app.py`
Expected: 打印启动横幅并监听 8000，无 `ImportError`、无 `KeyError`

- [ ] **Step 11: Commit**（需用户确认后执行）

```bash
git add requirements.txt requirements-dev.txt .env.example .gitignore tests/test_config.py app.py
git commit -m "feat: 引入 .env 配置层与测试基础设施"
```

---

## Task 2: 结构化进度推送（修复文件计数恒为 0）

**Files:**
- Modify: `app.py`（`SimpleCrawler.__init__` 与 `log` 方法）
- Modify: `static/js/main.js:33-66`
- Create: `tests/test_progress.py`

**Interfaces:**
- Consumes: Task 1 的模块常量
- Produces:
  - `SimpleCrawler.emit_progress(msg: str) -> None` —— 推送 `{progress, files, pages, stats, blocked}`
  - `SimpleCrawler.log(msg: str) -> None` —— 保持原签名，内部改为调用 `emit_progress` 再 `print`
  - 实例属性 `self.path_stats: dict[str, int]`、`self.blocked_prefixes: set[str]`（本任务仅初始化为空，Task 3/4 填充逻辑）

- [ ] **Step 1: 写失败测试**

`tests/test_progress.py`：
```python
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
```

- [ ] **Step 2: 运行测试，确认失败**

Run: `.venv/Scripts/python.exe -m pytest tests/test_progress.py -v`
Expected: FAIL —— `AttributeError: 'SimpleCrawler' object has no attribute 'path_stats'`

- [ ] **Step 3: 实现结构化推送**

修改 `app.py` 的 `SimpleCrawler.__init__`，在 `self.total_size = 0` 之后追加：

```python
        self.total_size = 0
        self.path_stats = defaultdict(int)   # 路径前缀 -> 已抓页面数
        self.blocked_prefixes = set()        # 用户点击「停止收集」的前缀
```

把 `log` 方法（当前 `app.py:205-208`）替换为：

```python
    def emit_progress(self, msg):
        """推送进度：文本 + 结构化统计。前端直接读字段，不再解析文本。"""
        with self.lock:
            stats = dict(self.path_stats)
            blocked = list(self.blocked_prefixes)
        self.sio.emit(self.token, {
            'progress': msg,
            'files': self.file_count,
            'pages': len(self.visited_pages),
            'stats': stats,
            'blocked': blocked,
        })

    def log(self, msg):
        """发送日志到前端并打印"""
        self.emit_progress(msg)
        print(msg, flush=True)
```

**注意**：`log()` 不得在持有 `self.lock` 的代码块内被调用，否则 `emit_progress` 会因 `Lock` 不可重入而死锁。

- [ ] **Step 4: 运行测试，确认通过**

Run: `.venv/Scripts/python.exe -m pytest tests/test_progress.py -v`
Expected: 2 passed

- [ ] **Step 5: 改造前端为直接读取字段**

修改 `static/js/main.js`，删除第 50-59 行基于文本的正则解析（`numberOfPages++` 与 `numberOfFiles += ...` 两段），替换 `socket.on(myToken, ...)` 的 `else` 分支为：

```javascript
        } else {
            progressArea.style.display = 'block';
            logConsole.style.display = 'block';
            statsGrid.style.display = 'flex';

            // 直接读服务端结构化字段，服务端是统计数字的唯一真相来源
            if (typeof event.files === 'number') nFilesSpan.textContent = event.files;
            if (typeof event.pages === 'number') nPagesSpan.textContent = event.pages;

            var type = '';
            if (event.progress.indexOf('完成') !== -1) type = 'success';
            else if (event.progress.indexOf('[页面]') !== -1) type = 'info';
            addLog(event.progress, type);
        }
```

同时把第 79-83 行 `downloadBtn` 点击处理中的计数重置改为：

```javascript
        numberOfFiles = 0;
        numberOfPages = 0;
        logLines = [];
        nFilesSpan.textContent = '0';
        nPagesSpan.textContent = '0';
```

（保留 `numberOfFiles` / `numberOfPages` 变量声明以兼容后续 Task 6 的面板逻辑，但不再由前端自增。）

- [ ] **Step 6: 端到端验证文件计数**

启动服务后对任意站点发起一次抓取，确认界面「文件」数字随资源下载增长而**不再恒为 0**。

Run: `.venv/Scripts/python.exe app.py`（后台）
手动验证：浏览器打开 `http://localhost:8000`，输入 `https://www.deep-drama.com/`，观察文件计数增长。
Expected: 文件数 > 0 且随抓取增长

- [ ] **Step 7: Commit**（需用户确认后执行）

```bash
git add app.py static/js/main.js tests/test_progress.py
git commit -m "fix: 进度推送改为结构化字段，修复文件计数恒为 0"
```

---

## Task 3: 路径归类统计

**Files:**
- Modify: `app.py`（新增 `prefix_of`，`crawl_page` 增加计数）
- Create: `tests/test_prefix.py`

**Interfaces:**
- Consumes: Task 2 的 `self.path_stats`
- Produces: `SimpleCrawler.prefix_of(url: str) -> str`（staticmethod），返回第一层路径段或 `'/'`

- [ ] **Step 1: 写失败测试**

`tests/test_prefix.py`：
```python
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
```

- [ ] **Step 2: 运行测试，确认失败**

Run: `.venv/Scripts/python.exe -m pytest tests/test_prefix.py -v`
Expected: FAIL —— `AttributeError: type object 'SimpleCrawler' has no attribute 'prefix_of'`

- [ ] **Step 3: 实现 prefix_of 并接入计数**

在 `app.py` 的 `SimpleCrawler` 类中，紧邻 `url_to_path` 之前插入：

```python
    @staticmethod
    def prefix_of(url):
        """取第一层路径段作为归类键：/2026/07/xxx.html -> '2026'"""
        seg = urlparse(url).path.strip('/').split('/')[0]
        return seg or '/'
```

修改 `crawl_page` 开头（当前 `app.py:502-506`）：

```python
    def crawl_page(self, page_url):
        """爬取单个页面"""
        if page_url in self.visited_pages:
            return

        self.visited_pages.add(page_url)
        with self.lock:
            self.path_stats[self.prefix_of(page_url)] += 1
        self.log(f"[页面] {page_url}")
```

- [ ] **Step 4: 运行测试，确认通过**

Run: `.venv/Scripts/python.exe -m pytest tests/test_prefix.py -v`
Expected: 6 passed

- [ ] **Step 5: 补充统计字段的集成断言**

在 `tests/test_progress.py` 末尾追加：

```python
def test_stats_reflect_visited_pages():
    c, sio = _make_crawler()
    c.path_stats['2026'] = 3
    c.log('x')
    _, payload = sio.payloads[-1]
    assert payload['stats'] == {'2026': 3}
```

Run: `.venv/Scripts/python.exe -m pytest tests/test_progress.py -v`
Expected: 3 passed

- [ ] **Step 6: Commit**（需用户确认后执行）

```bash
git add app.py tests/test_prefix.py tests/test_progress.py
git commit -m "feat: 按第一层路径段统计已抓页面数"
```

---

## Task 4: 停止收集（双点拦截 + 控制通道）

**Files:**
- Modify: `app.py`（`is_blocked`、`extract_links`、`crawl`、`ACTIVE_CRAWLERS`、两个 socketio handler）
- Create: `tests/test_block.py`

**Interfaces:**
- Consumes: Task 3 的 `prefix_of`、Task 2 的 `self.blocked_prefixes` 与 `emit_progress`
- Produces:
  - `SimpleCrawler.is_blocked(url: str) -> bool`
  - 模块级 `app.ACTIVE_CRAWLERS: dict[str, SimpleCrawler]`
  - socketio 事件 `block_prefix` / `unblock_prefix`，载荷 `{token: str, prefix: str}`

- [ ] **Step 1: 写失败测试**

`tests/test_block.py`：
```python
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
```

- [ ] **Step 2: 运行测试，确认失败**

Run: `.venv/Scripts/python.exe -m pytest tests/test_block.py -v`
Expected: FAIL —— `AttributeError: 'SimpleCrawler' object has no attribute 'is_blocked'`

- [ ] **Step 3: 实现 is_blocked 与拦截点 1**

在 `SimpleCrawler` 中、`prefix_of` 之后插入：

```python
    def is_blocked(self, url):
        """该 URL 所属的路径分类是否已被用户停止"""
        with self.lock:
            return self.prefix_of(url) in self.blocked_prefixes
```

修改 `extract_links` 的过滤条件（当前 `app.py:443`）：

```python
            if url and self.is_same_domain(url) and not self.is_blocked(url):
                if url not in self.visited_pages and url not in self.pending_pages:
                    links.append(url)
```

- [ ] **Step 4: 实现拦截点 2（队列出队）**

修改 `crawl` 的主循环（当前 `app.py:564-567`），并在方法开头注册实例：

```python
        start_time = time.time()

        # 注册到全局表，供 socketio handler 定位
        ACTIVE_CRAWLERS[self.token] = self
        try:
            # 添加起始URL
            self.pending_pages.append(self.start_url)

            # 循环处理所有页面
            while self.pending_pages:
                page_url = self.pending_pages.pop(0)
                if self.is_blocked(page_url):
                    continue          # 用户点击停止时已在队列中的 URL
                if page_url not in self.visited_pages:
                    self.crawl_page(page_url)
        finally:
            ACTIVE_CRAWLERS.pop(self.token, None)
```

- [ ] **Step 5: 实现控制通道**

在 `app.py` 模块级（`socketio` 定义之后、`SimpleCrawler` 类之前）加入：

```python
# 正在运行的抓取任务：token -> SimpleCrawler，供 socketio 控制事件定位
ACTIVE_CRAWLERS = {}
```

在 `app.py` 文件末尾（`if __name__ == '__main__':` 之前）加入：

```python
@socketio.on('block_prefix')
def handle_block_prefix(data):
    """用户点击「停止收集」：把前缀加入对应任务的封禁集合"""
    token = (data or {}).get('token')
    prefix = (data or {}).get('prefix')
    crawler = ACTIVE_CRAWLERS.get(token)
    if crawler is None:
        socketio.emit(token, {'progress': '错误：任务已结束'})
        return
    if prefix == '/' and not ALLOW_BLOCK_ROOT:
        socketio.emit(token, {'progress': '错误：不允许停止根路径'})
        return
    with crawler.lock:
        crawler.blocked_prefixes.add(prefix)
    crawler.log(f"[停止] 不再收集 /{prefix} 下的页面")


@socketio.on('unblock_prefix')
def handle_unblock_prefix(data):
    """用户点击「恢复」：把前缀移出封禁集合"""
    token = (data or {}).get('token')
    prefix = (data or {}).get('prefix')
    crawler = ACTIVE_CRAWLERS.get(token)
    if crawler is None:
        socketio.emit(token, {'progress': '错误：任务已结束'})
        return
    with crawler.lock:
        crawler.blocked_prefixes.discard(prefix)
    crawler.log(f"[恢复] 继续收集 /{prefix} 下的页面")
```

- [ ] **Step 6: 运行测试，确认通过**

Run: `.venv/Scripts/python.exe -m pytest tests/test_block.py -v`
Expected: 4 passed

- [ ] **Step 7: 全量测试回归**

Run: `.venv/Scripts/python.exe -m pytest tests/ -v`
Expected: 全部通过

- [ ] **Step 8: Commit**（需用户确认后执行）

```bash
git add app.py tests/test_block.py
git commit -m "feat: 按路径分类停止收集，双点拦截"
```

---

## Task 5: 硬护栏 MAX_PAGES

**Files:**
- Modify: `app.py`（`crawl` 主循环）
- Create: `tests/test_max_pages.py`

**Interfaces:**
- Consumes: Task 1 的 `app.MAX_PAGES`、Task 4 的 `crawl` 主循环结构
- Produces: 无新接口，仅行为约束

- [ ] **Step 1: 写失败测试**

`tests/test_max_pages.py`：
```python
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
```

- [ ] **Step 2: 运行测试，确认失败**

Run: `.venv/Scripts/python.exe -m pytest tests/test_max_pages.py -v`
Expected: FAIL —— 断言 `len(crawled) == 3` 失败（实际会抓 10 个）

- [ ] **Step 3: 实现上限判断**

修改 `crawl` 主循环，在出队前加入上限检查：

```python
            while self.pending_pages:
                if MAX_PAGES and len(self.visited_pages) >= MAX_PAGES:
                    self.log(f"[上限] 已达最大页面数 {MAX_PAGES}，停止抓取")
                    break
                page_url = self.pending_pages.pop(0)
                if self.is_blocked(page_url):
                    continue
                if page_url not in self.visited_pages:
                    self.crawl_page(page_url)
```

**注意**：`MAX_PAGES` 在循环内通过模块全局名读取（而非捕获到局部变量），这样 `monkeypatch.setattr(app, 'MAX_PAGES', 3)` 才能生效。

- [ ] **Step 4: 运行测试，确认通过**

Run: `.venv/Scripts/python.exe -m pytest tests/test_max_pages.py -v`
Expected: 1 passed

- [ ] **Step 5: 全量回归**

Run: `.venv/Scripts/python.exe -m pytest tests/ -v`
Expected: 全部通过

- [ ] **Step 6: Commit**（需用户确认后执行）

```bash
git add app.py tests/test_max_pages.py
git commit -m "feat: 增加 MAX_PAGES 硬上限兜底"
```

---

## Task 6: 前端路径分类面板

**Files:**
- Modify: `templates/index.html`（面板容器）
- Modify: `static/css/style.css`（面板样式）
- Modify: `static/js/main.js`（渲染 + 事件 + 节流）

**Interfaces:**
- Consumes: Task 2 推送的 `event.stats` / `event.blocked`，Task 4 的 `block_prefix` / `unblock_prefix` 事件
- Produces: 无（终端用户界面）

- [ ] **Step 1: 添加面板容器**

在 `templates/index.html` 中、统计网格 `statsGrid` 之后插入：

```html
            <div id="statsPanel" class="stats-panel" style="display:none;">
                <div class="stats-panel-title">路径分类</div>
                <div id="statsList" class="stats-list"></div>
            </div>
```

- [ ] **Step 2: 添加样式**

在 `static/css/style.css` 末尾追加（复用已有 CSS 变量）：

```css
.stats-panel {
    margin-top: 16px;
    border: 1px solid rgba(255, 255, 255, .12);
    border-radius: 8px;
    padding: 12px;
}
.stats-panel-title {
    font-size: 13px;
    opacity: .7;
    margin-bottom: 8px;
}
.stats-row {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 6px 0;
    border-bottom: 1px solid rgba(255, 255, 255, .06);
    font-size: 13px;
}
.stats-row:last-child { border-bottom: none; }
.stats-row.blocked { opacity: .45; }
.stats-prefix { font-family: monospace; }
.stats-count { margin-left: 8px; opacity: .6; }
.stats-btn {
    cursor: pointer;
    border: 1px solid rgba(255, 255, 255, .2);
    border-radius: 4px;
    background: transparent;
    color: inherit;
    font-size: 12px;
    padding: 2px 8px;
}
```

- [ ] **Step 3: 实现渲染与事件**

在 `static/js/main.js` 中，`socket.on(myToken, ...)` 回调内、`addLog(event.progress, type);` 之前插入：

```javascript
            if (event.stats) renderStats(event.stats, event.blocked || []);
```

并在 `generateToken` 函数之前插入渲染逻辑：

```javascript
    var statsPanel = document.getElementById('statsPanel');
    var statsList = document.getElementById('statsList');
    var lastStatsRender = 0;

    function renderStats(stats, blocked) {
        // 约 300ms 节流：抓取时进度消息高频到达，避免每页都重排 DOM
        var now = Date.now();
        if (now - lastStatsRender < 300) return;
        lastStatsRender = now;

        statsPanel.style.display = 'block';
        var entries = Object.keys(stats).map(function (k) {
            return { prefix: k, count: stats[k] };
        }).sort(function (a, b) { return b.count - a.count; });

        statsList.innerHTML = '';
        entries.forEach(function (e) {
            var isBlocked = blocked.indexOf(e.prefix) !== -1;
            var isRoot = e.prefix === '/';

            var row = document.createElement('div');
            row.className = 'stats-row' + (isBlocked ? ' blocked' : '');

            var label = document.createElement('span');
            label.innerHTML = '<span class="stats-prefix">/' +
                e.prefix.replace('/', '') + '</span>' +
                '<span class="stats-count">' + e.count + ' 页</span>';

            var btn = document.createElement('button');
            btn.className = 'stats-btn';
            if (isRoot) {
                btn.disabled = true;
                btn.textContent = '不可停止';
            } else if (isBlocked) {
                btn.textContent = '恢复';
                btn.addEventListener('click', function () {
                    socket.emit('unblock_prefix', { token: myToken, prefix: e.prefix });
                });
            } else {
                btn.textContent = '停止收集';
                btn.addEventListener('click', function () {
                    socket.emit('block_prefix', { token: myToken, prefix: e.prefix });
                });
            }

            row.appendChild(label);
            row.appendChild(btn);
            statsList.appendChild(row);
        });
    }
```

并在 `downloadBtn` 点击处理中，重置状态时追加一行隐藏面板：

```javascript
        statsPanel.style.display = 'none';
        statsList.innerHTML = '';
```

- [ ] **Step 4: 手工端到端验证**

Run: `.venv/Scripts/python.exe app.py`（后台），浏览器打开 `http://localhost:8000`

逐项确认：
1. 输入 `https://www.deep-drama.com/` 点「开始下载」→ 面板出现，`/2026` 计数增长
2. 点击 `/2026` 行的「停止收集」→ 该行置灰显示「恢复」，计数停止增长
3. 其他前缀（`/p`、`/search`）继续正常增长
4. 点击「恢复」→ 该行恢复为「停止收集」并重新增长
5. 总页面数不超过 `MAX_PAGES`

Expected: 5 项全部符合

- [ ] **Step 5: 更新 README 配置说明**

在 `README.md` 的「配置说明 → 环境变量」表格中追加三行：

```markdown
| `MAX_PAGES` | `5000` | 单次任务最大页面数，`0` 表示不限制 |
| `ALLOW_BLOCK_ROOT` | `false` | 是否允许停止根路径 `/` |
| `ALLOWED_ORIGINS` | 含本机地址 | Socket.IO 允许的来源，逗号分隔 |
```

并补一节说明 `.env`：

```markdown
### 使用 .env 覆盖配置

复制 `.env.example` 为 `.env` 后按需修改。所有配置项在代码内都有默认值，
缺少 `.env` 不影响启动。
```

- [ ] **Step 6: Commit**（需用户确认后执行）

```bash
git add templates/index.html static/css/style.css static/js/main.js README.md
git commit -m "feat: 路径分类面板，支持停止/恢复收集"
```

---

## 手工验收清单（全部任务完成后）

- [ ] `.venv/Scripts/python.exe -m pytest tests/ -v` 全绿
- [ ] 删除本地 `.env` 后服务仍能启动（验证默认值兜底）
- [ ] `MAX_PAGES=abc` 时服务启动即报 `ValueError`（验证不静默回退）
- [ ] 对 `https://www.deep-drama.com/` 抓取，观察：
  - 文件计数 > 0（Task 2 修复）
  - 路径面板正常增长（Task 3、6）
  - 点击停止后该类不再增长，其他类不受影响（Task 4）
  - 总页面数被 `MAX_PAGES` 截断（Task 5）
