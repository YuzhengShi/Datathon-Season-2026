import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from navigator.config import ConfigError, derive_runtime
from navigator.ingestion.fsutil import read_json
from navigator.ingestion.memory_repo import MemoryRepository
from navigator.services.pipeline import run_demo_pipeline
from tests.support import AS_OF, DemoEnv, refinger


class DemoPipelineTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.data_dir = Path(self.tmp.name)
        self.rt = derive_runtime({"DATA_DIR": str(self.data_dir)}, "demo")
        self.repo = MemoryRepository()

    def tearDown(self):
        self.tmp.cleanup()

    def test_end_to_end_without_network_or_keys(self):
        result = run_demo_pipeline(self.repo, self.rt, as_of=AS_OF)
        self.assertEqual((result["exit_code"], result["data_mode"]), (0, "demo"))
        self.assertEqual(result["import"]["counts"]["created"], 25)
        root = self.data_dir / "demo"
        for rel in ("candidates/awards.jsonl", "awards.jsonl", "reports/validation.json", "reports/import.json",
                    "reports/freshness.json", "reports/freshness.md", f"runs/{result['run_id']}.json"):
            self.assertTrue((root / rel).is_file(), rel)
        exported = [json.loads(line) for line in (root / "awards.jsonl").read_text(encoding="utf-8").splitlines()]
        self.assertEqual(len(exported), 25)
        self.assertTrue(all(r["is_demo"] and r["last_verified_at"] for r in exported))
        self.assertEqual([p.name for p in self.data_dir.iterdir()], ["demo"])  # nothing leaked into the live tree

    def test_manifest_records_steps_sources_and_pending_ocr(self):
        result = run_demo_pipeline(self.repo, self.rt, as_of=AS_OF)
        manifest = read_json(self.data_dir / "demo" / "runs" / f"{result['run_id']}.json")
        self.assertEqual([s["step"] for s in manifest["completed_steps"]],
                         ["synthetic_snapshots", "candidates", "validate", "import", "export", "report"])
        self.assertEqual((manifest["status"], manifest["data_mode"]), ("ok", "demo"))
        self.assertTrue(any("ocr_required" in p["reason"] for p in manifest["pending_verification"]))
        self.assertEqual(manifest["sources"]["demo_foundation_scanned_notice"]["status"], "ocr_required")
        self.assertTrue(all("sha256" in a for a in manifest["artifacts"].values() if a["path"].endswith(".jsonl")))

    def test_rerun_is_idempotent_and_does_not_duplicate_snapshots(self):
        run_demo_pipeline(self.repo, self.rt, as_of=AS_OF)
        raw_before = sorted(p.name for p in (self.data_dir / "demo" / "raw").rglob("*") if p.is_file())
        second = run_demo_pipeline(self.repo, self.rt, as_of=AS_OF)
        self.assertEqual(second["import"]["counts"], {"created": 0, "updated": 0, "unchanged": 25, "rejected": 0, "pending_review": 0})
        self.assertEqual(raw_before, sorted(p.name for p in (self.data_dir / "demo" / "raw").rglob("*") if p.is_file()))
        self.assertEqual(self.repo.revisions, [])

    def test_freshness_report_content(self):
        run_demo_pipeline(self.repo, self.rt, as_of=AS_OF)
        report = read_json(self.data_dir / "demo" / "reports" / "freshness.json")
        self.assertEqual((report["data_mode"], report["as_of"]), ("demo", "2026-10-07T12:00:00Z"))
        self.assertIsNone(report["target"])  # the 20-30 real-opportunity target is a live concept
        self.assertTrue(report["opportunities"]["is_demo_dataset"])
        self.assertEqual({k: report["opportunities"][k] for k in ("total", "award", "funding_channel", "award_collection")},
                         {"total": 25, "award": 23, "funding_channel": 1, "award_collection": 1})
        self.assertEqual(report["opportunities"]["distinct_administrators"], 3)
        self.assertEqual(report["cycles"]["expired"], 1)
        self.assertGreaterEqual(report["gaps"]["amount_unknown"], 3)
        self.assertEqual(report["gaps"]["shared_application_groups"], 1)
        self.assertEqual(report["gaps"]["group_exceptions"], 1)
        self.assertEqual((report["gaps"]["records_with_funder_side_conditions"], report["gaps"]["records_with_conflicts"]), (1, 0))
        self.assertEqual(report["verification"]["never_verified"], 0)
        self.assertEqual(len(report["ocr_required_documents"]), 1)
        self.assertEqual(report["review"]["human_reviewed"], 0)  # machine_checked is never dressed up as review
        markdown = (self.data_dir / "demo" / "reports" / "freshness.md").read_text(encoding="utf-8")
        self.assertIn("SYNTHETIC DEMO DATA", markdown)

    def test_staleness_shows_up_when_time_passes(self):
        from navigator.core.timeutil import parse_as_of
        from navigator.reports.freshness import build_freshness_report
        run_demo_pipeline(self.repo, self.rt, as_of=AS_OF)
        records = self.repo.list_records(published_only=False, is_demo=True)
        later = parse_as_of("2026-12-31")
        report = build_freshness_report(records, mode="demo", as_of=later, generated_at=later, freshness_days=30)
        self.assertEqual(report["verification"]["verification_stale"], 25)

    def test_dry_run_writes_nothing_durable(self):
        result = run_demo_pipeline(self.repo, self.rt, as_of=AS_OF, dry_run=True)
        self.assertEqual(result["exit_code"], 0)
        self.assertEqual((self.repo.records, self.repo.sources, self.repo.runs), ({}, {}, []))
        self.assertFalse((self.data_dir / "demo" / "awards.jsonl").exists())

    def test_invalid_candidates_fail_the_run_and_are_quarantined(self):
        forged = DemoEnv.get().all_records()
        forged[0]["evidence"][0]["quote"] = "forged sentence"
        forged[0] = refinger(forged[0])
        with mock.patch("navigator.services.pipeline.build_demo_records", return_value=forged):
            result = run_demo_pipeline(self.repo, self.rt, as_of=AS_OF)
        self.assertEqual(result["exit_code"], 1)
        self.assertEqual(self.repo.records, {})
        rows = [json.loads(line) for line in next((self.data_dir / "demo" / "quarantine").glob("*.jsonl")).read_text().splitlines()]
        self.assertEqual(rows[0]["error_type"], "evidence.quote_not_found")

    def test_demo_pipeline_refuses_a_live_runtime(self):
        with self.assertRaises(ValueError):
            run_demo_pipeline(self.repo, derive_runtime({"DATA_DIR": str(self.data_dir)}, "live"), as_of=AS_OF)


