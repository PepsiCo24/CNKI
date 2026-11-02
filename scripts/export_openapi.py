"""Export the OpenAPI schema to docs/openapi.json for offline API reference."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.main import app  # noqa: E402

schema = app.openapi()
target = ROOT / "docs" / "openapi.json"
target.write_text(json.dumps(schema, ensure_ascii=False, indent=2), encoding="utf-8")
print(f"Wrote {target} ({len(schema.get('paths', {}))} paths)")
