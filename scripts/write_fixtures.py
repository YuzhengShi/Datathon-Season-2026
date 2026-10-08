"""Write the synthetic demo source documents to tests/fixtures/demo/ so they can be read and diffed without running the pipeline."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from navigator.demo import content  # noqa: E402

target = ROOT / "tests" / "fixtures" / "demo"
target.mkdir(parents=True, exist_ok=True)
for page in content.PAGES:
    (target / f"{page.key}.html").write_bytes(content.render_html(page))
(target / "foundation_guide.pdf").write_bytes(content.render_guide_pdf())
(target / "scanned_notice.pdf").write_bytes(content.render_scanned_pdf())
print("wrote", ", ".join(sorted(p.name for p in target.iterdir())))
