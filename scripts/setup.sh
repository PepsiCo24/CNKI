#!/usr/bin/env bash
# One-time setup for macOS / Linux.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

if [ ! -f .env ]; then
  cp .env.example .env
  echo "Created .env from .env.example"
fi

if [ ! -d .venv ]; then
  if command -v uv >/dev/null 2>&1; then
    uv venv --python 3.12 .venv
  else
    python3 -m venv .venv
  fi
fi

if command -v uv >/dev/null 2>&1; then
  uv pip install -e ".[dev]"
else
  .venv/bin/python -m pip install --upgrade pip
  .venv/bin/python -m pip install -e ".[dev]"
fi

cd frontend
if [ ! -d node_modules ]; then
  npm install
fi
npm run build
cd "$ROOT"

.venv/bin/python - <<'PY'
import sys
sys.path.insert(0, "backend")
from app.database.init_db import init_db
init_db()
print("Database initialized")
PY

echo ""
echo "Setup complete. Start with: ./scripts/start.sh"
