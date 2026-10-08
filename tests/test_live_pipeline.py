"""The live pipeline against a scripted network of SYNTHETIC pages (structure modelled on observed
layouts; no real award data). Real-site behaviour is not claimed here: see docs/HANDOFF.md."""

import re
import dataclasses
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from navigator.config import derive_runtime
from navigator.ingestion.adapters import registry as real_registry
from navigator.ingestion.adapters.base import Adapter, AdapterResult
from navigator.ingestion.builder import finalize
from navigator.ingestion.fetcher import HttpResponse, TransportError
from navigator.ingestion.fsutil import read_json
from navigator.ingestion.memory_repo import MemoryRepository
from navigator.ingestion.sources import load_sources
from navigator.services import live
from tests.support import AS_OF
from tests.test_adapters import DETAIL, ISC_HTML, LISTING, UBC_LIKE

ROOT = Path(__file__).resolve().parent.parent
SOURCES = {s.source_id: dataclasses.replace(s, max_pages=None) for s in load_sources(ROOT / "sources.yaml")}
SIMPLE = b"<html><body><main><h1>Channel page (synthetic)</h1><p>Contact the local education office.</p></main></body></html>"
POLICY = b"<html><body><main><h1>Apply now</h1><p>Submit one application form. The deadline is on each award.</p></main></body></html>"


class Router:
    """Serves synthetic pages by URL; anything else is a 404. Records every request."""

    def __init__(self, extra=None, down=()):
        self.pages = {
            SOURCES["isc_bursaries_index"].url: ISC_HTML,
            SOURCES["indspire_apply_now"].url: POLICY,
            "https://indspirefunding.ca/": LISTING.replace(b'href="/awards/', b'href="/awards/'),
            "https://indspirefunding.ca/awards/sample-one": DETAIL,
            SOURCES["ubc_award_descriptions"].url: UBC_LIKE,
            **{
                SOURCES[k].url: SIMPLE
                for k in (
                    "isc_psssp",
                    "isc_inuit_strategy",
                    "isc_metis_strategy",
                    "ubc_award_context",
                    "sfu_indigenous_awards",
                    "mnbc_steps",
                )
            },
            **(extra or {}),
        }
        self.down, self.calls = set(down), []

    def get(self, url, headers, timeout, max_bytes):
        self.calls.append(url)
        host = url.split("/")[2]
        if host in self.down:
            raise TransportError("connect")
        if url.endswith("/robots.txt"):
            return HttpResponse(404, {}, b"", url)
        body = self.pages.get(url)
        if body is None:
            return HttpResponse(404, {"content-type": "text/html"}, b"not found", url)
        return HttpResponse(200, {"content-type": "text/html; charset=utf-8", "etag": '"v1"'}, body, url)

    def fetched(self):
        return [c for c in self.calls if not c.endswith("/robots.txt")]


class LivePipelineTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.data = Path(self.tmp.name)
        # production sources.yaml gives some sources their own page budget; these tests exercise the generic fair share
        stripped = re.sub(r"(?m)^    max_pages:.*\n", "", (ROOT / "sources.yaml").read_text(encoding="utf-8"))
        (self.data / "sources.test.yaml").write_text(stripped, encoding="utf-8")
        self.rt = derive_runtime(
            {
                "DATA_DIR": str(self.data),
                "SOURCE_CONFIG": str(self.data / "sources.test.yaml"),
                "FETCH_RETRIES": "0",
                "FETCH_MIN_INTERVAL_SECONDS": "0",
            },
            "live",
        )
        self.repo = MemoryRepository()

    def tearDown(self):
        self.tmp.cleanup()

    def run_pipeline(self, router, **kw):
        options = dict(now=AS_OF, limit=30, max_pages=50, resume=False, refresh=False)
        options.update(kw)
        return live.run_live_pipeline(self.repo, self.rt, fetcher=live.build_fetcher(self.rt, router), **options)

    def test_partial_run_reports_the_shortfall_instead_of_pretending(self):
        result = self.run_pipeline(Router())
        self.assertEqual((result["exit_code"], result["status"], result["data_mode"]), (3, "partial", "live"))
        self.assertEqual(
            result["real_opportunities"], 3
        )  # 2 UBC-style sections + 1 detail page (drafts are not counted)
        self.assertEqual(result["target"], {"minimum": 20, "shortfall": 17})
        report = read_json(self.data / "reports" / "freshness.json")
        self.assertEqual((report["data_mode"], report["target"]["shortfall"]), ("live", 17))
        self.assertFalse(report["opportunities"]["is_demo_dataset"])
        manifest = read_json(self.data / "runs" / f"{result['run_id']}.json")
        self.assertEqual(manifest["status"], "partial")
        self.assertTrue(any("terms NOT reviewed" in n for n in manifest["notes"]))

    def test_directory_entries_are_discovery_data_not_awards(self):
        self.run_pipeline(Router())
        entries = [
            json.loads(line)
            for line in (self.data / "discovery" / "isc_bursaries_index.jsonl").read_text().splitlines()
        ]
        self.assertEqual(len(entries), 5)
        self.assertTrue(all(e["status"] == "discovery_only_not_verified" for e in entries))
        summary = read_json(self.data / "discovery" / "isc_bursaries_index.summary.json")
        self.assertEqual(
            (summary["declared_count"], summary["coverage"], summary["pagination_complete"]), (5, 1.0, True)
        )
        stored = self.repo.list_records(published_only=False, is_demo=False)
        self.assertFalse(
            any(r["id"].startswith("isc:") for r in stored)
        )  # nothing from the index became an opportunity

    def test_only_real_records_reach_live_outputs(self):
        self.run_pipeline(Router())
        self.assertEqual(self.repo.list_records(published_only=False, is_demo=True), [])
        exported = [json.loads(line) for line in (self.data / "awards.jsonl").read_text(encoding="utf-8").splitlines()]
        self.assertEqual(len(exported), 3)
        self.assertTrue(
            all(
                not r["is_demo"] and r["review_status"] == "machine_checked" and r["last_verified_at"] for r in exported
            )
        )
        self.assertFalse((self.data / "demo").exists())
        self.assertEqual({r["provider"]["id"] for r in exported}, {"ubc", "indspire"})
        indspire = next(r for r in exported if r["provider"]["id"] == "indspire")
        self.assertEqual(indspire["provider"]["donor_name"], "The Sample Family Foundation")

    def test_total_outage_is_not_success_and_creates_no_data(self):
        router = Router(
            down={
                "www.sac-isc.gc.ca",
                "indspire.ca",
                "indspirefunding.ca",
                "students.ubc.ca",
                "www.sfu.ca",
                "www.mnbc.ca",
            }
        )
        result = self.run_pipeline(router)
        self.assertEqual((result["exit_code"], result["real_opportunities"], result["status"]), (3, 0, "partial"))
        self.assertEqual(result["sources"]["succeeded"], 0)
        self.assertFalse((self.data / "awards.jsonl").exists())  # no real data: no canonical export
        self.assertEqual(self.repo.records, {})
        report = read_json(self.data / "reports" / "freshness.json")
        self.assertEqual(report["target"]["shortfall"], 20)
        self.assertTrue(report["source_failures"])
        self.assertEqual(report["opportunities"]["total"], 0)

    def test_one_failing_source_does_not_stop_the_others(self):
        result = self.run_pipeline(Router(down={"www.mnbc.ca"}))
        statuses = {d["source_id"]: d["status"] for d in result["sources"]["details"]}
        self.assertEqual(statuses["mnbc_steps"], "failed")
        self.assertEqual(statuses["ubc_award_descriptions"], "ok")
        self.assertEqual(result["real_opportunities"], 3)

    def test_resume_does_not_download_finished_pages_again(self):
        first = Router()
        self.run_pipeline(first)
        second = Router()
        result = self.run_pipeline(second, resume=True, now=AS_OF)
        self.assertFalse(
            set(second.fetched()) & set(first.pages)
        )  # nothing that already has a snapshot is downloaded again
        self.assertTrue(second.fetched())  # ...but pages that failed last time (404 here) ARE retried
        self.assertEqual(
            result["import"]["counts"]["unchanged"], 5
        )  # 3 published + 2 draft records, none re-imported as new

    def test_restricted_sources_are_not_fetched(self):
        text = (ROOT / "sources.yaml").read_text(encoding="utf-8")
        marked = text.replace(
            'role: funding_channel\n    parser: curated_channel\n    language: en\n    allowed_domains: ["www.mnbc.ca"]\n    allowed_paths: ["/STEPS"]\n    access_status: unreviewed',
            'role: funding_channel\n    parser: curated_channel\n    language: en\n    allowed_domains: ["www.mnbc.ca"]\n    allowed_paths: ["/STEPS"]\n    access_status: restricted',
        )
        self.assertNotEqual(text, marked)
        path = self.data / "sources.yaml"
        path.write_text(marked, encoding="utf-8")
        self.rt = dataclasses.replace(self.rt, sources_config=path)
        router = Router()
        result = self.run_pipeline(router)
        self.assertFalse(any("mnbc.ca" in c for c in router.calls))
        self.assertEqual(result["sources"]["skipped"], 1)

    def test_page_budget_is_enforced_and_reported(self):
        result = self.run_pipeline(Router(), max_pages=3)
        self.assertEqual(result["exit_code"], 3)
        manifest = read_json(self.data / "runs" / f"{result['run_id']}.json")
        self.assertTrue(any("page budget" in p["reason"] for p in manifest["pending_verification"]))

    def test_dry_run_writes_no_database_rows(self):
        result = self.run_pipeline(Router(), dry_run=True)
        self.assertEqual((self.repo.records, self.repo.sources, self.repo.runs), ({}, {}, []))
        self.assertFalse((self.data / "awards.jsonl").exists())
        self.assertIn(result["exit_code"], (3,))

    def test_a_candidate_that_fails_verification_is_quarantined_and_fails_the_run(self):
        class Forging(Adapter):
            name = "ubc_sections"

            def parse(self, snaps, source, ctx):
                record = real_registry()["ubc_sections"].parse(snaps, source, ctx).candidates[0]
                record["evidence"][0]["quote"] = "A sentence the page never contained."
                return AdapterResult(candidates=[finalize(record)])

        adapters = {**real_registry(), "ubc_sections": Forging()}
        with mock.patch("navigator.services.live.registry", return_value=adapters):
            result = self.run_pipeline(Router())
        self.assertEqual((result["exit_code"], result["rejected_candidates"]), (1, 1))
        rows = [
            json.loads(line) for p in (self.data / "quarantine").glob("*.jsonl") for line in p.read_text().splitlines()
        ]
        self.assertTrue(any(r["error_type"] == "evidence.quote_not_found" for r in rows))

    def test_extract_command_works_from_stored_snapshots_without_network(self):
        self.run_pipeline(Router())
        out = live.run_extract_only(self.rt, now=AS_OF)
        self.assertEqual(
            (out["exit_code"], out["candidates"], out["rejected"]), (0, 3 + 2, 0)
        )  # includes the two draft sections
        empty = tempfile.TemporaryDirectory()
        rt = dataclasses.replace(self.rt, data_dir=Path(empty.name), artifact_root=Path(empty.name))
        self.assertEqual(live.run_extract_only(rt, now=AS_OF)["exit_code"], 3)
        empty.cleanup()

    def test_fetch_command_only_downloads(self):
        out = live.run_fetch_only(
            self.rt, now=AS_OF, max_pages=50, resume=False, refresh=False, fetcher=live.build_fetcher(self.rt, Router())
        )
        self.assertEqual(out["sources"]["succeeded"], 10)
        self.assertTrue((self.data / "discovery" / "fetch_index.json").is_file())
        self.assertFalse((self.data / "candidates").exists())

    def test_live_runtime_is_required(self):
        with self.assertRaises(ValueError):
            live.run_live_pipeline(
                self.repo, derive_runtime({}, "demo"), now=AS_OF, limit=1, max_pages=1, resume=False, refresh=False
            )


if __name__ == "__main__":
    unittest.main()
