import copy
import json
import tempfile
import unittest
from pathlib import Path

from navigator.core.fingerprint import compute_fingerprint
from navigator.core.timeutil import parse_as_of
from navigator.ingestion.importer import export_public, import_records
from navigator.ingestion.memory_repo import MemoryRepository
from navigator.ingestion.planner import plan_import
from navigator.ingestion.rows import canonicalize_record, record_to_rows, rows_to_record
from navigator.ingestion.validation import ValidationContext, validate_lines
from tests.support import DemoEnv, refinger, with_conflict

NOW = "2026-10-07T12:00:00Z"


LATER = parse_as_of("2027-01-01")  # "now" for validation, so test records may carry later timestamps


def validation(records, mode="demo"):
    ctx = ValidationContext(artifact_root=DemoEnv.get().root, expected_mode=mode, now=LATER)
    return validate_lines([(n, json.dumps(r)) for n, r in enumerate(records, start=1)], ctx)


def do_import(repo, records, **kw):
    return import_records(repo, validation(records), mode=kw.pop("mode", "demo"), run_id=kw.pop("run_id", "r1"),
                          now_iso=NOW, **kw)


def bad_record():
    r = DemoEnv.get().record("demo_clarification_award")
    r["evidence"][0]["quote"] = "forged sentence"
    return refinger(r)


def fresh_pipeline_records():
    return [dict(r, last_verified_at=NOW) for r in DemoEnv.get().all_records()]


class IdempotencyTests(unittest.TestCase):
    def test_importing_twice_changes_nothing(self):
        repo, records = MemoryRepository(), fresh_pipeline_records()
        first = do_import(repo, records)
        self.assertEqual((first.status, first.counts["created"], first.exit_code), ("ok", 25, 0))
        snapshot = copy.deepcopy(repo.records)
        second = do_import(repo, copy.deepcopy(records), run_id="r2")
        self.assertEqual((second.counts["created"], second.counts["updated"], second.counts["unchanged"]), (0, 0, 25))
        self.assertEqual(repo.records, snapshot)
        self.assertEqual(repo.revisions, [])
        self.assertEqual(len(repo.runs), 2)  # run audit grows; business objects do not

    def test_rows_roundtrip_loses_nothing(self):
        for r in DemoEnv.get().records:
            with self.subTest(id=r["id"]):
                canonical = canonicalize_record(r)
                self.assertEqual(rows_to_record(record_to_rows(canonical)), canonical)
                self.assertEqual(compute_fingerprint(rows_to_record(record_to_rows(canonical))), r["content_fingerprint"])

    def test_export_then_import_preserves_rules_dates_amounts_evidence_and_groups(self):
        a = MemoryRepository()
        do_import(a, fresh_pipeline_records())
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "awards.jsonl"
            info = export_public(a, path, mode="demo")
            self.assertEqual(info["records"], 25)
            exported = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
        b = MemoryRepository()
        report = do_import(b, exported, run_id="r-b")
        self.assertEqual(report.counts["created"], 25)
        self.assertEqual(a.records, b.records)
        shared = b.records["demo_shared_application_a"][0]
        self.assertEqual(shared["application"]["group_id"], "demo_foundation_shared_form")
        self.assertTrue(shared["evidence"] and shared["cycles"][0]["eligibility"]["mandatory"])

    def test_empty_dataset_has_a_real_empty_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            info = export_public(MemoryRepository(), Path(tmp) / "awards.jsonl", mode="live")
            self.assertEqual((info["records"], info["empty"]), (0, True))
            self.assertEqual((Path(tmp) / "awards.jsonl").read_text(), "")


