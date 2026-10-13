# WebClone 爬取范围控制 — 设计文档

- 日期：2026-09-23
- 状态：待实现
- 相关文件：`app.py`、`static/js/main.js`、`templates/index.html`、`requirements.txt`、`.env.example`

---

## 1. 背景

一次真实使用中，对 `https://www.deep-drama.com/` 发起抓取，**运行 3 小时仍未结束，累计访问 6623 个页面**，且页面数持续增长。用户目标是「下载网站源码」，实际却陷入 SEO 文章页之间的无限内链。

同时观察到另一个独立缺陷：**界面始终显示 0 文件**。

### 1.1 问题一：页面数量没有任何上限

`app.py` 的爬取主循环：

```python
while self.pending_pages:          # 只要队列非空就继续
    page_url = self.pending_pages.pop(0)
    if page_url not in self.visited_pages:
        self.crawl_page(page_url)
```

`extract_links()` 的过滤条件只有「同域 + 未访问过」：

```python
if url and self.is_same_domain(url):
    if url not in self.visited_pages and url not in self.pending_pages:
        links.append(url)
```

项目现有的限制：

| 维度 | 限制 | 状态 |
|---|---|---|
| 单文件大小 | `MAX_FILE_SIZE = 50MB` | 有 |
| 总下载大小 | `MAX_TOTAL_SIZE = 200MB` | 有 |
| 并发线程数 | `max_workers=30` | 有 |
| **页面数量** | — | **无** |

对「每篇文章互相链接」的 SEO 站，队列永远非空，无限爬取是必然结果。

### 1.2 问题二：文件计数恒为 0

前端从**自然语言日志里正则抠数字**（`static/js/main.js:55-59`）：

```javascript
if (event.progress.indexOf('资源下载完成') !== -1) {
    var match = event.progress.match(/(\d+)/);
    if (match) numberOfFiles += parseInt(match[1]) || 0;
```

而服务端发出的这条消息**不含数字**（`app.py:534`）：

```python
self.log(f"  资源下载完成")
```

`match(/(\d+)/)` 返回 `null`，因此 `numberOfFiles` 永不增加。

页面数显示正常，是因为前端不依赖解析，而是数 `[页面]` 日志的行数（`numberOfPages++`）。

### 1.3 共同根因

两个问题的症结是同一个：**socket.io 只推送纯文本，前端靠正则解析文本**。这既导致协议脆弱（文本一改前端就静默失效），也无法承载方案所需的路径统计这类结构化数据。

因此第一步必须是**通信协议结构化**，它同时修复问题二并支撑本设计。

---

## 2. 目标与非目标

### 目标

1. 抓取过程**可观测**：实时展示每个路径分类下已抓取的页面数。
2. 抓取过程**可干预**：用户可对某个路径分类点击「停止收集」，立即止损。
3. 抓取**不会失控**：即使无人值守，也有硬上限兜底。
4. 修复文件计数恒为 0。

### 非目标（本次不做）

- **AI / LLM 自动识别 SEO 页面**：问题本质是缺少控制流上限，而非识别能力不足；且会引入外部 API 依赖、成本与误判风险。留作后续可选增强。
- 路径深度限制（`MAX_PAGE_DEPTH`）：`MAX_PAGES` 已能兜底，无实际需求场景前不增加配置项。
- 自动删除已抓取页面：经确认采用「保留已抓、只止血」策略。
- 抓取结果的事后筛选/导出过滤。

---

## 3. 设计

### 3.1 三道闸

```
第 1 道（事前）：MAX_PAGES 硬上限           — 无人值守也能兜底
第 2 道（事中）：路径统计 + 点击停止        — 用户的核心需求
第 3 道（纵深）：停止后同时拦截「链接发现」与「队列出队」两个点
                                            — 防止已入队 URL 漏网
```

### 3.2 配置层

新增 `python-dotenv` 依赖，配置集中到 `.env`。

**启动时加载**（`app.py` 顶部，须在所有配置读取之前）：

```python
from dotenv import load_dotenv
load_dotenv()   # 文件不存在时静默跳过，回退到代码内默认值
```

**`.env.example`**（进版本库，作为模板与文档）：

```ini
# ===== 服务 =====
PORT=8000
DEBUG=false
# 留空则每次启动随机生成（多进程部署时需显式设置，否则各进程不一致）
SECRET_KEY=
ALLOWED_ORIGINS=https://wget.hackbyte.io,http://localhost:8000,http://127.0.0.1:8000

# ===== 爬取范围控制 =====
# 单次任务最大页面数（硬护栏）。0 = 不限制
MAX_PAGES=5000
# 是否允许停止根路径 '/'。默认禁止，防止误操作导致任务立即终止
ALLOW_BLOCK_ROOT=false
```

