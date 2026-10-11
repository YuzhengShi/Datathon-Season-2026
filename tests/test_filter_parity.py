"""The site filters in the browser (dist/model.js) and on the server (navigator/app/services.py): they must agree.

A page without a backend (static hosting) filters and computes Statistics itself; with the backend it asks ``/api/*``.
Both must give the same records in the same order and the same counts. The same filter cases go through both
implementations here, on the live dataset and on the demo one. A drift (for example a region the source does not state being
treated as national in one place only) fails this test instead of showing up as two different numbers on screen.
"""

import itertools
import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from navigator.app.schemas import SearchFilters
from navigator.app.services import REGIONS, DataService, filtered

ROOT = Path(__file__).resolve().parent.parent
DATASETS = {
    "live": ROOT / "dist" / "data" / "opportunities.json",
    "demo": ROOT / "dist" / "data" / "demo-opportunities.json",
}
COMMUNITIES = ["First Nations", "Inuit", "Métis"]
DEADLINES = ["date", "annual_rule", "rolling", "local_administrator", "unspecified"]
LEVELS = ["high_school", "college", "undergraduate", "graduate", "vocational"]
FIELDS = ["business", "stem", "health", "arts", "trades"]
EXPENSES = ["tuition", "living", "travel", "books"]


class Rows:
    """The part of the repository the service reads."""

    def __init__(self, mode, rows):
        self.mode, self._rows = mode, rows

    def all(self):
        return self._rows


def node_major() -> int:
    try:
        out = subprocess.run(["node", "--version"], capture_output=True, text=True, timeout=20).stdout.strip()
        return int(out.lstrip("v").split(".")[0])
    except (OSError, ValueError, subprocess.SubprocessError):
        return 0


def case(filters, statistics=True):
    return {
        "name": json.dumps(filters, sort_keys=True, ensure_ascii=False),
        "filters": filters,
        "statistics": statistics,
    }


def build_cases(records):
    """Single-field cases for every control the site has, then every pair of controls from different groups."""
    providers = sorted({x["provider"] for x in records})[:12]
    axes = {
        "community": [{"communities": [c]} for c in COMMUNITIES],
        "province": [{"provinces": [p]} for p in sorted(REGIONS.values())]
        + [{"provinces": [p], "include_unknown": False} for p in ("British Columbia", "Ontario")],
        "type": [{"types": [t]} for t in ("Scholarship", "Program")],
        "scope": [{"scope": s} for s in ("national", "regional", "unspecified")],
        "amount": [{"amount_band": b} for b in ("listed", "high", "under5000", "unknown")],
        "deadline": [{"deadline_kind": k} for k in DEADLINES]
        + [{"deadline_kind": k, "include_unknown": False} for k in DEADLINES],
    }
    single = [
        {},
        {"communities": ["Inuit", "Métis"]},
        {"provinces": ["British Columbia", "Ontario"]},
        {"include_unknown": False},
        *[{"goals": [g]} for g in ("postsecondary", "training")],
        *[{"renewable": r} for r in ("yes", "no", "unknown")],
        *[{"renewable": r, "include_unknown": False} for r in ("yes", "no", "unknown")],
        *[{"education_levels": [v]} for v in LEVELS],
        *[{"education_levels": [v], "include_unknown": False} for v in LEVELS],
        *[{"fields_of_study": [v]} for v in FIELDS],
        *[{"fields_of_study": [v], "include_unknown": False} for v in FIELDS],
        *[{"study_modes": [v]} for v in ("full_time", "part_time")],
        *[{"study_modes": [v], "include_unknown": False} for v in ("full_time", "part_time")],
        *[{"expenses": [v]} for v in EXPENSES],
        *[{"providers": [p]} for p in providers],
        *[{"providers": providers[:2]}],
    ]
    cases = [case(f) for f in single]
    for values in axes.values():
        cases += [case(f) for f in values]
    for (_, left), (_, right) in itertools.combinations(axes.items(), 2):
        cases += [case({**a, **b}) for a, b in itertools.product(left, right)]
    # Sort orders are part of what the page shows. The keyword search is not part of Statistics (the site drops it).
    for sort in ("recommended", "amount", "alphabetical"):
        cases += [
            case({"sort": sort}),
            case({"sort": sort, "scope": "regional"}),
            case({"sort": sort, "amount_band": "listed"}),
        ]
    for query in ("metis", "bursary", "british columbia", "nutrien", "college", "zzz"):
        cases.append(case({"q": query}, statistics=False))
    unique = {c["name"]: c for c in cases}
    return list(unique.values())


def summarize(stats):
    highest = stats["amounts"]["highest_example_figure"]
    return {
        "total": stats["total"],
        "national": stats["national_count"],
        "regional": stats["regional_count"],
        "unspecified": stats["unspecified_region_count"],
        "regions": [[r["code"], r["regional_count"], r["national_count"], r["reach_count"]] for r in stats["regions"]],
        "by_type": stats["by_type"],
        "by_community": stats["by_community"],
        "listed": stats["amounts"]["listed"],
        "unknown": stats["amounts"]["unknown"],
        "highest": None if highest is None else float(highest),
        "bands": stats["amount_bands"],
        "by_deadline_kind": stats["by_deadline_kind"],
        "verified": stats["quality"]["verified_records"],
        "unknown_education": stats["quality"]["unknown_education_level"],
    }


class FilterParityTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which("node") and node_major() >= 20, "Node.js 20 or newer is not installed")
    def test_the_browser_and_the_server_filter_and_count_the_same_way(self):
        defaults = SearchFilters().model_dump()
        for mode, path in DATASETS.items():
            with self.subTest(mode=mode):
                data = json.loads(path.read_text(encoding="utf-8"))
                records = sorted(data["records"], key=lambda x: (x.get("display_order", 100), x["id"]))
                cases = build_cases(records)
                service = DataService(Rows(data["data_mode"], records))
                with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
                    request = Path(tmp) / "cases.json"
                    request.write_text(
                        json.dumps(
                            {"data_mode": data["data_mode"], "records": records, "defaults": defaults, "cases": cases},
                            ensure_ascii=False,
                        ),
                        encoding="utf-8",
                    )
                    done = subprocess.run(
                        ["node", str(ROOT / "tests" / "js" / "parity.mjs"), str(request)],
                        capture_output=True,
                        encoding="utf-8",
                        timeout=120,
                        cwd=ROOT,
                    )
                self.assertEqual(done.returncode, 0, done.stderr[-2000:])
                browser = json.loads(done.stdout)
                self.assertGreater(len(cases), 500)
                order_diffs, count_diffs = [], []
                for c in cases:
                    filters = SearchFilters(**c["filters"])
                    server_ids = [x["id"] for x in filtered(records, filters)]
                    if server_ids != browser["results"][c["name"]]:
                        order_diffs.append((c["name"], server_ids, browser["results"][c["name"]]))
                    if c["statistics"]:
                        server_stats = summarize(service.statistics(filters))
                        if server_stats != browser["statistics"][c["name"]]:
                            count_diffs.append((c["name"], server_stats, browser["statistics"][c["name"]]))
                self.assertFalse(
                    order_diffs, f"{len(order_diffs)} cases list different records; first: {order_diffs[:1]}"
                )
                self.assertFalse(count_diffs, f"{len(count_diffs)} cases count differently; first: {count_diffs[:1]}")


if __name__ == "__main__":
    unittest.main()