class AtomicityTests(unittest.TestCase):
    def test_bad_record_rejects_the_whole_batch_by_default(self):
        repo = MemoryRepository()
        records = [r for r in fresh_pipeline_records() if r["id"] != "demo_clarification_award"] + [bad_record()]
        report = do_import(repo, records)
        self.assertEqual((report.status, report.exit_code), ("rejected", 1))
        self.assertEqual(repo.records, {})  # nothing at all was written
        self.assertEqual(repo.runs, [])
        self.assertEqual(report.validation["invalid"], 1)

    def test_database_failure_rolls_everything_back(self):
        repo = MemoryRepository()
        repo.fail_on = {"demo_funding_channel"}
        report = do_import(repo, fresh_pipeline_records())
        self.assertEqual((report.status, report.exit_code), ("failed", 1))
        self.assertIn("rolled back", report.error)
        self.assertEqual(repo.records, {})  # parent rows were not left behind

    def test_failed_update_leaves_the_old_version_intact(self):
        repo = MemoryRepository()
        do_import(repo, fresh_pipeline_records())
        before = copy.deepcopy(repo.records)
        changed = fresh_pipeline_records()
        for r in changed:
            if r["id"] in {"demo_supported_award", "demo_funding_channel"}:
                r["summary"] = r["summary"] + " (edited)"
                r["content_fingerprint"] = compute_fingerprint(r)
        repo.fail_on = {"demo_funding_channel"}
        report = do_import(repo, changed, run_id="r2")
        self.assertEqual(report.status, "failed")
        self.assertEqual(repo.records, before)  # the first update was rolled back with the second

    def test_allow_partial_commits_the_good_records_and_still_exits_nonzero(self):
        repo = MemoryRepository()
        records = [r for r in fresh_pipeline_records() if r["id"] != "demo_clarification_award"] + [bad_record()]
        report = do_import(repo, records, allow_partial=True)
        self.assertEqual((report.status, report.exit_code), ("partial", 1))
        self.assertEqual((report.counts["created"], report.counts["rejected"]), (24, 1))
        self.assertEqual(len(repo.records), 24)

    def test_allow_partial_with_a_db_error_on_one_record(self):
        repo = MemoryRepository()
        repo.fail_on = {"demo_funding_channel"}
        report = do_import(repo, fresh_pipeline_records(), allow_partial=True)
        self.assertEqual((report.status, report.exit_code), ("partial", 1))
        self.assertEqual((report.counts["created"], report.counts["rejected"]), (24, 1))
        self.assertNotIn("demo_funding_channel", repo.records)
        failed = next(i for i in report.items if i["id"] == "demo_funding_channel")
        self.assertEqual(failed["action"], "rejected")

    def test_dry_run_computes_the_diff_and_writes_nothing(self):
        repo = MemoryRepository()
        do_import(repo, fresh_pipeline_records())
        before_records, before_runs = copy.deepcopy(repo.records), copy.deepcopy(repo.runs)
        with tempfile.TemporaryDirectory() as tmp:
            export = Path(tmp) / "awards.jsonl"
            export_public(repo, export, mode="demo")
            exported = export.read_bytes()
            changed = fresh_pipeline_records()
            changed[0]["cycles"][0]["amount"]["raw_text"] = changed[0]["cycles"][0]["amount"]["raw_text"] + " (edited)"
            changed[0]["content_fingerprint"] = compute_fingerprint(changed[0])
            report = do_import(repo, changed, dry_run=True, run_id="dry")
            self.assertEqual((report.status, report.counts["updated"], report.counts["unchanged"]), ("ok", 1, 24))
            self.assertEqual(repo.records, before_records)
            self.assertEqual(repo.runs, before_runs)
            self.assertEqual(export.read_bytes(), exported)
        self.assertTrue(report.items[0]["changes"] or any(i["changes"] for i in report.items))


