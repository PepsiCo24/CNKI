@echo off
REM One-click setup + start for Windows (Python 3.11+ and Node.js required).
setlocal
cd /d "%~dp0.."

if not exist .env copy .env.example .env

if not exist .venv (
  echo Creating virtual environment...
  python -m venv .venv
)
call .venv\Scripts\activate.bat
python -m pip install --upgrade pip
pip install -e ".[dev]"
if errorlevel 1 goto :error

pushd frontend
if not exist node_modules npm install
call npm run build
if errorlevel 1 goto :error
popd

echo.
echo Starting CNKI Scholar AI at http://127.0.0.1:8000
start "" http://127.0.0.1:8000
python scripts\run_server.py
goto :eof

:error
echo.
echo Setup failed. Please check Python/Node.js installation and network access.
pause
exit /b 1
