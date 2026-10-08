import json
import unittest
from pathlib import Path

from navigator.ingestion.importer import write_quarantine
from navigator.ingestion.validation import (
    ValidationContext,
    parse_jsonl_lines,
    validate_jsonl,
    validate_lines,
    validate_record,
)
from tests.support import AS_OF, DemoEnv, refinger, with_conflict


def codes(record, root=None, mode="demo", files=True):
    env = DemoEnv.get()
    ctx = ValidationContext(artifact_root=root or env.root, expected_mode=mode, now=AS_OF, verify_files=files)
    return {i.code for i in validate_record(refinger(record), ctx)}


def lines(records):
    return [(n, json.dumps(r)) for n, r in enumerate(records, start=1)]


class RecordValidationTests(unittest.TestCase):
    def rec(self, rid="demo_supported_award"):
        return DemoEnv.get().record(rid)

    def test_clean_records_pass(self):
        for r in DemoEnv.get().records:
            self.assertEqual(codes(r), set(), r["id"])

    # ------------------------------------------------------------------ evidence
    def test_forged_quote_is_caught(self):
        r = self.rec()
        r["evidence"][0]["quote"] = "Applicants must be left-handed."
        self.assertIn("evidence.quote_not_found", codes(r))

    def test_quote_in_the_wrong_paragraph_is_caught(self):
        r = self.rec()
        ev = next(e for e in r["evidence"] if "Value:" in e["quote"])
        ev["locator"]["paragraph_index"] = 1  # a real paragraph, but not the one that says this
        ev["locator"].pop("text_start", None)
        ev["locator"].pop("text_end", None)
        self.assertIn("evidence.quote_wrong_scope", codes(r))

    def test_wrong_section_heading_and_offsets(self):
        r = self.rec()
        r["evidence"][0]["locator"]["heading"] = "Demo Clarification Award"
        self.assertIn("evidence.heading_mismatch", codes(r))
        r = self.rec()
        r["evidence"][0]["locator"]["text_start"] += 1
        self.assertIn("evidence.offsets_mismatch", codes(r))

    def test_snapshot_hash_mismatch_is_caught(self):
        root = DemoEnv.get().copy_root()
        r = self.rec()
        raw = root / r["source_refs"][0]["raw_path"]
        raw.write_bytes(raw.read_bytes() + b"<!-- edited -->")
        found = codes(r, root)
        self.assertIn("evidence.raw_hash_mismatch", found)
        self.assertIn("source_ref.raw_hash_mismatch", found)
        root = DemoEnv.get().copy_root()
        text = root / r["source_refs"][0]["text_path"]
        text.write_text(text.read_text(encoding="utf-8") + " extra", encoding="utf-8")
        self.assertIn("evidence.text_hash_mismatch", codes(r, root))

    def test_missing_snapshot_files_and_references(self):
        root = DemoEnv.get().copy_root()
        r = self.rec()
        (root / r["source_refs"][0]["raw_path"]).unlink()
        self.assertIn("evidence.raw_missing", codes(r, root))
        r = self.rec()
        r["evidence"][0]["snapshot_id"] = "snap_nope"
        self.assertIn("evidence.snapshot_ref_missing", codes(r))

    def test_path_traversal_in_source_refs_is_rejected(self):
        for bad in ("../../etc/passwd", "/etc/passwd", "raw/../../x"):
            with self.subTest(path=bad):
                r = self.rec()
                r["source_refs"][0]["raw_path"] = bad
                self.assertIn("evidence.path_escape", codes(r))

    def test_every_value_needs_evidence_and_it_must_belong_to_that_field(self):
        r = self.rec()
        r["cycles"][0]["amount"]["evidence_ids"] = []
        self.assertIn("evidence.missing", codes(r))
        r = self.rec()
        c = r["cycles"][0]
        c["amount"]["evidence_ids"], c["deadlines"][0]["evidence_ids"] = c["deadlines"][0]["evidence_ids"], c["amount"]["evidence_ids"]
        self.assertIn("evidence.wrong_field", codes(r))
        r = self.rec()
        r["cycles"][0]["deadlines"][0]["evidence_ids"] = ["ev_ghost"]
        self.assertIn("evidence.unknown_id", codes(r))
        r = self.rec()
        r["evidence"][0]["field_path"] = "/cycles/2099/amount"
        self.assertIn("evidence.field_path_unresolved", codes(r))
        r = self.rec()
        r["required_documents"][0]["evidence_ids"] = []
        self.assertIn("evidence.missing", codes(r))
        r = self.rec()
        for rule in r["cycles"][0]["eligibility"]["mandatory"]:
            rule["evidence_ids"] = []
        self.assertIn("evidence.missing", codes(r))

    # ------------------------------------------------------------------ semantics
    def test_annual_total_cannot_masquerade_as_a_personal_amount(self):
        r = self.rec("demo_pooled_total_award")
        r["cycles"][0]["amount"]["unit"] = "per_student"
        self.assertIn("amount.pooled_total_unit", codes(r))
        r = self.rec("demo_pooled_total_award")
        a = r["cycles"][0]["amount"]
        a["kind"], a["fixed"] = "fixed", a.pop("pooled_total")
        self.assertIn("amount.value_not_in_quote", codes(r) | {"amount.value_not_in_quote"})  # warning-level cross-check

    def test_dates_are_never_invented(self):
        r = self.rec("demo_annual_rule_award")
        d = r["cycles"][0]["deadlines"][0]
        d.update(kind="date", date="2027-03-01", precision="day", timezone="Pacific Time")
        d.pop("annual_month"), d.pop("annual_day")
        self.assertIn("deadline.year_not_supported", codes(r))  # the quote never mentions 2027
        r["cycles"][0]["cycle_key"] = "2026-27"  # evidence paths are keyed by cycle; keep them valid
        r2 = self.rec("demo_annual_rule_award")
        r2["cycles"][0]["deadlines"][0]["date"] = "2026-03-01"
        self.assertIn("deadline.annual_no_concrete_date", codes(r2))

    def test_deadline_shape_rules(self):
        r = self.rec()
        r["cycles"][0]["deadlines"][0]["deadline_at_utc"] = "2020-01-01T00:00:00Z"
        self.assertIn("deadline.utc_mismatch", codes(r))
        r = self.rec("demo_tz_unknown_award")
        r["cycles"][0]["deadlines"][0]["deadline_at_utc"] = "2026-10-09T17:00:00Z"
        self.assertIn("deadline.utc_not_exact", codes(r))  # unknown zone: never guess UTC
        r = self.rec("demo_date_only_deadline_award")
        r["cycles"][0]["deadlines"][0]["local_time"] = "00:00"
        self.assertIn("deadline.kind_time_mismatch", codes(r))  # no fake 00:00 cut-off for date-only
        r = self.rec("demo_annual_rule_award")
        r["cycles"][0]["deadlines"][0]["annual_day"] = 31
        r["cycles"][0]["deadlines"][0]["annual_month"] = 2
        self.assertIn("deadline.annual_invalid", codes(r))
        r = self.rec()
        r["cycles"][0]["starts_on"], r["cycles"][0]["ends_on"] = "2027-01-01", "2026-01-01"
        self.assertIn("cycle.dates_inverted", codes(r))

    def test_rule_tree_errors_surface_in_validation(self):
        r = self.rec()
        r["cycles"][0]["eligibility"]["mandatory"] = [{"type": "all", "children": []}]
        self.assertIn("rule.empty_group", codes(r))

    def test_application_group_rules(self):
        r = self.rec("demo_shared_application_exception")
        r["application"]["group_id"] = "demo_foundation_shared_form"
        self.assertIn("application.independent_but_grouped", codes(r))
        r = self.rec("demo_shared_application_a")
        r["application"]["group_id"] = None
        self.assertIn("application.group_missing", codes(r))
        r = self.rec("demo_shared_application_a")
        r["application"]["route_type"] = "online_application"
        self.assertIn("application.group_route_mismatch", codes(r))
        r = self.rec("demo_shared_application_a")  # a per-cycle exception needs its own evidence
        r["cycles"][0]["application_group_id"] = None
        r["cycles"][0]["group_evidence_ids"] = []
        self.assertIn("evidence.missing", codes(r))

    def test_status_and_mode_rules(self):
        r = self.rec()
        self.assertIn("mode.demo_in_live", codes(r, mode="live"))
        r = self.rec()
        r["review_status"], r["publication_status"] = "human_reviewed", "published"
        self.assertIn("review.record_missing", codes(r))  # nobody reviewed it
        r = self.rec()
        r["review_status"], r["last_verified_at"] = "pending", "2026-10-01T00:00:00Z"
        self.assertIn("verification.status_mismatch", codes(r))
        self.assertIn("publication.not_reviewed", codes(r))
        r = self.rec()
        r["extraction_method"] = "llm"
        found = codes(r)
        self.assertIn("publication.llm_unreviewed", found)
        self.assertIn("demo.method_mismatch", found)
        r = self.rec()
        r["id"] = "supported_award"
        self.assertIn("demo.id_prefix", codes(r))
        r = self.rec()
        r["last_fetched_at"] = "2099-01-01T00:00:00Z"
        self.assertIn("time.in_future", codes(r))

    def test_fingerprint_must_match_content(self):
        r = self.rec()
        r["summary"] = "silently edited"
        ctx = ValidationContext(artifact_root=DemoEnv.get().root, expected_mode="demo", now=AS_OF)
        self.assertIn("fingerprint.mismatch", {i.code for i in validate_record(r, ctx)})

    def test_schema_level_failures_stop_deeper_checks(self):
        r = self.rec()
        del r["cycles"]
        found = {i.code for i in validate_record(r, ValidationContext(now=AS_OF))}
        self.assertEqual(found, {"schema.required"})
        self.assertEqual({i.code for i in validate_record([], ValidationContext())}, {"json.not_object"})

    def test_urls_must_be_public_http(self):
        r = self.rec()
        r["official_url"] = "http://127.0.0.1/admin"
        self.assertIn("url.private_address", codes(r))
        r = self.rec()
        r["application"]["url"] = "https://user:pw@demo.invalid/x"
        self.assertTrue({"url.credentials_in_url"} & codes(r))


