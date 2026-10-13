#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
WebClone — 在线扒站工具

粘贴网址，抓取整站静态资源并打包为 ZIP。
"""

import os
import zipfile
import shutil
import re
import hashlib
import ssl
import socket
import time
from urllib.parse import urljoin, urlparse, urlunparse, quote, unquote
from urllib.request import Request, build_opener, HTTPCookieProcessor, HTTPSHandler
from urllib.error import URLError, HTTPError
from http.cookiejar import CookieJar
from threading import Thread, Lock
from concurrent.futures import ThreadPoolExecutor, as_completed
from flask import Flask, render_template, send_from_directory, abort
from flask_socketio import SocketIO
from bs4 import BeautifulSoup
import ipaddress
import secrets
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
        f'http://localhost:{PORT}',
        f'http://127.0.0.1:{PORT}',
    )),
).split(',')
MAX_PAGES = int(os.environ.get('MAX_PAGES', 5000))
ALLOW_BLOCK_ROOT = os.environ.get('ALLOW_BLOCK_ROOT', 'false').lower() == 'true'

app = Flask(__name__)
app.config['SECRET_KEY'] = SECRET_KEY
socketio = SocketIO(app, cors_allowed_origins=ALLOWED_ORIGINS, async_mode='threading')

# 正在运行的抓取任务：token -> SimpleCrawler，供 socketio 控制事件定位
ACTIVE_CRAWLERS = {}

# 安全: 速率限制
from collections import defaultdict
import time as time_module
REQUEST_LIMIT = defaultdict(list)  # IP -> [时间戳]
MAX_REQUESTS_PER_MINUTE = 5
MAX_FILE_SIZE = 50 * 1024 * 1024  # 单文件50MB限制
MAX_TOTAL_SIZE = 200 * 1024 * 1024  # 总大小200MB限制

# 目录配置
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DOWNLOAD_DIR = os.path.join(BASE_DIR, 'downloads')
SITES_DIR = os.path.join(BASE_DIR, 'static', 'sites')

os.makedirs(DOWNLOAD_DIR, exist_ok=True)
os.makedirs(SITES_DIR, exist_ok=True)

# 请求头
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
    'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
}

# 禁止爬取的域名后缀
BLOCKED_SUFFIXES = {'.gov', '.gov.cn', '.mil', '.edu', '.edu.cn', '.ac.uk', '.hospital'}

# 安全: 禁止爬取的内网IP和特殊域名
BLOCKED_HOSTS = {'localhost', '127.0.0.1', '0.0.0.0', '::1'}

def is_private_ip(hostname):
    """检查是否为内网IP"""
    try:
        ip = ipaddress.ip_address(hostname)
        return ip.is_private or ip.is_loopback or ip.is_reserved
    except ValueError:
        # 不是IP地址，是域名
        return hostname.lower() in BLOCKED_HOSTS

def is_safe_url(url):
    """检查URL是否安全"""
    try:
        # 安全: URL长度限制
        if not url or len(url) > 500:
            return False
            
        parsed = urlparse(url)
        host = parsed.netloc.split(':')[0]  # 移除端口
        
        # 检查内网IP
        if is_private_ip(host):
            return False
        
        # 检查禁止的域名后缀
        for suffix in BLOCKED_SUFFIXES:
            if host.endswith(suffix):
                return False
        
        # 检查协议
        if parsed.scheme not in ('http', 'https'):
            return False
            
        return True
    except:
        return False

# 允许下载的CDN域名（用于Canvas/WebGL等外部资源）
ALLOWED_CDN_DOMAINS = {
    'cdnjs.cloudflare.com', 'cdn.jsdelivr.net', 'unpkg.com',
    'fonts.googleapis.com', 'fonts.gstatic.com', 'ajax.googleapis.com',
    'code.jquery.com', 'stackpath.bootstrapcdn.com', 'maxcdn.bootstrapcdn.com',
    'cdn.bootcdn.net', 'cdn.bootcss.com', 'lib.baomitu.com', 'cdn.staticfile.org',
    'threejs.org', 'cdn.threejs.org', 'rawgit.com', 'raw.githubusercontent.com',
    'greensock.com', 'gw.alipayobjects.com', 'at.alicdn.com',
}

# Canvas/WebGL相关的文件扩展名
CANVAS_RESOURCE_EXTS = {
    # 3D模型
    '.obj', '.mtl', '.gltf', '.glb', '.fbx', '.dae', '.3ds', '.stl', '.ply',
    # 纹理/贴图
    '.dds', '.ktx', '.ktx2', '.basis', '.hdr', '.exr', '.tga',
    # Shader
    '.glsl', '.vert', '.frag', '.vs', '.fs', '.shader',
    # 音频
    '.mp3', '.ogg', '.wav', '.m4a', '.aac', '.flac',
    # 字体
    '.woff', '.woff2', '.ttf', '.otf', '.eot',
    # 数据文件
    '.json', '.xml', '.csv', '.bin', '.dat',
}


@app.route('/')
def index():
    return render_template('index.html', title='网站下载器')


# 安全: 添加安全响应头
@app.after_request
def add_security_headers(response):
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-Frame-Options'] = 'DENY'
    response.headers['X-XSS-Protection'] = '1; mode=block'
    response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
    # CSP: 允许自己的资源和Socket.IO CDN
    response.headers['Content-Security-Policy'] = (
        "default-src 'self'; "
        "script-src 'self' 'unsafe-inline' https://cdnjs.cloudflare.com; "
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
        "img-src 'self' https: data:; "
        "connect-src 'self' wss: ws: https://api.ipify.org; "
        "font-src 'self' https:; "
        "frame-ancestors 'none';"
    )
    return response


@app.route('/sites/<filename>')
def download_file(filename):
    # 安全: 防止路径遍历
    if '..' in filename or filename.startswith('/') or '/' in filename:
        abort(403)
    # 只允许.zip文件
    if not filename.endswith('.zip'):
        abort(403)
    return send_from_directory(SITES_DIR, filename, as_attachment=True)


class SimpleCrawler:
    """简洁可靠的网站爬虫"""
    
    def __init__(self, url, save_dir, token, sio):
        self.start_url = url
        self.save_dir = save_dir
        self.token = token
        self.sio = sio
        
        parsed = urlparse(url)
        self.domain = parsed.netloc
        self.scheme = parsed.scheme or 'https'
        
        self.downloaded = {}      # url -> filepath
        self.visited_pages = set()
        self.pending_pages = []
        self.lock = Lock()
        self.file_count = 0
        self.total_size = 0
        self.path_stats = defaultdict(int)   # 路径前缀 -> 已抓页面数
        self.blocked_prefixes = set()        # 用户点击「停止收集」的前缀
        self.fetch_errors = defaultdict(int)  # 请求失败原因 -> 次数（资源失败不逐条刷屏）

        # 创建SSL上下文（复用）
        self.ssl_ctx = ssl.create_default_context()
        self.ssl_ctx.check_hostname = False
        self.ssl_ctx.verify_mode = ssl.CERT_NONE
    
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
    
    def fetch(self, url, retry=2, silent=False):
        """下载URL内容

        失败时记录具体原因。原先用裸 except 吞掉一切，使用者只能看到
        「资源没下下来」却不知为何，无法判断是反爬、超时还是网络问题。
        silent=True 用于资源下载：不逐条刷屏，改为计入 self.fetch_errors，
        由 crawl() 结束时汇总输出。
        """
        reason = None
        for i in range(retry):
            try:
                opener = build_opener(
                    HTTPSHandler(context=self.ssl_ctx),
                    HTTPCookieProcessor(CookieJar())
                )
                req = Request(url)
                for k, v in HEADERS.items():
                    req.add_header(k, v)

                resp = opener.open(req, timeout=5)
                content = resp.read()
                content_type = resp.headers.get('Content-Type', '')
                resp.close()
                return content, content_type
            except HTTPError as e:
                # 4xx 是服务器明确拒绝（403 反爬 / 404 等），重试没有意义
                reason = f'HTTP {e.code}'
                if 400 <= e.code < 500:
                    break
            except URLError as e:
                reason = f'连接失败({e.reason})'
            except Exception as e:
                reason = f'{type(e).__name__}'

        if reason:
            with self.lock:
                self.fetch_errors[reason] += 1
            if not silent:
                self.log(f"  [失败] {reason} — {url[:120]}")
        return None, ''
    
    # Windows MAX_PATH 为 260，留出余量避免边缘情况
    MAX_PATH_LEN = 240
    MAX_SEG_LEN = 80

    def shorten_seg(self, seg, limit):
        """压缩单个路径段：保留可读前缀与扩展名，附加哈希保证唯一"""
        if len(seg) <= limit:
            return seg
        stem, ext = os.path.splitext(seg)
        digest = hashlib.md5(seg.encode()).hexdigest()[:8]
        keep = limit - len(digest) - len(ext) - 1
        if keep < 1:
            return (digest + ext)[:limit]
        return f"{stem[:keep]}_{digest}{ext}"

    def limit_path_len(self, path):
        """限制相对路径长度，避免 Windows 路径超限导致 os.makedirs 失败"""
        budget = self.MAX_PATH_LEN - len(os.path.join(self.save_dir, self.domain)) - 1
        parts = path.split('/')
        if len(path) <= budget and all(len(s) <= self.MAX_SEG_LEN for s in parts):
            return path
        per_seg = max(16, min(self.MAX_SEG_LEN, (budget - len(parts) + 1) // len(parts)))
        return '/'.join(self.shorten_seg(s, per_seg) for s in parts)

    @staticmethod
    def prefix_of(url):
        """取第一层路径段作为归类键：/2026/07/xxx.html -> '2026'"""
        seg = urlparse(url).path.strip('/').split('/')[0]
        return seg or '/'

    def is_blocked(self, url):
        """该 URL 所属的路径分类是否已被用户停止"""
        with self.lock:
            return self.prefix_of(url) in self.blocked_prefixes

    def url_to_path(self, url):
        """URL转本地文件路径"""
        parsed = urlparse(url)
        path = parsed.path or '/index.html'
        if path == '/':
            path = '/index.html'
        elif path.endswith('/'):
            path += 'index.html'
        elif '.' not in os.path.basename(path):
            path += '.html'
        
        # 处理查询字符串
        if parsed.query:
            h = hashlib.md5(parsed.query.encode()).hexdigest()[:8]
            base, ext = os.path.splitext(path)
            path = f"{base}_{h}{ext}"
        
        path = path.lstrip('/')
        path = re.sub(r'[<>:"|?*]', '_', path)
        path = self.limit_path_len(path)
        
        # 使用域名作为子目录
        return os.path.join(self.save_dir, self.domain, path)
    
    def save(self, url, content, content_type=''):
        """保存文件"""
        filepath = self.url_to_path(url)
        os.makedirs(os.path.dirname(filepath), exist_ok=True)
        
        mode = 'wb' if isinstance(content, bytes) else 'w'
        encoding = None if isinstance(content, bytes) else 'utf-8'
        
        with open(filepath, mode, encoding=encoding) as f:
            f.write(content)
        
        with self.lock:
            self.downloaded[url] = filepath
            self.file_count += 1
            if isinstance(content, bytes):
                self.total_size += len(content)
            else:
                self.total_size += len(content.encode('utf-8'))
        
        return filepath
    
    def is_same_domain(self, url):
        """检查是否同域名或允许的CDN"""
        parsed = urlparse(url)
        host = parsed.netloc
        if host == self.domain or host == '':
            return True
        # 允许CDN域名
        for cdn in ALLOWED_CDN_DOMAINS:
            if host == cdn or host.endswith('.' + cdn):
                return True
        return False
    
    def is_allowed_resource(self, url):
        """检查是否允许下载的资源"""
        parsed = urlparse(url)
        host = parsed.netloc
        path = parsed.path.lower()
        
        # 同域名资源
        if host == self.domain or host == '':
            return True
        
        # CDN资源
        for cdn in ALLOWED_CDN_DOMAINS:
            if host == cdn or host.endswith('.' + cdn):
                return True
        
        # Canvas相关扩展名
        for ext in CANVAS_RESOURCE_EXTS:
            if path.endswith(ext):
                return True
        
        # 常见静态资源
        if any(path.endswith(ext) for ext in ['.js', '.css', '.png', '.jpg', '.jpeg', '.gif', '.svg', '.webp', '.ico']):
            return True
        
        return False
    
    def normalize_url(self, url, base_url):
        """标准化URL

        统一百分号编码是关键：同一页面可能以两种形式出现在 HTML 里——
        原始字符（/label/مسلسل）与百分号编码（/label/%D9%85...），
        两者字节相同但字符串不同。不归一的话去重失效，同一页会被抓两次。
        顺带把空格等非法字符编码掉（空格是非法 URL 字符，会导致请求异常）。
        """
        if not url or url.startswith(('data:', 'javascript:', 'mailto:', '#')):
            return None
        if url.startswith('//'):
            url = self.scheme + ':' + url
        full = urljoin(base_url, url)
        parsed = urlparse(full)

        # 先 unquote 再 quote：两种写法归一到同一种
        # safe 保留 URL 中有语义的保留字符，避免破坏路径与查询串结构
        path = quote(unquote(parsed.path), safe="/%:@&=+$,;~()*!'")
        query = quote(unquote(parsed.query), safe="=&%:@+,;~()*!'/?")

        # 域名大小写不敏感；移除 fragment
        return urlunparse((
            parsed.scheme.lower(),
            parsed.netloc.lower(),
            path,
            '',
            query,
            '',
        ))
    
    def extract_resources(self, soup, page_url):
        """提取页面中的所有资源URL（包括Canvas/WebGL资源）"""
        resources = []
            
        # CSS
        for tag in soup.find_all('link', rel='stylesheet'):
            href = tag.get('href')
            if href:
                url = self.normalize_url(href, page_url)
                if url and self.is_allowed_resource(url):
                    resources.append(url)
            
        # JS
        for tag in soup.find_all('script', src=True):
            src = tag.get('src')
            if src:
                url = self.normalize_url(src, page_url)
                if url and self.is_allowed_resource(url):
                    resources.append(url)
            
        # 图片
        for tag in soup.find_all('img'):
            for attr in ['src', 'data-src', 'data-original']:
                src = tag.get(attr)
                if src and not src.startswith('data:'):
                    url = self.normalize_url(src, page_url)
                    if url and self.is_allowed_resource(url):
                        resources.append(url)
            
        # 图标
        for tag in soup.find_all('link', rel=lambda x: x and 'icon' in str(x).lower()):
            href = tag.get('href')
            if href:
                url = self.normalize_url(href, page_url)
                if url and self.is_allowed_resource(url):
                    resources.append(url)
            
        # 视频/音频
        for tag in soup.find_all(['video', 'audio', 'source']):
            src = tag.get('src')
            if src:
                url = self.normalize_url(src, page_url)
                if url and self.is_allowed_resource(url):
                    resources.append(url)
            
        # 背景图片 (style属性)
        for tag in soup.find_all(style=True):
            style = tag.get('style', '')
            urls = re.findall(r'url\(["\']?([^)"\']+)["\']?\)', style)
            for u in urls:
                if not u.startswith('data:'):
                    url = self.normalize_url(u, page_url)
                    if url and self.is_allowed_resource(url):
                        resources.append(url)
            
        # style标签中的url()
        for style_tag in soup.find_all('style'):
            if style_tag.string:
                urls = re.findall(r'url\(["\']?([^)"\']+)["\']?\)', style_tag.string)
                for u in urls:
                    if not u.startswith('data:'):
                        url = self.normalize_url(u, page_url)
                        if url and self.is_allowed_resource(url):
                            resources.append(url)
            
        # 从JS代码中提取Canvas/WebGL资源路径
        for script_tag in soup.find_all('script'):
            if script_tag.string:
                js_content = script_tag.string
                # 提取字符串中的资源路径
                patterns = [
                    r'["\']([^"\'·]+\.(?:obj|mtl|gltf|glb|fbx|dae|json|bin|png|jpg|jpeg|gif|webp|mp3|ogg|wav|glsl|vert|frag))["\']',
                    r'load\(["\']([^"\'·]+)["\']',
                    r'src\s*[=:]\s*["\']([^"\'·]+)["\']',
                ]
                for pattern in patterns:
                    matches = re.findall(pattern, js_content, re.IGNORECASE)
                    for match in matches:
                        if match and not match.startswith(('data:', 'blob:', 'javascript:')):
                            url = self.normalize_url(match, page_url)
                            if url and self.is_allowed_resource(url):
                                resources.append(url)
            
        return list(set(resources))
    
    def extract_links(self, soup, page_url):
        """提取页面中的所有链接"""
        links = []
        for a in soup.find_all('a', href=True):
            href = a.get('href', '').strip()
            if not href or href.startswith(('#', 'javascript:', 'mailto:')):
                continue
            url = self.normalize_url(href, page_url)
            if url and self.is_same_domain(url) and not self.is_blocked(url):
                if url not in self.visited_pages and url not in self.pending_pages:
                    links.append(url)
        return links
    
    def process_css(self, css_content, css_url):
        """处理CSS中的url()引用"""
        def replace_url(match):
            original = match.group(1)
            if original.startswith('data:'):
                return match.group(0)
            full_url = self.normalize_url(original, css_url)
            if full_url:
                # 下载资源
                content, _ = self.fetch(full_url)
                if content:
                    self.save(full_url, content)
                    # 返回相对路径
                    rel = os.path.relpath(
                        self.url_to_path(full_url),
                        os.path.dirname(self.url_to_path(css_url))
                    ).replace('\\', '/')
                    return f'url("{rel}")'
            return match.group(0)
        
        return re.sub(r'url\(["\']?([^)"\']+)["\']?\)', replace_url, css_content)
    
    def download_resource(self, url):
        """下载单个资源"""
        with self.lock:
            if url in self.downloaded:
                return True
            self.downloaded[url] = True  # 先标记防止重复
        
        content, content_type = self.fetch(url, silent=True)
        if content is None:
            return False
        
        # 处理CSS文件中的引用
        if 'text/css' in content_type or url.endswith('.css'):
            try:
                text = content.decode('utf-8')
                text = self.process_css(text, url)
                content = text.encode('utf-8')
            except:
                pass
        
        try:
            filepath = self.save(url, content, content_type)
        except OSError as e:
            # 单个资源保存失败不应中断整个抓取任务
            self.log(f"[跳过] 保存失败 {url}: {e}")
            return False
        with self.lock:
            self.downloaded[url] = filepath
        return True
    
    def crawl_page(self, page_url):
        """爬取单个页面"""
        if page_url in self.visited_pages:
            return
        
        self.visited_pages.add(page_url)
        with self.lock:
            self.path_stats[self.prefix_of(page_url)] += 1
        self.log(f"[页面] {page_url}")
        
        # 下载页面
        content, content_type = self.fetch(page_url)
        if content is None:
            return
        
        # 只处理HTML
        if 'text/html' not in content_type:
            self.save(page_url, content, content_type)
            return
        
        # 解析HTML
        try:
            html = content.decode('utf-8', errors='ignore')
        except:
            html = content.decode('latin-1', errors='ignore')
        
        soup = BeautifulSoup(html, 'html.parser')
        
        # 提取并并发下载资源
        resources = self.extract_resources(soup, page_url)
        new_resources = [r for r in resources if r not in self.downloaded]
        
        if new_resources:
            self.log(f"  下载 {len(new_resources)} 个资源...")
            with ThreadPoolExecutor(max_workers=30) as executor:
                list(executor.map(self.download_resource, new_resources))
            self.log(f"  资源下载完成")
        
        # 提取链接
        links = self.extract_links(soup, page_url)
        if links:
            self.log(f"  发现 {len(links)} 个新页面链接")
            self.pending_pages.extend(links)
        
        # 保存HTML
        self.save(page_url, html, content_type)
    
    def crawl(self):
        """开始爬取"""
        # 检查禁止域名
        for suffix in BLOCKED_SUFFIXES:
            if self.domain.endswith(suffix):
                self.log(f"[禁止] 不允许爬取 {suffix} 域名")
                return self.domain
        
        self.log("=" * 50)
        self.log(f"开始爬取: {self.start_url}")
        self.log(f"目标域名: {self.domain}")
        self.log("=" * 50)
        
        start_time = time.time()

        # 注册到全局表，供 socketio handler 定位
        ACTIVE_CRAWLERS[self.token] = self
        try:
            # 添加起始URL
            self.pending_pages.append(self.start_url)

            # 循环处理所有页面
            while self.pending_pages:
                if MAX_PAGES and len(self.visited_pages) >= MAX_PAGES:
                    self.log(f"[上限] 已达最大页面数 {MAX_PAGES}，停止抓取")
                    break
                page_url = self.pending_pages.pop(0)
                if self.is_blocked(page_url):
                    continue          # 用户点击停止时已在队列中的 URL
                if page_url not in self.visited_pages:
                    self.crawl_page(page_url)
        finally:
            ACTIVE_CRAWLERS.pop(self.token, None)

        elapsed = time.time() - start_time
        
        self.log("=" * 50)
        self.log(f"爬取完成!")
        self.log(f"下载文件: {self.file_count} 个")
        self.log(f"总大小: {self.total_size / 1024 / 1024:.2f} MB")
        self.log(f"耗时: {elapsed:.1f} 秒")

        # 失败汇总：资源失败不逐条刷屏，但必须让使用者知道「失败了多少、为什么」
        if self.fetch_errors:
            total_failed = sum(self.fetch_errors.values())
            detail = '，'.join(
                f'{reason} × {count}'
                for reason, count in sorted(self.fetch_errors.items(), key=lambda x: -x[1])[:5]
            )
            other = len(self.fetch_errors) - 5
            if other > 0:
                detail += f'，其它 {other} 种'
            self.log(f"请求失败: {total_failed} 个（{detail}）")

        self.log("=" * 50)
        
        return self.domain


def create_zip(source_dir, zip_path):
    """创建ZIP压缩包"""
    with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
        for root, dirs, files in os.walk(source_dir):
            for file in files:
                file_path = os.path.join(root, file)
                arcname = os.path.relpath(file_path, source_dir)
                zipf.write(file_path, arcname)


def download_website(token, website):
    """下载网站主函数"""
    socketio.emit(token, {'progress': '服务器已收到请求...'})
    
    parsed = urlparse(website)
    if not parsed.scheme:
        website = 'https://' + website
        parsed = urlparse(website)
    
    domain = parsed.netloc
    if not domain:
        socketio.emit(token, {'progress': '错误：无效的URL'})
        return
    
    work_dir = os.path.join(DOWNLOAD_DIR, token)
    os.makedirs(work_dir, exist_ok=True)
    
    try:
        crawler = SimpleCrawler(website, work_dir, token, socketio)
        domain = crawler.crawl()
        
        socketio.emit(token, {'progress': 'Converting'})
        
        downloaded_dir = os.path.join(work_dir, domain)
        
        if os.path.exists(downloaded_dir) and os.listdir(downloaded_dir):
            zip_path = os.path.join(SITES_DIR, f"{domain}.zip")
            create_zip(downloaded_dir, zip_path)
            shutil.rmtree(work_dir, ignore_errors=True)
            socketio.emit(token, {'progress': 'Completed', 'file': domain})
        else:
            socketio.emit(token, {'progress': '错误：下载失败'})
            shutil.rmtree(work_dir, ignore_errors=True)
            
    except Exception as e:
        # 安全: 不暴露详细错误信息
        print(f"[ERROR] {str(e)}")
        import traceback
        traceback.print_exc()  # 只在服务器日志记录
        socketio.emit(token, {'progress': '错误：下载失败，请稍后重试'})
        shutil.rmtree(work_dir, ignore_errors=True)


@socketio.on('connect')
def handle_connect():
    print('客户端已连接')


@socketio.on('disconnect')
def handle_disconnect():
    print('客户端已断开')


@socketio.on('request')
def handle_request(data):
    token = data.get('token')
    website = data.get('website')
    
    # 安全: 速率限制
    from flask import request
    client_ip = request.remote_addr or 'unknown'
    now = time_module.time()
    
    # 清理过期记录
    REQUEST_LIMIT[client_ip] = [t for t in REQUEST_LIMIT[client_ip] if now - t < 60]
    
    if len(REQUEST_LIMIT[client_ip]) >= MAX_REQUESTS_PER_MINUTE:
        socketio.emit(token, {'progress': '错误：请求过于频繁，请稍后再试'})
        return
    
    REQUEST_LIMIT[client_ip].append(now)
    
    # 安全: URL安全检查
    if not website or not is_safe_url(website):
        socketio.emit(token, {'progress': '错误：不允许的URL'})
        return
    
    print(f"收到请求: {website} (IP: {client_ip})")
    
    thread = Thread(target=download_website, args=(token, website))
    thread.daemon = True
    thread.start()


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


if __name__ == '__main__':
    port = PORT
    debug = DEBUG
    
    print("=" * 50)
    print("在线扒站工具 - Python Flask 版本")
    if port == 80:
        print("访问地址: http://localhost/")
    else:
        print(f"访问地址: http://localhost:{port}/")
    print("=" * 50)
    socketio.run(app, host='0.0.0.0', port=port, debug=debug)