class VersionPrecedenceTests(unittest.TestCase):
    def setUp(self):
        self.repo = MemoryRepository()
        self.records = fresh_pipeline_records()
        do_import(self.repo, self.records)

    def update_current_cycle(self, **fixed):
        r = copy.deepcopy(next(x for x in self.records if x["id"] == "demo_multi_cycle_award"))
        cycle = next(c for c in r["cycles"] if c["cycle_key"] == "2026-27")
        cycle["amount"].update(fixed)
        cycle["amount"]["raw_text"] = "$900 CAD in each intake"
        r["cycles"] = [cycle]  # the new input does not list the old cycle at all ...
        r["evidence"] = [e for e in r["evidence"] if "/cycles/2019-20" not in e["field_path"]]  # ... nor its evidence
        r["last_fetched_at"] = "2026-10-08T12:00:00Z"
        return refinger(r)

    def test_updating_the_current_cycle_keeps_the_old_one(self):
        report = do_import(self.repo, [self.update_current_cycle(fixed="900")], run_id="r2")
        item = report.items[0]
        self.assertEqual((item["action"], item["cycles"]), ("updated", {"2026-27": "updated", "2019-20": "retained"}))
        stored = self.repo.records["demo_multi_cycle_award"][0]
        self.assertEqual({c["cycle_key"] for c in stored["cycles"]}, {"2019-20", "2026-27"})
        old = next(c for c in stored["cycles"] if c["cycle_key"] == "2019-20")
        self.assertEqual(old["amount"]["fixed"], "800")
        self.assertEqual(self.repo.records["demo_multi_cycle_award"][1], 2)
        diff = self.repo.revisions[0]["diff"]
        self.assertIn("/cycles/2026-27/amount/fixed", [c["path"] for c in diff])

    def test_replaying_the_same_update_is_unchanged(self):
        update = self.update_current_cycle(fixed="900")
        do_import(self.repo, [update], run_id="r2")
        again = do_import(self.repo, [copy.deepcopy(update)], run_id="r3")
        self.assertEqual(again.items[0]["action"], "unchanged")
        self.assertEqual(self.repo.records["demo_multi_cycle_award"][1], 2)

    def test_an_older_snapshot_cannot_silently_overwrite_a_newer_version(self):
        do_import(self.repo, [self.update_current_cycle(fixed="900")], run_id="r2")
        stale = self.update_current_cycle(fixed="100")
        stale["last_fetched_at"] = "2026-09-01T00:00:00Z"
        report = do_import(self.repo, [refinger(stale)], run_id="r3")
        self.assertEqual(report.items[0]["action"], "pending_review")
        self.assertIn("older_input_would_overwrite_newer", report.items[0]["reasons"][0])
        stored = self.repo.records["demo_multi_cycle_award"][0]
        self.assertEqual(next(c for c in stored["cycles"] if c["cycle_key"] == "2026-27")["amount"]["fixed"], "900")
        self.assertEqual(report.status, "ok")  # a conflict is reported, not an error

    def test_an_explicit_later_verification_may_correct_an_earlier_fetch(self):
        stale = self.update_current_cycle(fixed="950")
        stale["last_fetched_at"] = "2026-09-01T00:00:00Z"
        stale["last_verified_at"] = "2026-10-09T00:00:00Z"  # reviewed after the stored version was verified
        report = do_import(self.repo, [refinger(stale)], run_id="r2")
        self.assertEqual(report.items[0]["action"], "updated")

    def test_nothing_is_deleted_when_a_source_stops_listing_an_item(self):
        report = do_import(self.repo, self.records[:3], run_id="r2")
        self.assertEqual(report.counts["unchanged"], 3)
        self.assertEqual(len(self.repo.records), 25)

    def test_verification_time_never_moves_backwards(self):
        newer = copy.deepcopy(self.records[0])
        newer["last_verified_at"] = "2026-12-01T00:00:00Z"
        do_import(self.repo, [newer], run_id="r2")
        older = copy.deepcopy(self.records[0])
        older["last_verified_at"] = "2026-11-01T00:00:00Z"
        do_import(self.repo, [older], run_id="r3")
        self.assertEqual(self.repo.records[self.records[0]["id"]][0]["last_verified_at"], "2026-12-01T00:00:00Z")

    def test_a_review_upgrade_is_not_undone_by_a_machine_rerun(self):
        reviewed = copy.deepcopy(self.records[0])
        reviewed.update(review_status="human_reviewed", review={"reviewer": "A. Reviewer", "reviewed_at": NOW})
        do_import(self.repo, [reviewed], run_id="r2")
        do_import(self.repo, [copy.deepcopy(self.records[0])], run_id="r3")
        self.assertEqual(self.repo.records[self.records[0]["id"]][0]["review_status"], "human_reviewed")


class ConflictHandlingTests(unittest.TestCase):
    def test_a_newly_found_conflict_unpublishes_the_record_instead_of_silently_choosing(self):
        repo = MemoryRepository()
        do_import(repo, fresh_pipeline_records())
        base = DemoEnv.get().record("demo_supported_award")
        base["last_verified_at"] = NOW
        conflicted = with_conflict(base, "/cycles/2026-27/deadlines/0")
        report = do_import(repo, [conflicted], run_id="r2")
        self.assertEqual(report.items[0]["action"], "updated")
        stored = repo.records["demo_supported_award"][0]
        self.assertEqual((stored["review_status"], stored["publication_status"]), ("pending", "draft"))
        self.assertEqual(len(stored["conflicts"]), 1)
        self.assertEqual(len(repo.list_records(published_only=True, is_demo=True)), 24)
        self.assertEqual(len(stored["conflicts"][0]["evidence_ids"]), 2)  # both statements are still on file


class ModeIsolationTests(unittest.TestCase):
    def test_demo_records_are_rejected_in_live_mode(self):
        repo = MemoryRepository()
        report = import_records(repo, validation(fresh_pipeline_records(), mode="live"), mode="live", run_id="x", now_iso=NOW)
        self.assertEqual(report.status, "rejected")
        self.assertEqual(repo.records, {})
        plan = plan_import(fresh_pipeline_records()[:2], {}, expected_mode="live")
        self.assertEqual({i.action for i in plan.items}, {"rejected"})
        self.assertIn("mode_mismatch", plan.items[0].reasons[0])

    def test_listing_is_scoped_to_one_mode(self):
        repo = MemoryRepository()
        do_import(repo, fresh_pipeline_records())
        self.assertEqual(len(repo.list_records(published_only=True, is_demo=True)), 25)
        self.assertEqual(repo.list_records(published_only=True, is_demo=False), [])

    def test_duplicate_ids_in_one_batch_are_rejected(self):
        r = fresh_pipeline_records()[0]
        plan = plan_import([r, copy.deepcopy(r)], {}, expected_mode="demo")
        self.assertEqual([i.action for i in plan.items], ["created", "rejected"])


if __name__ == "__main__":
    unittest.main()
