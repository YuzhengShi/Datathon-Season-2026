import shutil
import tempfile
import unittest
import weakref
from pathlib import Path

from navigator.core.timeutil import parse_as_of
from navigator.ingestion.adapters import registry
from navigator.ingestion.adapters.base import ParseContext
from navigator.ingestion.adapters.curated import curated_record
from navigator.ingestion.adapters.isc_index import parse_index_table
from navigator.ingestion.builder import SnapshotView
from navigator.ingestion.snapshots import SnapshotStore
from navigator.ingestion.sources import SourceConfig, load_sources
from navigator.ingestion.text import EXTRACTOR_NAME, EXTRACTOR_VERSION, extract
from navigator.ingestion.validation import ValidationContext, validate_record
from navigator.matching.engine import MatchOptions, evaluate_record

ROOT = Path(__file__).resolve().parent.parent
NOW = parse_as_of("2026-10-07")
STAMP = "2026-10-07T12:00:00Z"
ISC_HTML = (ROOT / "tests" / "fixtures" / "isc_index_sample.html").read_bytes()

UBC_LIKE = """<!doctype html><html><head><title>Awards (synthetic fixture)</title></head><body><main>
<h1>Indigenous awards (synthetic structural fixture)</h1>
<h2>Awards</h2>
<h3>Sample Entrance Award (1234)</h3>
<p>Open to Indigenous students entering a first-year program. Applicants must be Canadian citizens or permanent residents.</p>
<p>The application deadline is March 15, 2027.</p>
<p>The award is valued at $2,000.</p>
<h3>Sample Graduate Fellowship</h3>
<p>Eligible students are enrolled in a graduate program and have a minimum average of 80 percent.</p>
<h3>Sample Plain Note</h3>
<p>See the faculty office.</p>
<h3>Sample Plain Note</h3>
<p>Another unrelated note.</p>
<h3>Heading without body</h3>
<h2>On this page</h2>
</main></body></html>""".encode()

LISTING = b"""<html><body><main><h1>Funding (synthetic)</h1><a href="/awards/sample-one">Sample One</a>
<a href="/awards/sample-two">Sample Two</a><a href="/awards/sample-one#top">Sample One again</a></main></body></html>"""
DETAIL = b"""<html><body><main><h1>Sample One Award</h1><p>Donor: The Sample Family Foundation</p>
<p>Applicants must self-identify as Indigenous and be enrolled in a post-secondary program.</p>
<p>Applications close on November 1, 2026.</p></main></body></html>"""


def source(parser: str, url: str = "https://example.org/awards/", provider=("ubc", "Sample University")) -> SourceConfig:
    return SourceConfig("src_" + parser, "Sample", url, provider[0], provider[1], "award_listing", parser, "en",
                        ("example.org",), ("/",), "unreviewed")


class Env:
    def __init__(self):
        self.root = Path(tempfile.mkdtemp(prefix="adapter-env-"))
        weakref.finalize(self, shutil.rmtree, str(self.root), True)
        self.store = SnapshotStore(self.root)

    def snap(self, key, src: SourceConfig, url: str, html: bytes) -> SnapshotView:
        raw = self.store.save_raw(html, "text/html")
        doc = extract(html, "text/html", url)
        stored = self.store.save_text(raw.raw_sha256, doc.text, EXTRACTOR_NAME, EXTRACTOR_VERSION)
        return SnapshotView(key, src.source_id, url, "text/html", raw.snapshot_id, raw.raw_sha256, raw.raw_path,
                            stored.text_sha256, stored.text_path, STAMP, doc.text, src.role)

    def ctx(self, **kw) -> ParseContext:
        return ParseContext(now=NOW, read_raw=lambda s: self.store.read_raw(s.raw_path), **kw)

    def validate(self, record):
        return [i for i in validate_record(record, ValidationContext(artifact_root=self.root, expected_mode="live", now=NOW)) if i.is_error]