class ConfigTests(unittest.TestCase):
    def test_mode_precedence_and_isolation(self):
        demo = derive_runtime({}, "demo")
        live = derive_runtime({}, "live")
        self.assertNotEqual(demo.database_url, live.database_url)
        self.assertNotEqual(demo.artifact_root, live.artifact_root)
        self.assertEqual(demo.artifact_root, live.data_dir / "demo")
        self.assertEqual(derive_runtime({"DATA_MODE": "demo"}).mode, "demo")
        self.assertEqual(derive_runtime({"DATA_MODE": "demo"}, "live").mode, "live")  # --mode wins
        self.assertEqual(derive_runtime({}).mode, "live")
        self.assertEqual(derive_runtime({"DATABASE_URL": "postgresql+psycopg://u:p@h/db"}, "live").database_url.split(":")[0], "postgresql+psycopg")

    def test_unsafe_or_invalid_settings_are_refused(self):
        for raw in ({"DEMO_DATABASE_URL": "sqlite:///./data/navigator.db"},
                    {"DEMO_DATABASE_URL": "sqlite:///data/navigator.db"},  # same file, different spelling
                    {"EXTRACTION_MODE": "magic"}, {"FETCH_RETRIES": "many"}, {"FRESHNESS_DAYS": "0"}):
            with self.subTest(raw=raw), self.assertRaises(ConfigError):
                derive_runtime(raw)
        with self.assertRaises(ConfigError):
            derive_runtime({}, "production")

    def test_secrets_never_appear_in_the_printable_view(self):
        rt = derive_runtime({"OPENAI_API_KEY": "sk-secret-value", "OPENAI_MODEL": "m", "DATABASE_URL": "postgresql://u:pw@h/db"}, "live")
        self.assertTrue(rt.llm_configured)
        shown = json.dumps(rt.describe())
        self.assertNotIn("sk-secret-value", shown)
        self.assertNotIn("pw", shown)
        self.assertFalse(derive_runtime({"OPENAI_API_KEY": "sk-x"}, "live").llm_configured)  # no model => not configured


if __name__ == "__main__":
    unittest.main()
