@echo off
REM One-click setup + start for Windows (Python 3.11+ and Node.js required).
setlocal
cd /d "%~dp0.."

if not exist .env copy .env.example .env

if not exist .venv (
  echo Creating virtual environment...
  python -m venv .venv
  if errorlevel 1 goto :error
)
call .venv\Scripts\activate.bat
python -m pip install --upgrade pip
pip install -e ".[dev]"
if errorlevel 1 goto :error

pushd frontend
if not exist node_modules npm install
if errorlevel 1 goto :error
call npm run build
if errorlevel 1 goto :error
popd

if not defined CNKI_HOST set CNKI_HOST=127.0.0.1
if not defined CNKI_PORT set CNKI_PORT=8000
if not defined CNKI_DATA_DIR set CNKI_DATA_DIR=%CD%\data

echo.
echo Starting CNKI Scholar AI at http://%CNKI_HOST%:%CNKI_PORT%
echo API docs: http://%CNKI_HOST%:%CNKI_PORT%/docs
echo Data directory: %CNKI_DATA_DIR%
echo Import directory: configure in Settings - CNKI (default: %CNKI_DATA_DIR%\imports)
echo Press Ctrl+C to stop.
start "" http://%CNKI_HOST%:%CNKI_PORT%
python scripts\run_server.py
goto :eof

:error
echo.
echo Setup failed. Please check Python 3.11+ and Node.js 20+ installation and network access.
pause
exit /b 1