class IscIndexTests(unittest.TestCase):
    def test_columns_stay_aligned_when_cells_are_empty(self):
        parsed = parse_index_table(ISC_HTML, "https://www.sac-isc.gc.ca/eng/1351185180120/1351685455328")
        by_name = {(e["name"], e["institution"]): e for e in parsed["entries"]}
        self.assertEqual(len(parsed["entries"]), 5)
        self.assertEqual(by_name[("Sample Award Without Link", "")]["province"], "National")
        self.assertEqual(by_name[("Another Sample Award", "Sample University")]["province"], "")
        self.assertEqual(by_name[("Sample Fund", "All")]["indigenous_group"], "")

    def test_duplicate_names_are_kept_distinct_and_marked_unverified(self):
        entries = parse_index_table(ISC_HTML, "https://www.sac-isc.gc.ca/eng/1351185180120/1351685455328")["entries"]
        same_name = [e for e in entries if e["name"] == "Sample Bursary Program"]
        self.assertEqual(len(same_name), 2)
        self.assertEqual(len({e["entry_id"] for e in entries}), 5)  # never merged by title
        self.assertTrue(all(e["status"] == "discovery_only_not_verified" for e in entries))
        self.assertTrue(same_name[0]["detail_url"].endswith("/detail-1"))
        self.assertIsNone(next(e for e in entries if e["name"] == "Sample Fund")["detail_url"])

    def test_coverage_and_pagination_facts(self):
        stats = parse_index_table(ISC_HTML, "https://x.example/eng/")["stats"]
        self.assertEqual((stats["declared_count"], stats["entries_observed"], stats["coverage"]), (5, 5, 1.0))
        self.assertTrue(stats["pagination_complete"])
        self.assertTrue(stats["update_in_progress_notice"])
        short = ISC_HTML.replace(b"There are 5 bursaries", b"There are 538 bursaries")
        stats = parse_index_table(short, "https://x.example/eng/")["stats"]
        self.assertFalse(stats["pagination_complete"])  # 5 of 538 is not a complete crawl
        self.assertAlmostEqual(stats["coverage"], 5 / 538, places=3)
        paged = ISC_HTML.replace(b"</main>", b'<a href="?page=2">Next</a></main>')
        self.assertFalse(parse_index_table(paged, "https://x.example/eng/")["stats"]["pagination_complete"])

    def test_unexpected_rows_and_missing_tables_are_pending_not_guessed(self):
        bad = ISC_HTML.replace(b"<td>Sample Fund</td><td>Alberta</td>", b"<td>Sample Fund</td>")
        parsed = parse_index_table(bad, "https://x.example/eng/")
        self.assertEqual(len(parsed["entries"]), 4)
        self.assertIn("unexpected column count", parsed["pending"][0]["reason"])
        self.assertEqual(parse_index_table(b"<html><body><p>nothing</p></body></html>", "https://x.example/")["entries"], [])

    def test_adapter_never_emits_opportunity_records(self):
        env = Env()
        src = load_sources(ROOT / "sources.yaml")[0]
        snap = env.snap("a", src, src.url, ISC_HTML)
        result = registry()["isc_index"].parse([snap], src, env.ctx())
        self.assertEqual((result.candidates, len(result.discovery)), ([], 5))
        self.assertEqual(result.stats["declared_count"], 5)


class SectionedAdapterTests(unittest.TestCase):
    def setUp(self):
        self.env = Env()
        self.src = source("ubc_sections")
        self.snap = self.env.snap("p", self.src, self.src.url, UBC_LIKE)
        self.result = registry()["ubc_sections"].parse([self.snap], self.src, self.env.ctx())

    def test_one_record_per_award_section_with_stable_ids(self):
        ids = sorted(r["id"] for r in self.result.candidates)
        self.assertEqual(ids, ["ubc:1234", "ubc:sample_graduate_fellowship", "ubc:sample_plain_note",
                               "ubc:sample_plain_note_2"])  # award number kept; duplicate titles kept apart
        self.assertTrue(any("without body" in p["reason"] for p in self.result.pending))

    def test_records_validate_and_carry_real_evidence(self):
        for record in self.result.candidates:
            self.assertEqual(self.env.validate(record), [], record["id"])
        entrance = next(r for r in self.result.candidates if r["id"] == "ubc:1234")
        self.assertEqual(entrance["title"], "Sample Entrance Award")
        deadline = entrance["cycles"][0]["deadlines"][0]
        self.assertEqual((deadline["kind"], deadline["date"], deadline.get("timezone")), ("date", "2027-03-15", None))
        self.assertTrue(entrance["cycles"][0]["eligibility"]["unstructured"])

    def test_nothing_is_guessed(self):
        entrance = next(r for r in self.result.candidates if r["id"] == "ubc:1234")
        cycle = entrance["cycles"][0]
        self.assertEqual((cycle["cycle_key"], cycle["amount"]["kind"], cycle["eligibility"]["mandatory"]), ("unspecified", "unspecified", []))
        self.assertEqual(entrance["application"]["route_type"], "unknown")
        self.assertEqual(entrance["review_status"], "machine_checked")  # parser + validation, not a person

    def test_unstructured_conditions_can_never_produce_a_fit(self):
        entrance = next(r for r in self.result.candidates if r["id"] == "ubc:1234")
        item = evaluate_record(entrance, {"indigenous_identity": ["metis"]}, MatchOptions(as_of=NOW, include_closed=True))
        self.assertEqual(item["match_status"], "needs_provider_confirmation")

    def test_sections_with_nothing_verifiable_stay_draft(self):
        plain = next(r for r in self.result.candidates if r["id"] == "ubc:sample_plain_note")
        self.assertEqual((plain["review_status"], plain["publication_status"]), ("pending", "draft"))
        self.assertEqual(self.env.validate(plain), [])

    def test_unknown_page_structure_goes_to_pending(self):
        flat = self.env.snap("f", self.src, self.src.url + "flat", b"<html><body><main><p>just text</p></main></body></html>")
        result = registry()["ubc_sections"].parse([flat], self.src, self.env.ctx())
        self.assertEqual(result.candidates, [])
        self.assertIn("nothing guessed", result.pending[0]["reason"])


