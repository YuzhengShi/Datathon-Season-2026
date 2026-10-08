import unittest
from datetime import UTC, datetime
from pathlib import Path

from navigator.core import contract
from navigator.core.evidence import (
    PathEscapeError,
    QuoteNotFoundError,
    locate_quote,
    normalize_text,
    safe_join,
)
from navigator.core.fingerprint import compute_fingerprint
from navigator.core.ids import evidence_id, make_opportunity_id
from navigator.core.jsonschema_lite import validate as schema_validate
from navigator.core.money import canonical_decimal, describe_amount, to_decimal, validate_amount
from navigator.core.timeutil import (
    FixedClock,
    canonical_deadline_utc,
    parse_as_of,
    resolve_close_window,
    resolve_timezone,
)
from navigator.core.urlpolicy import AllowRule, UnsafeUrlError, canonicalize_url, check_url
from tests.support import DemoEnv


def at(text: str) -> datetime:
    return parse_as_of(text)


class DeadlineTests(unittest.TestCase):
    def test_date_only_closes_at_end_of_local_day(self):
        d = {"kind": "date", "date": "2026-10-07", "timezone": "America/Vancouver"}
        w = resolve_close_window(d)
        self.assertEqual(w.state(at("2026-10-07")), "not_closed")  # noon UTC on the deadline day
        self.assertEqual(w.state(at("2026-10-08T06:59:00Z")), "not_closed")
        self.assertEqual(w.state(at("2026-10-08T07:00:00Z")), "closed")
        self.assertEqual(w.basis, "end_of_local_day")

    def test_unknown_timezone_never_closes_early(self):
        w = resolve_close_window({"kind": "date", "date": "2026-10-07"})
        self.assertIn("timezone_unknown", w.flags)
        self.assertEqual(w.state(at("2026-10-07T09:59:00Z")), "not_closed")
        self.assertEqual(w.state(at("2026-10-07T12:00:00Z")), "closing_ambiguous")
        self.assertEqual(w.state(at("2026-10-08T12:00:00Z")), "closed")
        self.assertIsNone(canonical_deadline_utc({"kind": "date", "date": "2026-10-07"}))

    def test_timezone_resolution(self):
        july, jan = at("2026-07-15").date(), at("2026-01-15").date()
        self.assertEqual(resolve_timezone("Eastern Time", july).status, "generic")
        self.assertEqual(resolve_timezone("EST", jan).status, "fixed")  # matches Toronto in winter
        amb = resolve_timezone("EST", july)  # "EST" in July contradicts Toronto's daylight time
        self.assertEqual(amb.status, "ambiguous")
        self.assertEqual(len(amb.candidates), 2)
        self.assertEqual(resolve_timezone("Moon/Base", jan).status, "unknown")
        self.assertEqual(resolve_timezone(None).status, "unknown")

    def test_literal_est_in_summer_keeps_both_readings(self):
        d = {"kind": "datetime", "date": "2026-07-15", "local_time": "23:59", "timezone": "EST"}
        w = resolve_close_window(d)
        self.assertIn("timezone_ambiguous", w.flags)
        self.assertLess(w.earliest_utc, w.latest_utc)
        self.assertIsNone(canonical_deadline_utc(d))
        generic = dict(d, timezone="Eastern Time")
        self.assertEqual(canonical_deadline_utc(generic), "2026-07-16T04:00:00Z")

    def test_dst_repeated_and_skipped_local_times(self):
        repeated = resolve_close_window({"kind": "datetime", "date": "2026-11-01", "local_time": "01:29",
                                         "timezone": "America/Toronto"})
        self.assertIn("dst_repeated_local_time", repeated.flags)
        self.assertEqual(repeated.latest_utc - repeated.earliest_utc, at("2026-11-01T06:30:00Z") - at("2026-11-01T05:30:00Z"))
        skipped = resolve_close_window({"kind": "datetime", "date": "2026-03-08", "local_time": "02:29",
                                        "timezone": "America/Toronto"})
        self.assertIn("dst_skipped_local_time", skipped.flags)

    def test_non_instant_kinds_never_resolve(self):
        for kind in ("annual_rule", "rolling", "local_administrator", "unspecified"):
            self.assertIsNone(resolve_close_window({"kind": kind}))

    def test_as_of_parsing(self):
        self.assertEqual(parse_as_of("2026-10-07"), datetime(2026, 10, 7, 12, 0, tzinfo=UTC))
        self.assertEqual(parse_as_of("2026-10-07T01:02:03"), datetime(2026, 10, 7, 1, 2, 3, tzinfo=UTC))
        self.assertEqual(parse_as_of(None, FixedClock(datetime(2030, 1, 1, tzinfo=UTC))).year, 2030)


