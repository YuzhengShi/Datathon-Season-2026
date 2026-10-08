import json
import tempfile
import unittest
from pathlib import Path

from navigator.core.evidence import locate_quote
from navigator.core.timeutil import parse_as_of
from navigator.core.urlpolicy import AllowRule
from navigator.demo import content as demo_content
from navigator.ingestion import fetch_stage
from navigator.ingestion.adapters.base import Adapter
from navigator.ingestion.fetch_stage import FetchIndex, run_fetch_stage
from navigator.ingestion.fetcher import Fetcher, FetchPolicy, TransportError, parse_retry_after
from navigator.ingestion.snapshots import SnapshotIntegrityError, SnapshotStore
from navigator.ingestion.sources import SourceConfigError, load_sources
from navigator.ingestion.text import extract, extract_html, extract_pdf
from tests.support import FakeTransport, resp

ROOT = Path(__file__).resolve().parent.parent
RULES = [AllowRule(("www.example.ca",), ("/eng/",))]
URL = "https://www.example.ca/eng/a"
HTML_HDR = {"content_type": "text/html; charset=utf-8"}


class TextExtractionTests(unittest.TestCase):
    PAGE = (
        b"<html><head><title>T</title></head><body><nav><a href='/x'>Menu</a></nav><main>"
        b"<h1>Awards</h1><h2>Award One</h2><p>Open to M\xc3\xa9tis students. Apply <a href='/a/1?utm_source=z'>here</a>.</p>"
        b"<ul><li>Transcript</li></ul><h2>Award Two</h2><p>Open to Inuit students.</p>"
        b"<table><tr><th>Due</th><td>March 1, 2026</td></tr></table></main><footer>junk</footer></body></html>"
    )

    def test_html_is_split_by_award_section_with_headings(self):
        doc = extract_html(self.PAGE, "https://e.org/awards/")
        self.assertEqual(doc.status, "ok")
        self.assertNotIn("Menu", doc.text)
        self.assertNotIn("junk", doc.text)
        one = locate_quote(doc.text, "Open to Métis students")
        two = locate_quote(doc.text, "Open to Inuit students")
        self.assertEqual((one["heading"], two["heading"]), ("Award One", "Award Two"))
        self.assertIn("Apply here.", doc.text)  # inline markup does not split punctuation
        self.assertIn("Due | March 1, 2026", doc.text)
        self.assertEqual(doc.links[0].href, "https://e.org/a/1?utm_source=z")

    def test_pdf_pages_are_one_based_and_scans_are_flagged(self):
        pdf = extract_pdf(demo_content.render_guide_pdf())
        self.assertEqual((pdf.status, pdf.page_count), ("ok", 2))
        self.assertEqual(locate_quote(pdf.text, "Only one shared form")["pdf_page"], 2)
        self.assertEqual(locate_quote(pdf.text, "an official transcript")["pdf_page"], 1)
        scan = extract_pdf(demo_content.render_scanned_pdf())
        self.assertEqual(scan.status, "ocr_required")
        self.assertEqual(scan.text, "")
        self.assertIn("OCR is not performed", scan.note)

    def test_bad_inputs_are_reported_not_guessed(self):
        self.assertEqual(extract_pdf(b"%PDF-1.4 not really").status, "unreadable")
        self.assertEqual(extract(b"\x00\x01", "image/png").status, "unreadable")
        self.assertEqual(extract_html(b"<html><body></body></html>").status, "empty")

    def test_extraction_is_deterministic(self):
        self.assertEqual(extract_html(self.PAGE).text, extract_html(self.PAGE).text)


