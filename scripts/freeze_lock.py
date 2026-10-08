"""Write an exact lock file from the current environment (run after a green test run)."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

HEADER = "# Exact versions frozen from a working environment by scripts/freeze_lock.py.\n"


def main() -> int:
    frozen = subprocess.run(
        [sys.executable, "-m", "pip", "freeze", "--exclude-editable"], check=True, capture_output=True, text=True
    ).stdout
    Path("requirements.lock").write_text(HEADER + frozen, encoding="utf-8")
    print("requirements.lock written")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
