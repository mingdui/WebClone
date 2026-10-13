FROM python:3.10-slim

WORKDIR /app

# 仅在容器内安装的部署依赖（gunicorn 在 Windows 上无法运行，故不入 requirements.txt）
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt gunicorn \
    -i https://pypi.tuna.tsinghua.edu.cn/simple

COPY . .

EXPOSE 8000

# 关键：Flask-SocketIO 在 app.py 中使用 async_mode='threading'，
# 因此必须用 gunicorn 的 gthread worker（多线程）。
# 用 `-k eventlet` 会 monkey-patch 并与 threading 模式冲突，导致 Socket.IO 连接失败。
CMD ["gunicorn", "-k", "gthread", "-w", "1", "--threads", "100", \
     "-b", "0.0.0.0:8000", "app:app"]