class SnapshotTests(unittest.TestCase):
    def test_content_addressed_and_never_overwritten(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = SnapshotStore(Path(tmp))
            first = store.save_raw(b"<p>v1</p>", "text/html")
            again = store.save_raw(b"<p>v1</p>", "text/html")
            changed = store.save_raw(b"<p>v2</p>", "text/html")
            self.assertTrue(first.created)
            self.assertFalse(again.created)
            self.assertNotEqual(first.raw_path, changed.raw_path)  # a changed page is a NEW file
            self.assertEqual(store.read_raw(first.raw_path), b"<p>v1</p>")
            self.assertTrue(first.raw_path.startswith("raw/") and "\\" not in first.raw_path)
            (Path(tmp) / first.raw_path).write_bytes(b"tampered")
            with self.assertRaises(SnapshotIntegrityError):
                store.save_raw(b"<p>v1</p>", "text/html")
            self.assertFalse(store.verify_raw(first.raw_path, first.raw_sha256))

    def test_no_temp_files_left_behind(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = SnapshotStore(Path(tmp))
            raw = store.save_raw(b"x", "text/html")
            store.save_text(raw.raw_sha256, "x", "navigator-text", "1.0.0")
            self.assertEqual([p for p in Path(tmp).rglob("*.tmp")], [])


def make_fetcher(script, **policy):
    sleeps, clock = [], [0.0]

    def sleeper(seconds):
        sleeps.append(round(seconds, 3))
        clock[0] += seconds

    transport = FakeTransport({"https://www.example.ca/robots.txt": resp(404), **script})
    kwargs = dict(retries=3, min_interval=1.0)
    kwargs.update(policy)
    fetcher = Fetcher(
        transport,
        FetchPolicy("TestBot/1.0", **kwargs),
        sleeper=sleeper,
        monotonic=lambda: clock[0],
        wall_clock=lambda: 1000.0,
    )
    return transport, fetcher, sleeps


class FetcherTests(unittest.TestCase):
    def test_429_honours_retry_after_then_succeeds(self):
        _, fetcher, sleeps = make_fetcher({URL: [resp(429, retry_after="5"), resp(200, b"ok", **HTML_HDR)]})
        out = fetcher.fetch(URL, RULES)
        self.assertEqual((out.outcome, out.attempts), ("ok", 2))
        self.assertIn(5.0, sleeps)

    def test_429_retries_are_bounded(self):
        _, fetcher, _ = make_fetcher({URL: [resp(429, retry_after="1")]}, retries=2)
        out = fetcher.fetch(URL, RULES)
        self.assertEqual((out.outcome, out.reason, out.attempts), ("failed", "http_429", 3))
        _, fetcher, sleeps = make_fetcher({URL: [resp(429, retry_after="99999")]})
        self.assertEqual(fetcher.fetch(URL, RULES).reason, "retry_after_too_long")
        self.assertLess(max(sleeps), 100)  # never sleeps for the absurd value

    def test_5xx_backs_off_exponentially_then_gives_up(self):
        _, fetcher, sleeps = make_fetcher({URL: [resp(503)]})
        out = fetcher.fetch(URL, RULES)
        self.assertEqual((out.outcome, out.reason, out.attempts), ("failed", "http_503", 4))
        self.assertEqual([s for s in sleeps if s != 1.0 or True][-3:], [1.0, 2.0, 4.0])

    def test_redirects_must_stay_inside_the_allowlist(self):
        for location, reason in [
            ("https://evil.example/eng/x", "url_outside_allowlist"),
            ("http://127.0.0.1/eng/x", "url_private_address"),
            ("https://www.example.ca/fra/x", "url_outside_allowlist"),
        ]:
            with self.subTest(location=location):
                _, fetcher, _ = make_fetcher({URL: [resp(302, location=location)]})
                out = fetcher.fetch(URL, RULES)
                self.assertEqual((out.outcome, out.reason), ("blocked", reason))
        _, fetcher, _ = make_fetcher(
            {URL: [resp(301, location="/eng/b")], "https://www.example.ca/eng/b": [resp(200, b"x", **HTML_HDR)]}
        )
        out = fetcher.fetch(URL, RULES)
        self.assertEqual((out.outcome, out.final_url), ("ok", "https://www.example.ca/eng/b"))

    def test_redirect_loops_and_chains_are_bounded(self):
        a, b = URL, "https://www.example.ca/eng/b"
        _, fetcher, _ = make_fetcher({a: [resp(302, location="/eng/b")], b: [resp(302, location="/eng/a")]})
        self.assertEqual(fetcher.fetch(a, RULES).reason, "redirect_loop")
        chain = {f"https://www.example.ca/eng/{i}": [resp(302, location=f"/eng/{i + 1}")] for i in range(20)}
        _, fetcher, _ = make_fetcher(chain, max_redirects=3)
        self.assertEqual(fetcher.fetch("https://www.example.ca/eng/0", RULES).reason, "too_many_redirects")

    def test_304_reuses_a_snapshot_only_when_one_exists(self):
        transport, fetcher, _ = make_fetcher({URL: [resp(304)]})
        out = fetcher.fetch(URL, RULES, etag='"v1"', have_snapshot=True)
        self.assertEqual(out.outcome, "not_modified")
        self.assertEqual(transport.calls[-1][1]["If-None-Match"], '"v1"')
        transport, fetcher, _ = make_fetcher({URL: [resp(200, b"fresh", **HTML_HDR)]})
        out = fetcher.fetch(URL, RULES, etag='"v1"', have_snapshot=False)  # no snapshot -> plain GET
        self.assertEqual(out.outcome, "ok")
        self.assertNotIn("If-None-Match", transport.calls[-1][1])
        _, fetcher, _ = make_fetcher({URL: [resp(304)]})
        self.assertEqual(fetcher.fetch(URL, RULES).reason, "unexpected_304")

    def test_size_media_and_access_limits(self):
        _, fetcher, _ = make_fetcher({URL: [TransportError("too_large")]})
        self.assertEqual(fetcher.fetch(URL, RULES).reason, "response_too_large")
        _, fetcher, _ = make_fetcher({URL: [resp(200, b"x" * 50, **HTML_HDR)]}, max_bytes=10)
        self.assertEqual(fetcher.fetch(URL, RULES).reason, "response_too_large")
        _, fetcher, _ = make_fetcher({URL: [resp(200, b"x", content_type="image/png")]})
        self.assertEqual(fetcher.fetch(URL, RULES).reason, "unsupported_media_type")
        _, fetcher, _ = make_fetcher({URL: [resp(403)]})
        out = fetcher.fetch(URL, RULES)
        self.assertEqual((out.reason, out.attempts), ("access_denied_403", 1))  # never retried or bypassed

    def test_robots_txt_is_respected(self):
        robots = resp(200, b"User-agent: *\nDisallow: /eng/", content_type="text/plain")
        transport, fetcher, _ = make_fetcher({"https://www.example.ca/robots.txt": robots, URL: [resp(200)]})
        out = fetcher.fetch(URL, RULES)
        self.assertEqual((out.outcome, out.reason, out.robots_status), ("blocked", "robots_disallowed", "present"))
        self.assertNotIn(URL, [c[0] for c in transport.calls])
        _, fetcher, _ = make_fetcher({"https://www.example.ca/robots.txt": resp(503), URL: [resp(200)]}, retries=0)
        self.assertEqual(fetcher.fetch(URL, RULES).reason, "robots_unavailable")  # RFC 9309: assume disallowed

    def test_spacing_and_identity(self):
        transport, fetcher, sleeps = make_fetcher(
            {URL: [resp(200, b"1", **HTML_HDR)], "https://www.example.ca/eng/c": [resp(200, b"2", **HTML_HDR)]}
        )
        fetcher.fetch(URL, RULES)
        fetcher.fetch("https://www.example.ca/eng/c", RULES)
        self.assertEqual(sleeps, [1.0, 1.0])  # min interval between requests to one host
        self.assertTrue(all(c[1]["User-Agent"] == "TestBot/1.0" for c in transport.calls))

    def test_retry_after_parser(self):
        self.assertEqual(parse_retry_after("7"), 7.0)
        self.assertIsNone(parse_retry_after("soon"))
        self.assertEqual(parse_retry_after("Thu, 01 Jan 1970 00:20:00 GMT", lambda: 1000.0), 200.0)


class FollowLinks(Adapter):
    def select_links(self, doc, url, source, depth):
        return [link.href for link in doc.links]


class FetchStageTests(unittest.TestCase):
    PAGES = {}

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.source = load_sources(ROOT / "sources.yaml")[0]
        base = self.source.url
        self.page2 = "https://www.sac-isc.gc.ca/eng/1351185180120/page2"
        self.pages = {
            base: b'<main><h1>Index</h1><p>entry</p><a href="/eng/1351185180120/page2">next</a>'
            b'<a href="https://evil.example/x">bad</a></main>',
            self.page2: b"<main><h1>Page 2</h1><p>more</p></main>",
        }
        self.calls, self.fail = [], set()

        class Net:
            def get(inner, url, headers, timeout, max_bytes):  # noqa: N805
                self.calls.append(url)
                if url.endswith("robots.txt"):
                    return resp(404)
                if url in self.fail:
                    raise TransportError("timeout")
                if "If-None-Match" in headers:
                    return resp(304)
                return resp(200, self.pages[url], etag='"v1"', **HTML_HDR)

        self.net = Net()

    def tearDown(self):
        self.tmp.cleanup()

    def run_stage(self, **kw):
        fetcher = Fetcher(self.net, FetchPolicy("T/1", retries=0, min_interval=0), sleeper=lambda s: None)
        index = FetchIndex(self.root / "discovery" / "fetch_index.json")
        result = run_fetch_stage(
            [self.source],
            fetcher,
            SnapshotStore(self.root),
            index,
            {"isc_index": FollowLinks()},
            run_id="r",
            now=parse_as_of("2026-10-07"),
            audit_path=self.root / "discovery" / "fetch_audit.jsonl",
            **kw,
        )
        return result, result.per_source[self.source.source_id]

    def test_failure_then_resume_only_refetches_what_is_missing(self):
        self.fail.add(self.page2)
        _, stats = self.run_stage()
        self.assertEqual(
            (stats["succeeded"], stats["failed"], stats["blocked"]), (1, 1, 1)
        )  # out-of-scope link blocked
        self.calls.clear()
        self.fail.clear()
        result, stats = self.run_stage(resume=True)
        fetched = [c for c in self.calls if not c.endswith("robots.txt")]
        self.assertEqual(fetched, [self.page2])  # page 1 was NOT downloaded again
        self.assertEqual(len(result.snapshots[self.source.source_id]), 2)
        self.assertEqual(stats["skipped"], 1)

    def test_refresh_uses_conditional_requests_and_reuses_snapshots(self):
        self.run_stage()
        _, stats = self.run_stage(refresh=True)
        self.assertEqual((stats["not_modified"], stats["succeeded"]), (2, 0))

    def test_failed_refresh_never_replaces_a_good_snapshot(self):
        self.run_stage()
        index = FetchIndex(self.root / "discovery" / "fetch_index.json")
        before = {k: dict(v) for k, v in index.entries.items()}
        self.fail.update({self.source.url, self.page2})
        _, stats = self.run_stage(refresh=True)
        after = FetchIndex(self.root / "discovery" / "fetch_index.json")
        self.assertEqual(
            {k: v["raw_sha256"] for k, v in after.entries.items()}, {k: v["raw_sha256"] for k, v in before.items()}
        )
        self.assertEqual(len(after.failures), 2)
        self.assertTrue(
            all(SnapshotStore(self.root).verify_raw(e["raw_path"], e["raw_sha256"]) for e in after.entries.values())
        )

    def test_page_bound(self):
        result, _ = self.run_stage(max_pages=1)
        self.assertEqual(result.pages_fetched, 1)
        self.assertTrue(result.unvisited)

    def test_depth_bound(self):
        _, stats = self.run_stage(max_depth=0)
        self.assertEqual(stats["attempted"], 1)  # links are not followed at depth 0

    def test_extractor_version_change_only_reruns_extraction(self):
        self.run_stage()
        self.calls.clear()
        original = fetch_stage.EXTRACTOR_VERSION
        fetch_stage.EXTRACTOR_VERSION = "9.9.9"
        try:
            self.run_stage(resume=True)
        finally:
            fetch_stage.EXTRACTOR_VERSION = original
        self.assertEqual([c for c in self.calls if not c.endswith("robots.txt")], [])
        index = FetchIndex(self.root / "discovery" / "fetch_index.json")
        self.assertTrue(all(e["extractor_version"] == "9.9.9" for e in index.entries.values()))

    def test_audit_trail_records_every_attempt_without_bodies(self):
        self.fail.add(self.page2)
        self.run_stage()
        rows = [json.loads(line) for line in (self.root / "discovery" / "fetch_audit.jsonl").read_text().splitlines()]
        self.assertEqual({r["outcome"] for r in rows}, {"ok", "failed", "blocked"})
        self.assertTrue(all("body" not in r and r["run_id"] == "r" for r in rows))


class SourceConfigTests(unittest.TestCase):
    def test_shipped_sources_are_valid_and_scoped(self):
        sources = load_sources(ROOT / "sources.yaml")
        self.assertEqual(len(sources), 10)
        self.assertEqual(len({s.source_id for s in sources}), 10)
        for s in sources:
            self.assertTrue(s.url.startswith("https://"), s.source_id)
            self.assertEqual(s.access_status, "unreviewed")  # terms have not been reviewed by a person
        self.assertIn("wbdisable=true", sources[0].url)  # semantic query parameter is preserved

    def test_bad_config_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "s.yaml"
            path.write_text(
                "sources:\n  - {source_id: a, name: A, url: 'http://127.0.0.1/x', provider: {id: p, name: P},"
                " role: r, parser: x, allowed_domains: ['127.0.0.1'], allowed_paths: ['/']}\n",
                encoding="utf-8",
            )
            with self.assertRaises(SourceConfigError):
                load_sources(path)
            with self.assertRaises(SourceConfigError):
                load_sources(Path(tmp) / "missing.yaml")


if __name__ == "__main__":
    unittest.main()