class ListingDetailTests(unittest.TestCase):
    def test_detail_pages_become_records_and_donors_are_not_administrators(self):
        env = Env()
        src = source("indspire_funding", "https://example.org/", ("indspire", "Indspire"))
        listing = env.snap("l", src, "https://example.org/", LISTING)
        detail = env.snap("d", src, "https://example.org/awards/sample-one", DETAIL)
        adapter = registry()["indspire_funding"]
        links = adapter.select_links(extract(LISTING, "text/html", "https://example.org/"), "https://example.org/", src, 0)
        self.assertEqual(links, ["https://example.org/awards/sample-one", "https://example.org/awards/sample-two"])
        self.assertEqual(adapter.select_links(extract(LISTING, "text/html", "https://example.org/"), "https://example.org/", src, 1), [])
        result = adapter.parse([listing, detail], src, env.ctx())
        record = result.candidates[0]
        self.assertEqual((record["id"], record["provider"]["id"]), ("indspire:sample_one", "indspire"))
        self.assertEqual(record["provider"]["donor_name"], "The Sample Family Foundation")
        self.assertEqual(env.validate(record), [])
        self.assertEqual(record["cycles"][0]["deadlines"][0]["date"], "2026-11-01")

    def test_listing_alone_infers_nothing(self):
        env = Env()
        src = source("indspire_funding", "https://example.org/", ("indspire", "Indspire"))
        result = registry()["indspire_funding"].parse([env.snap("l", src, "https://example.org/", LISTING)], src, env.ctx())
        self.assertEqual(result.candidates, [])
        self.assertIn("nothing inferred", result.pending[0]["reason"])


class CuratedTests(unittest.TestCase):
    PAGE = (b"<html><body><main><h1>Funding channel (synthetic)</h1>"
            b"<p>Eligible students apply through their community education administrator.</p>"
            b"<p>Contact your local education office for deadlines.</p></main></body></html>")

    def entry(self, quote="Eligible students apply through their community education administrator."):
        return {"key": "sample-channel", "title": "Sample Channel", "opportunity_type": "funding_channel",
                "summary": "Funding administered locally.", "official_url": "https://example.org/channel",
                "application": {"route_type": "contact_administrator", "contact_url": "https://example.org/contact",
                                "quotes": [quote]},
                "cycles": [{"cycle_key": "unspecified", "label_raw": "not stated",
                            "deadlines": [{"kind": "local_administrator", "raw_text": "set locally",
                                           "quotes": ["Contact your local education office for deadlines."]}],
                            "eligibility": {"mandatory": [{"type": "unknown", "reason": "Administrator decides", "quotes": [quote]}]}}]}

    def test_curated_entry_validates_and_never_claims_human_review(self):
        env = Env()
        src = source("curated_channel", "https://example.org/channel", ("isc", "Indigenous Services Canada"))
        snap = env.snap("c", src, src.url, self.PAGE)
        record = curated_record(self.entry(), [snap], src, STAMP)
        self.assertEqual(env.validate(record), [])
        self.assertEqual((record["extraction_method"], record["review_status"]), ("curated", "machine_checked"))
        item = evaluate_record(record, {}, MatchOptions(as_of=NOW))
        self.assertEqual(item["match_status"], "needs_provider_confirmation")
        self.assertEqual(item["application_route"]["contact_url"], "https://example.org/contact")

    def test_forged_quotes_are_rejected_before_they_become_candidates(self):
        env = Env()
        src = source("curated_channel", "https://example.org/channel", ("isc", "Indigenous Services Canada"))
        snap = env.snap("c", src, src.url, self.PAGE)
        result = registry()["curated_channel"].parse([snap], src, env.ctx(curated={src.source_id: {"records": [self.entry("A sentence the page never says.")]}}))
        self.assertEqual(result.candidates, [])
        self.assertIn("quote not found", result.pending[0]["reason"])

    def test_missing_curated_file_is_reported_not_invented(self):
        env = Env()
        src = source("curated_channel", "https://example.org/channel")
        result = registry()["curated_channel"].parse([env.snap("c", src, src.url, self.PAGE)], src, env.ctx())
        self.assertEqual(result.candidates, [])
        self.assertIn("no curated mapping", result.pending[0]["reason"])

    def test_human_review_requires_a_review_record(self):
        env = Env()
        src = source("curated_channel", "https://example.org/channel")
        snap = env.snap("c", src, src.url, self.PAGE)
        entry = self.entry()
        entry["review"] = {"reviewer": "A. Reviewer", "reviewed_at": STAMP}
        self.assertEqual(curated_record(entry, [snap], src, STAMP)["review_status"], "human_reviewed")


