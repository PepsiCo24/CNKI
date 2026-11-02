@echo off
REM Windows development mode: backend + Vite dev server.
setlocal
cd /d "%~dp0.."

if not exist .venv python -m venv .venv
call .venv\Scripts\activate.bat
pip install -e ".[dev]"

start "CNKI Scholar AI Backend" cmd /k python scripts\run_server.py --reload
pushd frontend
if not exist node_modules npm install
npm run dev
popd