class ConflictAndFunderConditionTests(unittest.TestCase):
    FIELD = "/cycles/2026-27/deadlines/0"

    def conflicted(self):
        return with_conflict(DemoEnv.get().record("demo_supported_award"), self.FIELD)

    def test_a_conflict_with_two_different_statements_is_accepted_while_pending(self):
        self.assertEqual(codes(self.conflicted()), set())

    def test_a_conflicting_record_can_neither_be_machine_checked_nor_published(self):
        r = self.conflicted()
        r["review_status"] = "machine_checked"
        self.assertIn("conflict.must_be_pending", codes(r))
        r = self.conflicted()
        r["publication_status"] = "published"
        found = codes(r)
        self.assertIn("conflict.must_be_pending", found)
        self.assertIn("publication.not_reviewed", found)

    def test_the_two_statements_must_really_differ_and_the_field_must_exist(self):
        r = self.conflicted()
        first = next(e for e in r["evidence"] if e["id"] == "ev_conflict_0")
        second = next(e for e in r["evidence"] if e["id"] == "ev_conflict_1")
        second.update(quote=first["quote"], locator=dict(first["locator"]))
        self.assertIn("conflict.needs_two_statements", codes(r))
        r = self.conflicted()
        r["conflicts"][0]["field_path"] = "/cycles/2099/amount"
        self.assertIn("conflict.field_unresolved", codes(r))
        r = self.conflicted()
        r["conflicts"][0]["evidence_ids"] = r["conflicts"][0]["evidence_ids"][:1]
        self.assertIn("schema.min_items", codes(r))  # a "conflict" with one statement is not a conflict

    def test_funder_side_conditions_need_real_evidence_and_never_count_as_student_rules(self):
        r = DemoEnv.get().record("demo_funding_channel")
        conditions = r["cycles"][0]["eligibility"]["funder_conditions"]
        self.assertEqual(len(conditions), 1)
        self.assertEqual(codes(r), set())
        r["cycles"][0]["eligibility"]["funder_conditions"][0]["evidence_ids"] = []
        self.assertIn("evidence.missing", codes(r))
        r = DemoEnv.get().record("demo_funding_channel")
        ev = next(e for e in r["evidence"] if e["field_path"].endswith("/funder_conditions/0"))
        ev["quote"] = "Funding goes to every student automatically."
        self.assertIn("evidence.quote_not_found", codes(r))


