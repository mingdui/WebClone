#!/usr/bin/env bash
set -e

# 切换到脚本所在目录，确保从任意位置调用都能正常工作
cd "$(dirname "$0")"

echo
echo "========================================"
echo "  WebClone 一键启动"
echo "========================================"
echo

PY=""
for candidate in python3 python; do
    if command -v "$candidate" >/dev/null 2>&1; then
        PY="$candidate"
        break
    fi
done

if [ -z "$PY" ]; then
    echo "[错误] 未找到 python3，请先安装 Python 3.9+。"
    exit 1
fi

if [ ! -x ".venv/bin/python" ]; then
    echo "[1/3] 创建虚拟环境 .venv ..."
    "$PY" -m venv .venv
else
    echo "[1/3] 虚拟环境已存在，跳过创建"
fi

echo "[2/3] 检查并安装依赖 ..."
# 国内网络较慢时可保留镜像源；海外环境可删掉 -i 参数使用默认源
.venv/bin/python -m pip install -q -r requirements.txt \
    -i https://pypi.tuna.tsinghua.edu.cn/simple

echo "[3/3] 启动服务 ..."
echo
echo "   访问地址: http://localhost:8000"
echo "   停止服务: 按 Ctrl+C"
echo
exec .venv/bin/python app.py
