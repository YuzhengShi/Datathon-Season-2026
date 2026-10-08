"""Write the JSON Schema of the JSONL record contract to docs/schemas/ (run after changing the contract)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from navigator.core.contract import record_schema  # noqa: E402

target = ROOT / "docs" / "schemas" / "opportunity-record-1.0.schema.json"
target.parent.mkdir(parents=True, exist_ok=True)
target.write_text(json.dumps(record_schema(), indent=2, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
print(f"wrote {target.relative_to(ROOT)}")