class MoneyTests(unittest.TestCase):
    base = {"currency": "CAD", "unit": "per_student", "renewable": None, "raw_text": "x", "evidence_ids": []}

    def codes(self, **kw):
        return {i.code for i in validate_amount({**self.base, **kw}, "/a")}

    def test_floats_are_rejected(self):
        with self.assertRaises(TypeError):
            to_decimal(12.5)
        with self.assertRaises(ValueError):
            to_decimal("-1")
        self.assertEqual(canonical_decimal("5000.00"), "5000")

    def test_kind_field_consistency(self):
        self.assertEqual(self.codes(kind="fixed", fixed="100"), set())
        self.assertIn("amount.missing_field", self.codes(kind="fixed"))
        self.assertIn("amount.unexpected_field", self.codes(kind="maximum", maximum="5", fixed="1"))
        self.assertIn("amount.range_inverted", self.codes(kind="range", minimum="9", maximum="1"))
        self.assertIn("amount.currency_required", self.codes(kind="fixed", fixed="1", currency=None))

    def test_pooled_total_is_not_a_per_student_amount(self):
        self.assertIn("amount.pooled_total_unit", self.codes(kind="pooled_total", pooled_total="50000", unit="per_student"))
        self.assertEqual(self.codes(kind="pooled_total", pooled_total="50000", unit="per_year"), set())

    def test_unknown_is_not_zero(self):
        view = describe_amount({"kind": "unspecified", "raw_text": ""})
        self.assertIn("not zero", view["interpretation"])
        self.assertFalse(view["is_per_recipient_figure"])
        self.assertFalse(describe_amount({"kind": "pooled_total"})["is_per_recipient_figure"])
        self.assertIn("not a guaranteed", describe_amount({"kind": "maximum"})["interpretation"])


class UrlPolicyTests(unittest.TestCase):
    rules = [AllowRule(("www.sac-isc.gc.ca",), ("/eng/",))]

    def test_canonicalisation_keeps_semantics(self):
        url = "HTTPS://www.sac-isc.gc.ca/eng/Abc/Detail?id=7&utm_source=x&wbdisable=true#top"
        self.assertEqual(canonicalize_url(url), "https://www.sac-isc.gc.ca/eng/Abc/Detail?id=7&wbdisable=true")
        self.assertNotEqual(canonicalize_url("https://a.org/x?id=1"), canonicalize_url("https://a.org/x?id=2"))
        with self.assertRaises(UnsafeUrlError):
            canonicalize_url("https://user:pw@a.org/")

    def test_guard(self):
        ok = check_url("https://www.sac-isc.gc.ca/eng/page", self.rules)
        self.assertTrue(ok.ok)
        for url, reason in [
            ("http://localhost/eng/", "private_hostname"),
            ("https://169.254.169.254/eng/", "private_address"),
            ("https://10.0.0.5/eng/", "private_address"),
            ("ftp://www.sac-isc.gc.ca/eng/", "scheme_not_allowed"),
            ("https://u:p@www.sac-isc.gc.ca/eng/", "credentials_in_url"),
            ("https://evil.example/eng/", "outside_allowlist"),
            ("https://www.sac-isc.gc.ca/fra/", "outside_allowlist"),
            ("https://www.sac-isc.gc.ca:8443/eng/", "port_not_allowed"),
        ]:
            with self.subTest(url=url):
                self.assertEqual(check_url(url, self.rules).reason, reason)

    def test_dns_rebinding_guard(self):
        decision = check_url("https://www.sac-isc.gc.ca/eng/x", self.rules, resolver=lambda h: ["10.1.2.3"])
        self.assertEqual(decision.reason, "dns_private_address")


