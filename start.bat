@echo off
chcp 65001 >nul
setlocal

rem 切换到脚本所在目录，确保从任意位置调用都能正常工作
cd /d "%~dp0"

echo.
echo ========================================
echo   WebClone 一键启动
echo ========================================
echo.

where python >nul 2>nul
if errorlevel 1 (
    echo [错误] 未找到 Python。
    echo        请先安装 Python 3.9+ 并勾选 "Add Python to PATH"。
    echo        下载地址: https://www.python.org/downloads/
    echo.
    pause
    exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
    echo [1/3] 创建虚拟环境 .venv ...
    python -m venv .venv
    if errorlevel 1 (
        echo [错误] 创建虚拟环境失败。
        pause
        exit /b 1
    )
) else (
    echo [1/3] 虚拟环境已存在，跳过创建
)

echo [2/3] 检查并安装依赖 ...
.venv\Scripts\python.exe -m pip install -q -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
if errorlevel 1 (
    echo [错误] 依赖安装失败，请检查网络后重试。
    pause
    exit /b 1
)

echo [3/3] 启动服务 ...
echo.
echo    访问地址: http://localhost:8000
echo    停止服务: 按 Ctrl+C
echo.
.venv\Scripts\python.exe app.py

echo.
echo 服务已停止。
pause
