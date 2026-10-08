import json
import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path

from navigator.ingestion.fetch_stage import FetchIndex
from navigator.ingestion.manual import ManualImportError, import_manual_snapshot
from navigator.ingestion.snapshots import SnapshotStore
from navigator.ingestion.sources import load_sources

ROOT = Path(__file__).resolve().parent.parent
PAGE = "<html><body><main><h1>Indigenous awards</h1><p>Applications close on March 1.</p></main></body></html>"
SAVED = datetime(2026, 10, 8, 18, 0, tzinfo=UTC)


class ManualImportTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.root = Path(self.tmp.name)
        self.source = next(s for s in load_sources(ROOT / "sources.yaml") if s.source_id == "ubc_award_descriptions")
        self.store, self.index = SnapshotStore(self.root), FetchIndex(self.root / "index.json")
        self.audit = self.root / "audit.jsonl"
        self.page = self.root / "page.html"
        self.page.write_text(PAGE, encoding="utf-8")
        self.url = self.source.url

    def tearDown(self):
        self.tmp.cleanup()

    def run_import(self, url=None, file=None, **kw):
        args = dict(saved_by="A. Student", saved_at=SAVED, store=self.store, index=self.index, audit_path=self.audit)
        args.update(kw)
        return import_manual_snapshot(self.source, url or self.url, file or self.page, **args)

    def test_a_saved_page_becomes_a_normal_snapshot_with_its_provenance(self):
        summary = self.run_import()
        entry = FetchIndex(self.root / "index.json").entries[next(iter(self.index.entries))]
        self.assertEqual(
            (entry["acquisition"], entry["saved_by"], entry["fetched_at"]),
            ("manual_upload", "A. Student", "2026-10-08T18:00:00Z"),
        )
        self.assertTrue(self.store.verify_raw(entry["raw_path"], entry["raw_sha256"]))
        text = (self.root / entry["text_path"]).read_text(encoding="utf-8")
        self.assertIn("Applications close on March 1.", text)
        self.assertEqual(summary["acquisition"], "manual_upload")
        row = json.loads(self.audit.read_text(encoding="utf-8").splitlines()[-1])
        self.assertEqual(
            (row["outcome"], row["saved_by"], row["source_id"]),
            ("manual_import", "A. Student", "ubc_award_descriptions"),
        )

    def test_the_source_allowlist_still_applies(self):
        with self.assertRaises(ManualImportError):
            self.run_import(url="https://example.org/awards")
        self.assertEqual(self.index.entries, {})

    def test_it_refuses_unknown_provenance_and_unsupported_or_empty_files(self):
        with self.assertRaises(ManualImportError):
            self.run_import(saved_by="  ")
        text_file = self.root / "page.txt"
        text_file.write_text("x", encoding="utf-8")
        with self.assertRaises(ManualImportError):
            self.run_import(file=text_file)
        empty = self.root / "empty.html"
        empty.write_bytes(b"")
        with self.assertRaises(ManualImportError):
            self.run_import(file=empty)
        with self.assertRaises(ManualImportError):
            self.run_import(file=self.root / "missing.html")
        self.assertEqual(self.index.entries, {})

    def test_importing_the_same_page_twice_changes_nothing(self):
        first = self.run_import()
        second = self.run_import()
        self.assertEqual((first["snapshot_id"], first["raw_sha256"]), (second["snapshot_id"], second["raw_sha256"]))
        self.assertEqual(len(self.index.entries), 1)


if __name__ == "__main__":
    unittest.main()
