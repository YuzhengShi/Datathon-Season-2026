import dataclasses
import tempfile
import unittest
from pathlib import Path

from navigator.core.timeutil import parse_as_of
from navigator.ingestion.adapters.base import Adapter
from navigator.ingestion.fetch_stage import FetchIndex, run_fetch_stage
from navigator.ingestion.fetcher import Fetcher, FetchPolicy
from navigator.ingestion.snapshots import SnapshotStore
from navigator.ingestion.sources import load_sources
from tests.support import FakeTransport, resp

ROOT = Path(__file__).resolve().parent.parent
HTML = {"content_type": "text/html"}


class FollowEveryLink(Adapter):
    def select_links(self, doc, url, source, depth):
        return [link.href for link in doc.links]


class PerSourceBudgetTests(unittest.TestCase):
    def test_one_large_index_cannot_starve_the_other_sources(self):
        # the ISC index (hundreds of links) and Indspire apply-now, without the production per-source budgets
        big, small = (dataclasses.replace(s, max_pages=None) for s in load_sources(ROOT / "sources.yaml")[:2])
        links = "".join(f'<a href="/eng/1351185180120/detail-{i}">row {i}</a>' for i in range(30))
        script = {
            "https://www.sac-isc.gc.ca/robots.txt": resp(404),
            "https://indspire.ca/robots.txt": resp(404),
            big.url: resp(200, f"<main><h1>Index</h1>{links}</main>".encode(), **HTML),
            small.url: resp(200, b"<main><h1>Apply</h1><p>Policy text.</p></main>", **HTML),
        }
        for i in range(30):
            script[f"https://www.sac-isc.gc.ca/eng/1351185180120/detail-{i}"] = resp(
                200, b"<main><p>detail</p></main>", **HTML
            )
        fetcher = Fetcher(FakeTransport(script), FetchPolicy("T/1", retries=0, min_interval=0), sleeper=lambda s: None)
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            root = Path(tmp)
            result = run_fetch_stage(
                [big, small],
                fetcher,
                SnapshotStore(root),
                FetchIndex(root / "index.json"),
                {"isc_index": FollowEveryLink()},
                run_id="r",
                now=parse_as_of("2026-10-07"),
                audit_path=root / "audit.jsonl",
                max_pages=6,
            )
        self.assertEqual(result.per_source[big.source_id]["succeeded"], 3)  # its fair share: 6 // 2
        self.assertEqual(
            result.per_source[small.source_id]["succeeded"], 1
        )  # the second source still got its start page
        self.assertEqual(result.pages_fetched, 4)
        self.assertTrue(result.unvisited)

    def fetch_one(self, big, pages, max_pages):
        script = {"https://www.sac-isc.gc.ca/robots.txt": resp(404)}
        script.update({url: resp(200, body, **HTML) for url, body in pages.items()})
        fetcher = Fetcher(FakeTransport(script), FetchPolicy("T/1", retries=0, min_interval=0), sleeper=lambda s: None)
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            root = Path(tmp)
            return run_fetch_stage(
                [big],
                fetcher,
                SnapshotStore(root),
                FetchIndex(root / "index.json"),
                {"isc_index": FollowEveryLink()},
                run_id="r",
                now=parse_as_of("2026-10-07"),
                audit_path=root / "audit.jsonl",
                max_pages=max_pages,
            )

    def test_a_source_can_set_its_own_budget(self):
        big = dataclasses.replace(load_sources(ROOT / "sources.yaml")[0], max_pages=2)
        links = "".join(f'<a href="/eng/9/{i}">row {i}</a>' for i in range(5))
        pages = {big.url: f"<main><h1>Index</h1>{links}</main>".encode()}
        pages.update({f"https://www.sac-isc.gc.ca/eng/9/{i}": b"<main><p>x</p></main>" for i in range(5)})
        result = self.fetch_one(big, pages, max_pages=50)
        self.assertEqual(result.per_source[big.source_id]["succeeded"], 2)  # its own 2, not the global 50

    def test_links_refused_by_the_url_policy_do_not_use_up_the_budget(self):
        big = dataclasses.replace(load_sources(ROOT / "sources.yaml")[0], max_pages=4)
        social = "".join(f'<a href="https://www.facebook.com/page{i}">social {i}</a>' for i in range(6))
        inside = "".join(f'<a href="/eng/9/{i}">row {i}</a>' for i in range(3))
        pages = {big.url: f"<main><h1>Index</h1>{social}{inside}</main>".encode()}
        pages.update({f"https://www.sac-isc.gc.ca/eng/9/{i}": b"<main><p>x</p></main>" for i in range(3)})
        result = self.fetch_one(big, pages, max_pages=50)
        stats = result.per_source[big.source_id]
        self.assertEqual(stats["succeeded"], 4)  # the start page and all three in-scope links
        self.assertEqual(stats["blocked"], 6)  # the off-site links were refused, and were free


if __name__ == "__main__":
    unittest.main()
