document.addEventListener('DOMContentLoaded', function() {
    var downloadFile = '';
    var logLines = [];
    
    var socket = io();
    var myToken = generateToken(20);
    
    var websiteInput = document.getElementById('website');
    var downloadBtn = document.getElementById('download');
    var alertMessage = document.getElementById('alertMessage');
    var progressArea = document.getElementById('progressArea');
    var logConsole = document.getElementById('log');
    var logContent = document.getElementById('logContent');
    var statsGrid = document.getElementById('statsGrid');
    var nFilesSpan = document.getElementById('nFiles');
    var nPagesSpan = document.getElementById('nPages');
    var progressText = document.getElementById('progressText');
    var zipDownloadBtn = document.getElementById('downloadBtn');
    var spinner = document.getElementById('spinner');
    
    function addLog(message, type) {
        var code = document.createElement('code');
        code.textContent = message;
        if (type) code.className = type;
        logLines.push(code.outerHTML);
        if (logLines.length > 50) logLines = logLines.slice(-50);
        logContent.innerHTML = logLines.join('');
        logConsole.scrollTop = logConsole.scrollHeight;
    }
    
    socket.on(myToken, function(event) {
        if (event.progress === 'Converting') {
            progressText.textContent = '压缩中...';
            addLog('正在压缩文件...', 'info');
        } else if (event.progress === 'Completed') {
            spinner.style.display = 'none';
            progressText.textContent = '完成';
            downloadFile = event.file;
            addLog('下载完成!', 'success');
            zipDownloadBtn.style.display = 'inline-block';
            // 抓取结束：按当前输入重新决定「开始下载」是否可用
            downloadBtn.disabled = !validateUrl(websiteInput.value);
        } else if (event.progress.indexOf('Error') !== -1 || event.progress.indexOf('错误') !== -1) {
            addLog(event.progress, 'error');
            // 抓取失败/结束：同样按当前输入恢复按钮状态
            downloadBtn.disabled = !validateUrl(websiteInput.value);
        } else {
            progressArea.style.display = 'block';
            logConsole.style.display = 'block';
            statsGrid.style.display = 'flex';
            
            // 直接读服务端结构化字段，服务端是统计数字的唯一真相来源
            if (typeof event.files === 'number') nFilesSpan.textContent = event.files;
            if (typeof event.pages === 'number') {
                nPagesSpan.textContent = event.pages;
                // 「连接中...」只适用于最初几秒。一旦有进度就换成实时计数，
                // 否则长时间抓取会一直显示「连接中...」，看起来像卡死。
                progressText.textContent = '抓取中 · ' + event.pages + ' 页 / ' +
                    (typeof event.files === 'number' ? event.files : 0) + ' 文件';
            }
            
            var type = '';
            if (event.progress.indexOf('完成') !== -1) type = 'success';
            else if (event.progress.indexOf('[页面]') !== -1) type = 'info';
            if (event.stats) renderStats(event.stats, event.blocked || []);
            addLog(event.progress, type);
        }
    });
    
    function validateUrl(url) {
        return url.startsWith('http://') || url.startsWith('https://');
    }
    
    websiteInput.addEventListener('input', function() {
        downloadBtn.disabled = !validateUrl(this.value);
        alertMessage.style.display = (this.value && !validateUrl(this.value)) ? 'block' : 'none';
    });
    
    downloadBtn.addEventListener('click', function() {
        if (!validateUrl(websiteInput.value)) return;
        logLines = [];
        nFilesSpan.textContent = '0';
        nPagesSpan.textContent = '0';
        zipDownloadBtn.style.display = 'none';
        progressArea.style.display = 'block';
        logConsole.style.display = 'block';
        statsGrid.style.display = 'flex';
        statsPanel.style.display = 'none';
        statsList.innerHTML = '';
        logContent.innerHTML = '';
        spinner.style.display = 'block';
        progressText.textContent = '连接中...';
        addLog('正在连接服务器...', 'info');
        socket.emit('request', { token: myToken, website: websiteInput.value.substring(0, 500) });
        // 抓取期间禁用按钮，避免同一 token 并发提交导致任务互相覆盖
        downloadBtn.disabled = true;
    });
    
    zipDownloadBtn.addEventListener('click', function() {
        // 安全: 防止文件名注入
        if (downloadFile && /^[a-zA-Z0-9][a-zA-Z0-9._-]*$/.test(downloadFile)) {
            window.location = '/sites/' + encodeURIComponent(downloadFile) + '.zip';
        }
    });
    
    var statsPanel = document.getElementById('statsPanel');
    var statsList = document.getElementById('statsList');
    var lastStatsRender = 0;

    // 计数低于此值的前缀不单独成行。单段路径的站点（如 /article-slug/）会让
    // 每篇文章自成一类，大量「1 页」行会淹没面板。这类前缀聚合为「其他」，
    // 既便于查看，也便于一次性停掉散落的一次性页面。
    var SINGLE_THRESHOLD = 2;

    // displayPrefix 用于显示；targets 是这一行代表的前缀（普通行一个，「其他」行多个）；
    // action 为 'none' | 'block' | 'unblock'
    function buildRow(displayPrefix, count, isBlocked, targets, action) {
        var row = document.createElement('div');
        row.className = 'stats-row' + (isBlocked ? ' blocked' : '');

        var label = document.createElement('span');
        var prefixSpan = document.createElement('span');
        prefixSpan.className = 'stats-prefix';
        prefixSpan.textContent = displayPrefix;
        var countSpan = document.createElement('span');
        countSpan.className = 'stats-count';
        countSpan.textContent = count + ' 页';
        label.appendChild(prefixSpan);
        label.appendChild(countSpan);

        var btn = document.createElement('button');
        btn.className = 'stats-btn';
        if (action === 'none') {
            btn.disabled = true;
            btn.textContent = '不可停止';
        } else {
            btn.textContent = action === 'unblock' ? '恢复' : '停止收集';
            btn.addEventListener('click', function () {
                var name = action === 'unblock' ? 'unblock_prefix' : 'block_prefix';
                targets.forEach(function (p) {
                    socket.emit(name, { token: myToken, prefix: p });
                });
            });
        }

        row.appendChild(label);
        row.appendChild(btn);
        return row;
    }

    function renderStats(stats, blocked) {
        // 约 300ms 节流：抓取时进度消息高频到达，避免每页都重排 DOM
        var now = Date.now();
        if (now - lastStatsRender < 300) return;
        lastStatsRender = now;

        statsPanel.style.display = 'block';

        var entries = Object.keys(stats).map(function (k) {
            return { prefix: k, count: stats[k] };
        }).sort(function (a, b) { return b.count - a.count; });

        // 根路径单独处理：它永远不可停止（服务端也会拒绝），不能混进「其他」的批量操作
        var rootEntry = null;
        var notable = [];
        var singles = [];
        entries.forEach(function (e) {
            if (e.prefix === '/') rootEntry = e;
            else if (e.count >= SINGLE_THRESHOLD) notable.push(e);
            else singles.push(e);
        });

        statsList.innerHTML = '';

        notable.forEach(function (e) {
            var isBlocked = blocked.indexOf(e.prefix) !== -1;
            statsList.appendChild(buildRow(
                '/' + e.prefix, e.count, isBlocked, [e.prefix],
                isBlocked ? 'unblock' : 'block'
            ));
        });

        if (singles.length) {
            var all = singles.map(function (e) { return e.prefix; });
            var pending = all.filter(function (p) { return blocked.indexOf(p) === -1; });
            var total = singles.reduce(function (sum, e) { return sum + e.count; }, 0);
            var label = '其他（' + singles.length + ' 类）';
            // 还有未停止的 → 提供「停止收集」（仅针对未停止的那些）；全部已停 → 提供「恢复」
            statsList.appendChild(pending.length
                ? buildRow(label, total, false, pending, 'block')
                : buildRow(label, total, true, all, 'unblock'));
        }

        if (rootEntry) {
            statsList.appendChild(buildRow('/', rootEntry.count, false, [], 'none'));
        }
    }

    function generateToken(n) {
        var chars = 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789';
        var token = '';
        for (var i = 0; i < n; i++) token += chars[Math.floor(Math.random() * chars.length)];
        return token;
    }
    
    // Update time
    function updateTime() {
        var now = new Date();
        var hours = now.getHours();
        var minutes = now.getMinutes();
        var ampm = hours >= 12 ? 'PM' : 'AM';
        hours = hours % 12;
        hours = hours ? hours : 12;
        var timeStr = (hours < 10 ? '0' : '') + hours + ':' + (minutes < 10 ? '0' : '') + minutes + ' ' + ampm;
        document.getElementById('statusTime').textContent = timeStr;
    }
    updateTime();
    setInterval(updateTime, 1000);
    
    // Get IP
    fetch('https://api.ipify.org?format=json')
        .then(function(r) { return r.json(); })
        .then(function(data) {
            document.getElementById('statusIp').textContent = data.ip;
        })
        .catch(function() {
            document.getElementById('statusIp').textContent = '127.0.0.1';
        });
});