class EvidenceTests(unittest.TestCase):
    def test_normalisation(self):
        self.assertEqual(normalize_text("  \u201cHi\u201d\u00a0 there \u2014 it\u2019s\n ok\u200b "), "\"Hi\" there - it's ok")

    def test_locate_quote_and_scope(self):
        text = "# Awards\n\nIntro.\n\n## Award A\n\nOpen to Métis students.\n\nDeadline: March 1."
        loc = locate_quote(text, "Open to Métis students")
        self.assertEqual((loc["paragraph_index"], loc["heading"]), (3, "Award A"))
        with self.assertRaises(QuoteNotFoundError):
            locate_quote(text, "Open to Inuit students")
        with self.assertRaises(QuoteNotFoundError):
            locate_quote(text, "Open to Métis students", paragraph_index=1)

    def test_safe_join_rejects_escapes(self):
        root = Path("/tmp/artifacts")
        for bad in ("../x", "a/../../x", "/etc/passwd", "C:\\x", "", "a\x00b"):
            with self.subTest(path=bad), self.assertRaises(PathEscapeError):
                safe_join(root, bad)
        self.assertEqual(safe_join(root, "raw/ab/x.html"), (root / "raw/ab/x.html").resolve())

    def test_evidence_ids_are_stable(self):
        self.assertEqual(evidence_id("/a", "s", "x  y"), evidence_id("/a", "s", "x y"))
        self.assertNotEqual(evidence_id("/a", "s", "x"), evidence_id("/b", "s", "x"))
        self.assertEqual(make_opportunity_id("Indspire", "Métis Award (BC)"), "indspire:metis_award_bc")


class FingerprintAndContractTests(unittest.TestCase):
    def test_fingerprint_ignores_fetch_time_and_status_but_not_facts(self):
        r = DemoEnv.get().record("demo_supported_award")
        base = compute_fingerprint(r)
        r2 = dict(r, last_fetched_at="2030-01-01T00:00:00Z", review_status="human_reviewed", last_verified_at="2030-01-01T00:00:00Z")
        self.assertEqual(base, compute_fingerprint(r2))
        r3 = DemoEnv.get().record("demo_supported_award")
        r3["cycles"][0]["amount"]["fixed"] = "9999"
        self.assertNotEqual(base, compute_fingerprint(r3))

    def test_fingerprint_is_list_order_insensitive_where_order_is_meaningless(self):
        r = DemoEnv.get().record("demo_multi_cycle_award")
        shuffled = DemoEnv.get().record("demo_multi_cycle_award")
        shuffled["cycles"].reverse()
        shuffled["evidence"].reverse()
        self.assertEqual(compute_fingerprint(r), compute_fingerprint(shuffled))

    def test_every_demo_record_satisfies_the_json_schema(self):
        schema = contract.record_schema()
        for r in DemoEnv.get().records:
            with self.subTest(id=r["id"]):
                self.assertEqual(schema_validate(r, schema), [])

    def test_schema_rejects_bad_shapes(self):
        schema = contract.record_schema()
        r = DemoEnv.get().record("demo_supported_award")
        r["extra"] = 1
        r["cycles"][0]["amount"]["kind"] = "huge"
        codes = {i.code for i in schema_validate(r, schema)}
        self.assertTrue({"schema.additional_property", "schema.enum"} <= codes)

    def test_exported_schema_file_matches_code(self):
        import json
        path = Path(__file__).resolve().parent.parent / "docs" / "schemas" / "opportunity-record-1.0.schema.json"
        self.assertTrue(path.is_file(), "run `python scripts/export_schema.py`")
        self.assertEqual(json.loads(path.read_text(encoding="utf-8")), contract.record_schema())

    def test_jsonschema_package_agrees_when_installed(self):
        try:
            from jsonschema import Draft202012Validator
        except ImportError:
            self.skipTest("jsonschema package not installed")
        validator = Draft202012Validator(contract.record_schema())
        for r in DemoEnv.get().records:
            self.assertEqual(list(validator.iter_errors(r)), [], r["id"])


if __name__ == "__main__":
    unittest.main()