class CuratedConflictTests(unittest.TestCase):
    PAGE = (b"<html><body><main><h1>Sample award (synthetic)</h1>"
            b"<p>The current page says applications close on March 1, 2027.</p>"
            b"<p>The yearly guide says applications close on March 15, 2027.</p>"
            b"<p>Funding is paid to the education authority once it files its annual plan.</p></main></body></html>")

    def entry(self, **extra):
        body = {"key": "sample-award", "title": "Sample Award", "summary": "Synthetic.", "official_url": "https://example.org/award",
                "cycles": [{"cycle_key": "unspecified", "label_raw": "not stated",
                            "deadlines": [{"kind": "date", "date": "2027-03-01", "raw_text": "March 1, 2027",
                                           "quotes": ["The current page says applications close on March 1, 2027."]}],
                            "eligibility": {"mandatory": [], "funder_conditions": [
                                {"text": "The education authority files an annual plan.",
                                 "quotes": ["Funding is paid to the education authority once it files its annual plan."]}]}}]}
        body.update(extra)
        return body

    def build(self, entry):
        env = Env()
        src = source("curated_awards", "https://example.org/award", ("example", "Example Provider"))
        snap = env.snap("c", src, src.url, self.PAGE)
        return env, curated_record(entry, [snap], src, STAMP)

    def test_funder_conditions_are_carried_with_evidence(self):
        env, record = self.build(self.entry())
        self.assertEqual(env.validate(record), [])
        condition = record["cycles"][0]["eligibility"]["funder_conditions"][0]
        self.assertEqual(len(condition["evidence_ids"]), 1)
        self.assertEqual(record["cycles"][0]["eligibility"]["mandatory"], [])

    def test_conflicting_statements_keep_both_and_force_pending_even_with_a_review_block(self):
        conflict = {"field_path": "/cycles/unspecified/deadlines/0", "summary": "Page and guide give different closing dates.",
                    "quotes": ["The current page says applications close on March 1, 2027.",
                               "The yearly guide says applications close on March 15, 2027."]}
        env, record = self.build(self.entry(conflicts=[conflict], review={"reviewer": "A. Reviewer", "reviewed_at": STAMP}))
        self.assertEqual(env.validate(record), [])
        self.assertEqual((record["review_status"], record["publication_status"]), ("pending", "draft"))
        self.assertNotIn("review", record)  # an unresolved conflict cannot be "human reviewed"
        self.assertEqual(len(record["conflicts"][0]["evidence_ids"]), 2)
        quotes = {e["quote"] for e in record["evidence"] if e["field_path"] == "/conflicts/0"}
        self.assertEqual(len(quotes), 2)


class PolicyTests(unittest.TestCase):
    def test_policy_pages_capture_facts_but_emit_no_records(self):
        env = Env()
        src = source("indspire_policy", "https://example.org/apply-now/", ("indspire", "Indspire"))
        page = b"<html><body><main><h1>Apply now</h1><h2>How it works</h2><p>Submit one application form for many awards. The deadline is stated on each award.</p><p>Unrelated.</p></main></body></html>"
        result = registry()["indspire_policy"].parse([env.snap("p", src, src.url, page)], src, env.ctx())
        self.assertEqual(result.candidates, [])
        self.assertEqual(result.stats["count"], 1)
        self.assertEqual(result.stats["policy_facts"][0]["heading"], "How it works")
        self.assertIn("not inferred", result.pending[0]["reason"])


if __name__ == "__main__":
    unittest.main()