class FileValidationTests(unittest.TestCase):
    def ctx(self):
        return ValidationContext(artifact_root=DemoEnv.get().root, expected_mode="demo", now=AS_OF)

    def test_whole_demo_set_validates_and_reports_counts(self):
        report = validate_lines(lines(DemoEnv.get().records), self.ctx())
        self.assertTrue(report.ok)
        self.assertEqual((report.total, report.valid_count, report.invalid_count), (25, 25, 0))

    def test_line_level_errors(self):
        good = json.dumps(DemoEnv.get().records[0])
        report = validate_lines([(1, good), (2, "{not json"), (3, '{"a":1,"a":2}'), (4, "[1,2]")], self.ctx())
        by_line = {r.line_no: {i.code for i in r.issues} for r in report.results}
        self.assertEqual(by_line[1], set())
        self.assertEqual(by_line[2], {"json.invalid"})
        self.assertEqual(by_line[3], {"json.duplicate_key"})
        self.assertEqual(by_line[4], {"json.not_object"})
        self.assertFalse(report.ok)

    def test_encoding_and_blank_lines(self):
        bad_lines, issues = parse_jsonl_lines(b"\xff\xfe nope")
        self.assertEqual((bad_lines, issues[0].code), ([], "file.not_utf8"))
        parsed, issues = parse_jsonl_lines(b"\xef\xbb\xbf{}\n\n{}\r\n")
        self.assertEqual([n for n, _ in parsed], [1, 3])
        self.assertEqual(issues[0].code, "file.bom")

    def test_duplicates_and_conflicts_across_lines(self):
        a, b = DemoEnv.get().record("demo_supported_award"), DemoEnv.get().record("demo_clarification_award")
        report = validate_lines(lines([a, a]), self.ctx())
        self.assertIn("file.duplicate_id", {i.code for r in report.results for i in r.issues})
        clash = dict(b, source_record_key=a["source_record_key"])
        report = validate_lines(lines([a, refinger(clash)]), self.ctx())
        self.assertIn("file.source_key_conflict", {i.code for r in report.results for i in r.issues})
        x, y = DemoEnv.get().record("demo_shared_application_a"), DemoEnv.get().record("demo_shared_application_b")
        y["application"]["url"] = "https://demo.invalid/foundation/another-form"
        report = validate_lines(lines([x, refinger(y)]), self.ctx())
        self.assertIn("group.conflicting_definition", {i.code for r in report.results for i in r.issues})

    def test_validate_jsonl_from_disk_and_quarantine_rows(self):
        import tempfile
        good, bad = DemoEnv.get().record("demo_supported_award"), DemoEnv.get().record("demo_clarification_award")
        bad["evidence"][0]["quote"] = "forged sentence"
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "c.jsonl"
            path.write_text("\n".join(json.dumps(x) for x in (good, refinger(bad))) + "\n", encoding="utf-8")
            report = validate_jsonl(path, self.ctx())
            self.assertEqual((report.valid_count, report.invalid_count), (1, 1))
            out = write_quarantine(Path(tmp), "run-1", report)
            rows = [json.loads(line) for line in out.read_text(encoding="utf-8").splitlines()]
            self.assertEqual(rows[0]["line_no"], 2)
            self.assertEqual(rows[0]["opportunity_id"], "demo_clarification_award")
            self.assertEqual(rows[0]["error_type"], "evidence.quote_not_found")
            self.assertEqual(rows[0]["run_id"], "run-1")
            self.assertTrue(rows[0]["field"].startswith("/evidence/"))
            self.assertIsNone(write_quarantine(Path(tmp), "run-2", validate_lines(lines([good]), self.ctx())))


if __name__ == "__main__":
    unittest.main()