**`.gitignore`** 需新增：

```
.env
.venv/
server.log
__pycache__/
*.pyc
```

**约定**：代码内必须保留默认值，`.env` 仅作覆盖。即 `int(os.environ.get('MAX_PAGES', 5000))`，不得写 `os.environ['MAX_PAGES']`（后者在缺 `.env` 时抛 `KeyError`）。

### 3.3 通信协议结构化

服务端 `SimpleCrawler.log()` 改造为携带统计快照：

```python
def emit_progress(self, msg):
    self.sio.emit(self.token, {
        'progress': msg,
        'files':   self.file_count,
        'pages':   len(self.visited_pages),
        'stats':   dict(self.path_stats),      # 前缀 -> 已抓页面数
        'blocked': list(self.blocked_prefixes),
    })
```

保留 `log()` 名称作为薄封装（`log()` 内部调用 `print` 与 `emit_progress`），避免大范围改动调用点。

前端改为直接读取字段：

```javascript
if (typeof event.files === 'number') { nFilesSpan.textContent = event.files; }
if (typeof event.pages === 'number') { nPagesSpan.textContent = event.pages; }
```

**删除**所有基于 `progress` 文本的正则解析。服务端成为统计数字的唯一真相来源。

### 3.4 路径归类

以**第一层路径段**为归类键：

```python
@staticmethod
def prefix_of(url):
    """取第一层路径段：/2026/07/blog-post_1628.html -> '2026'"""
    seg = urlparse(url).path.strip('/').split('/')[0]
    return seg or '/'
```

示例映射：

| URL | 归类键 |
|---|---|
| `https://www.deep-drama.com/2026/07/blog-post_1628.html` | `2026` |
| `https://www.deep-drama.com/p/about.html` | `p` |
| `https://www.deep-drama.com/search/label/x` | `search` |
| `https://www.deep-drama.com/` | `/`（根路径）|

数据结构：

```python
self.path_stats = defaultdict(int)      # 前缀 -> 已抓页面数
self.blocked_prefixes = set()           # 被用户停止的前缀
```

计数时机：`crawl_page()` 中页面成功获取后 `self.path_stats[self.prefix_of(page_url)] += 1`。

### 3.5 停止收集 — 双点拦截

```python
def is_blocked(self, url):
    return self.prefix_of(url) in self.blocked_prefixes
```

**拦截点 1 — 链接发现时**（`extract_links`）：

```python
if url and self.is_same_domain(url) and not self.is_blocked(url):
    if url not in self.visited_pages and url not in self.pending_pages:
        links.append(url)
```

**拦截点 2 — 队列出队时**（`crawl` 主循环）：

```python
while self.pending_pages:
    page_url = self.pending_pages.pop(0)
    if self.is_blocked(page_url):
        continue                        # 处理「点击时已在队列中」的 URL
    if page_url not in self.visited_pages:
        self.crawl_page(page_url)
```

**两个点都必需**：用户点击停止的那一刻，队列里可能已堆积数百个该类 URL。若只做点 1，「停止」要等这些 URL 全部出队并抓完才生效，与用户预期严重不符。

### 3.6 硬护栏

```python
MAX_PAGES = int(os.environ.get('MAX_PAGES', 5000))
```

主循环中加入：

```python
if MAX_PAGES and len(self.visited_pages) >= MAX_PAGES:
    self.log(f"[上限] 已达最大页面数 {MAX_PAGES}，停止抓取")
    break
```

`MAX_PAGES = 0` 表示不限制（保留给确有需要的用户）。

### 3.7 控制通道（前端 → 服务端）

需要按 token 定位正在运行的 crawler：

```python
ACTIVE_CRAWLERS = {}        # token -> SimpleCrawler

# crawl() 开头
ACTIVE_CRAWLERS[self.token] = self
# crawl() 的 finally 中
ACTIVE_CRAWLERS.pop(self.token, None)
```

事件处理器：

```python
@socketio.on('block_prefix')
def handle_block_prefix(data):
    token  = data.get('token')
    prefix = data.get('prefix')
    crawler = ACTIVE_CRAWLERS.get(token)
    if crawler is None:
        socketio.emit(token, {'progress': '错误：任务已结束'})
        return
    if prefix == '/' and not ALLOW_BLOCK_ROOT:
        socketio.emit(token, {'progress': '错误：不允许停止根路径'})
        return
    with crawler.lock:
        crawler.blocked_prefixes.add(prefix)
```

`@socketio.on('unblock_prefix')` 为对称实现，将前缀从集合移除。

