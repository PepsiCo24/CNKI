@echo off
chcp 65001 >nul
REM CNKI Scholar AI — Windows 一键启动（解压后双击本文件）
REM 需要已安装：Python 3.11+、Node.js 20+，并确保 python / npm 在 PATH 中
setlocal EnableExtensions
cd /d "%~dp0"

echo ========================================
echo   CNKI Scholar AI  一键启动
echo ========================================
echo.

where python >nul 2>&1
if errorlevel 1 (
  echo [错误] 未找到 python。请先安装 Python 3.11+ 并勾选 "Add to PATH"。
  pause
  exit /b 1
)

where npm >nul 2>&1
if errorlevel 1 (
  echo [错误] 未找到 npm。请先安装 Node.js 20+。
  pause
  exit /b 1
)

if not exist .env (
  if exist .env.example (
    copy /Y .env.example .env >nul
    echo 已从 .env.example 创建 .env
  )
)

if not exist .venv (
  echo [1/4] 创建虚拟环境...
  python -m venv .venv
  if errorlevel 1 goto :error
) else (
  echo [1/4] 虚拟环境已存在
)

call .venv\Scripts\activate.bat
if errorlevel 1 goto :error

echo [2/4] 安装 Python 依赖...
python -m pip install --upgrade pip >nul
pip install -e ".[dev]"
if errorlevel 1 goto :error

echo [3/4] 构建前端...
pushd frontend
if not exist node_modules (
  call npm install
  if errorlevel 1 (
    popd
    goto :error
  )
)
call npm run build
if errorlevel 1 (
  popd
  goto :error
)
popd

if not defined CNKI_HOST set CNKI_HOST=127.0.0.1
if not defined CNKI_PORT set CNKI_PORT=8000
if not defined CNKI_DATA_DIR set CNKI_DATA_DIR=%CD%\data

echo [4/4] 启动服务...
echo.
echo ----------------------------------------
echo  访问地址: http://%CNKI_HOST%:%CNKI_PORT%
echo  API 文档: http://%CNKI_HOST%:%CNKI_PORT%/docs
echo  数据目录: %CNKI_DATA_DIR%
echo  导入目录: 请在「设置 → 知网接入」配置
echo  停止服务: 本窗口按 Ctrl+C
echo ----------------------------------------
echo.

start "" "http://%CNKI_HOST%:%CNKI_PORT%"
python scripts\run_server.py
goto :eof

:error
echo.
echo 启动失败。请检查：
echo   1. 已安装 Python 3.11+ 且命令行为 python
echo   2. 已安装 Node.js 20+ 且命令行为 npm
echo   3. 网络可访问 PyPI / npm 源
echo.
pause
exit /b 1
