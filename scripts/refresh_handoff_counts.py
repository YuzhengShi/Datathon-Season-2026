"""Refresh the numbers in docs/HANDOFF.md (per-suite test table and the totals quoted in the text).

Run after changing the test suite:  python scripts/refresh_handoff_counts.py
"""

from __future__ import annotations

import collections
import io
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))


def walk(suite):
    for item in suite:
        if isinstance(item, unittest.TestSuite):
            yield from walk(item)
        else:
            yield item


def main() -> int:
    suite = unittest.defaultTestLoader.discover(str(ROOT / "tests"), top_level_dir=str(ROOT))
    tests = list(walk(suite))
    result = unittest.TextTestRunner(stream=io.StringIO(), verbosity=0).run(suite)
    if not result.wasSuccessful():
        print("tests are failing; not touching HANDOFF.md")
        return 1
    skipped = {t.id() for t, _ in result.skipped}
    counts: dict[str, list[int]] = collections.defaultdict(lambda: [0, 0])
    for t in tests:
        module = t.id().split(".")[1]
        counts[module][0] += 1
        counts[module][1] += t.id() in skipped
    total, skip = result.testsRun, len(result.skipped)
    ran = total - skip
    rows = "\n".join(f"| `tests/{m}.py` | {n} | {n - s} | {s} |" for m, (n, s) in sorted(counts.items()))
    path = ROOT / "docs" / "HANDOFF.md"
    text = path.read_text(encoding="utf-8")
    text = re.sub(r"(\| suite \| tests \| executed \| skipped \|\n\| --- \| --- \| --- \| --- \|\n).*?(\n\n)",
                  lambda m: m.group(1) + rows + f"\n| **total** | **{total}** | **{ran}** | **{skip}** |" + m.group(2), text, flags=re.S)
    text = re.sub(r"by \*\*\d+ executed tests", f"by **{ran} executed tests", text)
    text = re.sub(r"\(\d+ skipped\)", f"({skip} skipped)", text)
    text = re.sub(r"and \d+ tests ran offline", f"and {ran} tests ran offline", text)
    path.write_text(text, encoding="utf-8")
    print(f"HANDOFF.md refreshed: {total} tests, {ran} executed, {skip} skipped")
    return 0


if __name__ == "__main__":
    sys.exit(main())
