# WebClone — 在线扒站工具

> 粘贴一个网址，把整站源码（HTML / CSS / JS / 图片等静态资源）抓下来并打包成 ZIP。

[![Python](https://img.shields.io/badge/python-3.9%2B-blue.svg)](https://www.python.org/)
[![Flask](https://img.shields.io/badge/flask-2.3%2B-green.svg)](https://flask.palletsprojects.com/)
[![License](https://img.shields.io/badge/license-GPL--3.0-blue.svg)](LICENSE)
[![Disclaimer](https://img.shields.io/badge/usage-read%20DISCLAIMER-red.svg)](DISCLAIMER.md)

**中文** · [English](#english)

> ⚠️ **使用前请先阅读 [免责声明](DISCLAIMER.md)** —— 本工具仅供学习研究与自有网站备份，使用者须自行遵守目标站条款与相关法律。

---

## 目录

- [快速开始](#快速开始)
- [使用说明](#使用说明)
- [控制抓取范围](#控制抓取范围)
- [配置](#配置)
- [常见问题](#常见问题)
- [项目结构](#项目结构)
- [开发](#开发)
- [生产部署](#生产部署)

---

## 快速开始

### 方式一：一键启动（推荐）

**Windows** — 双击 `start.bat`

**Linux / macOS** —

```bash
chmod +x start.sh && ./start.sh
```

脚本自动完成：创建虚拟环境 → 安装依赖 → 启动服务。首次约 1 分钟（取决于网速），之后启动只需几秒。

启动后打开 **http://localhost:8000**

### 方式二：手动启动

```bash
python -m venv .venv
.venv/Scripts/python.exe -m pip install -r requirements.txt   # Windows
# .venv/bin/python -m pip install -r requirements.txt         # Linux / macOS
.venv/Scripts/python.exe app.py
```

> 国内网络较慢时可加镜像源：`-i https://pypi.tuna.tsinghua.edu.cn/simple`

---

## 使用说明

1. 浏览器打开 `http://localhost:8000`
2. 在输入框粘贴目标网址（如 `https://example.com`），点「开始下载」
3. 顶部实时显示 **文件数** 与 **页面数**，右侧日志输出抓取详情
4. 抓完后点「下载 ZIP」拿到打包好的源码

顶部状态文字会随进度变化：

| 显示 | 含义 |
|---|---|
| `连接中...` | 已提交请求，正在等服务器响应（通常几百毫秒）|
| `抓取中 · N 页 / M 文件` | 正在抓取，数字实时增长 |
| `压缩中...` | 抓取完成，正在打包 ZIP |
| `完成` | 打包完毕，可点「下载 ZIP」|

---

## 控制抓取范围

内容站（尤其 SEO 站）的页面会互相链接，不加控制可能抓很久都停不下来。本工具提供三层控制。

### 1. 实时路径分类

抓取过程中，页面下方会出现**路径分类**面板，按 URL 的第一层路径段归类，实时显示每类抓了多少页：

```
路径分类
──────────────────────────
/search       9 页    [停止收集]
/p            3 页    [停止收集]
其他（26 类）  26 页   [停止收集]
/             1 页    不可停止
```

- 点某行的 **「停止收集」**，该路径下不再抓新页面 —— **点击即刻生效**，包括已经在队列里的 URL
- 点 **「恢复」** 可撤销
- 计数为 1 的零散路径会**聚合为「其他」**，避免单篇文章各自成类把面板撑爆；「其他」支持**批量停止**
- 根路径 `/` 永远不可停止（否则任务会瞬间终止）

> 典型用法：发现某个路径（如 `/2026/` 或某类文章页）在无限膨胀，点一下「停止收集」即可止损。

### 2. 页面数硬上限

单个任务最多抓 `MAX_PAGES`（默认 **5000**）个页面，达到后自动停止。**即使你离开电脑，任务也不会无限跑下去。**

### 3. 内置安全限制

请求频率限制（防止对目标站造成压力）、内网地址拦截、单文件与总体积上限。

---

## 配置

所有配置都有代码内默认值，**没有 `.env` 也能正常启动**。需要修改时：

```bash
cp .env.example .env    # 复制模板
# 然后编辑 .env
```

| 变量 | 默认值 | 说明 |
|---|---|---|
| `PORT` | `8000` | 服务监听端口 |
| `DEBUG` | `false` | 调试模式（仅接受 `true` / `false`）|
| `SECRET_KEY` | 每次启动随机生成 | 多进程部署时需显式设置 |
| `ALLOWED_ORIGINS` | 含本机地址 | Socket.IO 允许的来源，逗号分隔 |
| `MAX_PAGES` | `5000` | 单次任务最大页面数，`0` 表示不限制 |
| `ALLOW_BLOCK_ROOT` | `false` | 是否允许停止根路径 `/` |

`.env` 已在 `.gitignore` 中，不会误提交。

---

## 常见问题

**Q：`pip install` 报 `UnicodeDecodeError: 'gbk' codec can't decode ...`**
中文 Windows 的编码问题，已在 `requirements.txt` 首行加编码声明修复。若仍出现，确认首行是 `# -*- coding: utf-8 -*-`。

**Q：页面能打开，但进度、文件数不更新**
Socket.IO 连接失败。最常见原因是浏览器地址与实际访问来源不一致（例如用 `127.0.0.1` 打开，但白名单里只有 `localhost`）。在 `.env` 的 `ALLOWED_ORIGINS` 里把两者都加上。

**Q：报错「下载失败，请稍后重试」**
先看服务端控制台日志。常见两类原因：目标站反爬（403 / 需要登录）、或 URL 超出系统路径长度限制。

**Q：抓了很久一直不停**
这正是本工具要解决的问题 —— 见[控制抓取范围](#控制抓取范围)。若任务已失控，直接停掉服务进程即可，已抓的文件保留在 `downloads/`。

**Q：点了「停止收集」，为什么那行还显示「停止收集」而不是「恢复」？**
因为抓取仍在继续，新的单页路径不断产生，它们不在已停止集合里。这是正常的 —— 该分类已抓的页面确实停了，新出现的需要你再决定一次。

**Q：`gunicorn` 在 Windows 上跑不起来**
正常，`gunicorn` 不支持 Windows。Windows 上直接用 `python app.py`，或用 Docker。

**Q：一次会抓多少页面？**
默认上限 5000。对内容站可能偏大，建议按目标站点规模调小 `MAX_PAGES`。

**Q：跳过的页面会记录吗？**
单页停止后，其已抓取的内容**保留在结果中**（不会删除）。日志里会打印 `[停止] 不再收集 /xxx 下的页面`。

---

## 项目结构

```
webclone/
├── app.py                # 后端全部逻辑（Flask + SimpleCrawler + Socket.IO 事件）
├── start.bat / start.sh  # 一键启动脚本
├── cleanup.py            # 定时清理脚本（清理过期的抓取产物）
├── dedupe.html           # 附带的独立工具页：数据去重
├── templates/index.html  # 主页面
├── static/
│   ├── css/style.css
│   └── js/
│       ├── main.js
│       └── socket.io.min.js   # 本地化引入，不依赖 CDN
├── tests/                # pytest 测试（31 个用例）
├── docs/                 # 设计与实现文档
├── DISCLAIMER.md         # 免责声明（请务必阅读）
├── .env.example          # 配置模板
├── requirements.txt      # 运行时依赖
└── requirements-dev.txt  # 开发依赖（pytest）
```

---

## 开发

```bash
.venv/Scripts/python.exe -m pip install -r requirements-dev.txt
.venv/Scripts/python.exe -m pytest tests/ -v
```

---

## 生产部署

### Docker

```bash
docker build -t webclone .
docker run -d -p 8000:8000 --name webclone webclone
```

> 容器内用 `gunicorn -k gthread` 启动 —— 应用使用 Flask-SocketIO 的 **threading 模式**，必须配多线程 worker；用 `eventlet` worker 会与 threading 模式冲突。

### 裸机（仅 Linux）

`gunicorn` 依赖 `fcntl`，**Windows 上无法运行**。Linux 上：

```bash
pip install -r requirements.txt gunicorn
gunicorn -k gthread -w 1 --threads 100 -b 0.0.0.0:8000 app:app
```

### 定时清理

抓取产物会累积在 `downloads/` 与 `static/sites/`：

```bash
python cleanup.py            # 清理 24 小时前的文件
python cleanup.py --hours 6  # 清理 6 小时前的
python cleanup.py --all      # 全部清理
```

---

## 使用限制

- 仅支持 HTTP/HTTPS，不支持需要登录的网站
- 不支持动态渲染的 SPA（本工具解析静态 HTML，不执行 JavaScript）
- 不支持需要 JavaScript 才能加载的资源

**完整的使用条款、禁止事项与责任划分，见 [DISCLAIMER.md](DISCLAIMER.md)。**

---

## 技术栈

| 层 | 技术 |
|---|---|
| 后端 | Flask + Flask-SocketIO（threading 模式）|
| 实时通信 | Socket.IO（客户端本地化，不依赖 CDN）|
| HTML 解析 | BeautifulSoup4 |
| HTTP 请求 | 内置 `urllib`，无额外 HTTP 库 |
| 并发 | `ThreadPoolExecutor` + `threading.Lock` |
| 配置 | `python-dotenv` + 环境变量 |
| 测试 | pytest（31 用例）|

---

## 开源协议

[GNU General Public License v3.0](LICENSE)

本项目基于 [HackByte.io](https://hackbyte.io) 的 WebClone 修改而来，遵循 GPL-3.0 发布。
按 GPL-3.0 的要求，任何人都可以自由使用、修改、分发本项目，但**衍生作品必须同样以 GPL-3.0 开源**。

## 致谢

原始项目由 [黑客字节 HackByte.io](https://hackbyte.io) 开发。

---
---

<a name="english"></a>

# English

> Paste a URL, download the whole site's static assets (HTML / CSS / JS / images) and get them as a ZIP.

**中文** · **English**

> ⚠️ **Read the [DISCLAIMER](DISCLAIMER.md) before use.** This tool is for learning, research, and backing up sites you own. You are responsible for complying with the target site's terms and applicable law.

## Quick Start

**One command:**

```bash
# Windows
start.bat

# Linux / macOS
chmod +x start.sh && ./start.sh
```

The script creates a virtualenv, installs dependencies, and starts the server. Then open **http://localhost:8000**.

**Manual:**

```bash
python -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python app.py
```

## Usage

1. Open `http://localhost:8000`
2. Paste a URL (e.g. `https://example.com`) and click **开始下载 / Start**
3. Watch live file & page counters, plus a streaming log
4. Click **下载 ZIP / Download ZIP** when finished

### Controlling crawl scope

Content-heavy sites link to each other endlessly. Three safeguards:

**Live path buckets** — pages are grouped by their first path segment, shown live with per-bucket counts. Click **停止收集 / Stop collecting** on a bucket to stop fetching it — **effective immediately**, including URLs already queued. Single-page buckets are merged into an **其他 / Other** row to keep the panel readable.

**Hard page cap** — `MAX_PAGES` (default **5000**) stops the crawl automatically, so an unattended run can't go forever.

**Built-in limits** — request-rate limiting, internal-network blocking, per-file and total size caps.

## Configuration

Every setting has an in-code default — **the app starts fine without `.env`**.

```bash
cp .env.example .env
```

| Variable | Default | Description |
|---|---|---|
| `PORT` | `8000` | Listening port |
| `DEBUG` | `false` | Debug mode (`true` / `false` only) |
| `SECRET_KEY` | random per start | Set explicitly for multi-process deploys |
| `ALLOWED_ORIGINS` | includes localhost | Socket.IO allowed origins, comma-separated |
| `MAX_PAGES` | `5000` | Max pages per task; `0` = unlimited |
| `ALLOW_BLOCK_ROOT` | `false` | Allow stopping the root path `/` |

## Requirements

- Python 3.9+
- HTTP/HTTPS only; no login-protected sites
- No JavaScript execution — dynamic SPAs are not supported

## Docker

```bash
docker build -t webclone .
docker run -d -p 8000:8000 --name webclone webclone
```

Runs `gunicorn -k gthread` — the app uses Flask-SocketIO's **threading** mode, so a multi-threaded worker is required (`eventlet` conflicts with it).

## License

[GNU General Public License v3.0](LICENSE)

This project is a modified version of WebClone by [HackByte.io](https://hackbyte.io), released under GPL-3.0.
As required by GPL-3.0, you may freely use, modify, and redistribute it — but **derivative works must also be open-sourced under GPL-3.0**.

Original project by [HackByte.io](https://hackbyte.io).