**并发安全**：crawler 在子线程运行、handler 在主线程修改集合，统一用 crawler 已有的 `self.lock` 保护读写。

### 3.8 前端 UI

在统计区下方新增「路径分类」面板，按页面数降序：

```
路径分类
─────────────────────────────
2026        1823 页   [停止收集]
search        57 页   [停止收集]
p             12 页   [停止收集]
```

点击【停止收集】后，**该项原地更新**为 `2026   1823 页  [已停止 · 恢复]`（置灰），不新增行。已抓取数保留显示，便于用户知道停在了哪里。

渲染要求：

- 统计列表面板仅在抓取开始后显示。
- 更新走 **约 300ms 节流**（合并高频 socket 消息，避免每页重排 DOM）。使用时间戳比较，不引入额外依赖。
- 点击【停止收集】→ `socket.emit('block_prefix', {token, prefix})`；【恢复】→ `unblock_prefix`。
- 复用现有 CSS 变量与按钮风格，不引入新样式体系。

---

## 4. 边界情况

| 情况 | 处理 |
|---|---|
| 点击时任务已结束 | `ACTIVE_CRAWLERS` 查不到 token，回「任务已结束」提示 |
| 停止根路径 `/` | 默认拒绝并提示（`ALLOW_BLOCK_ROOT=false`）|
| 同一前缀重复停止 | `set.add` 幂等，无副作用 |
| 恢复一个未停止的前缀 | `set.discard` 幂等，无副作用 |
| 停止后该前缀不再产生新页面 | 仅影响**后续**，已抓取的保留在结果中 |
| `.env` 文件缺失 | `load_dotenv()` 静默跳过，全部使用代码内默认值 |
| `.env` 中值非法（如 `MAX_PAGES=abc`）| 当前设计**会抛 `ValueError` 并阻止启动**。理由：配置错误应当立即暴露，而非静默回退导致用户以为上限生效实际没有 |
| `python-dotenv` 未安装 | **故意不兜底**：与其他依赖一致地在启动时抛 `ImportError`。若静默降级，用户会陷入「明明改了 `.env` 却不生效」的困惑，排查成本远高于一次明确的安装失败 |

---

## 5. 测试策略

### 单元测试（可独立于网络运行）

1. `prefix_of()` 对各类 URL 的归类正确，含根路径、无路径、嵌套路径。
2. `is_blocked()` 在前缀加入后返回 `True`。
3. 路径长度限制（已有实现）与 `prefix_of` 组合时行为正确。

### 集成测试（本地起服务 + 真实站点）

4. **计数正确性**：抓取过程中 `files` 字段随 `file_count` 增长（回归问题二）。断言依据是服务端字段，不是前端文本。
5. **停止生效**：抓取中 emit `block_prefix`，断言：
   - 该前缀不再有新页面进入 `visited_pages`
   - 队列中残留的该类 URL 被跳过（验证拦截点 2）
   - 其他前缀继续正常抓取
6. **硬上限**：将 `MAX_PAGES` 设为极小值（如 5），断言抓取在 5 页后停止且日志明确说明原因。
7. **根路径保护**：emit `block_prefix {prefix: '/'}` 且 `ALLOW_BLOCK_ROOT=false`，断言被拒绝且任务继续。

### 手工验证

8. 浏览器实测：对 `https://www.deep-drama.com/` 发起抓取，观察路径面板计数增长、点击停止后对应分类停止增长、总页面数不再失控。

---

## 6. 影响面

| 文件 | 改动 |
|---|---|
| `app.py` | 新增 `prefix_of`/`is_blocked`/`emit_progress`；`log()` 保留为封装；`extract_links`/`crawl` 加拦截；主循环加上限；新增 `ACTIVE_CRAWLERS` 与两个 socketio handler；配置项迁至带默认值的 `os.environ.get` |
| `static/js/main.js` | 删除正则解析，改读结构化字段；新增路径面板渲染与节流；新增停止/恢复事件 |
| `templates/index.html` | 新增路径分类面板容器 |
| `static/css/style.css` | 面板样式（复用现有变量）|
| `requirements.txt` | 新增 `python-dotenv` |
| `.env.example` | 新增 |
| `.gitignore` | 新增 |
| `README.md` | 补充配置说明章节 |

---

## 7. 实现顺序建议

1. 配置层（`.env` + 加载 + 默认值）— 无行为变化，可独立验证
2. 协议结构化 + 前端改读字段 — **修复问题二**，可独立验证
3. 路径统计 — 数据开始可用
4. 停止/恢复（双点拦截 + 控制通道）— 核心功能
5. 硬护栏 — 兜底
6. UI 打磨与文档
