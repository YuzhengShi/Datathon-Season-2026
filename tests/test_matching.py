import json
import unittest
from pathlib import Path

from navigator.core.timeutil import parse_as_of
from navigator.matching.availability import cycle_availability, select_cycle
from navigator.matching.engine import MatchOptions, evaluate_record, match_records
from navigator.matching.rules import evaluate_eligibility, parse_eligibility
from navigator.reference import load_institutions
from tests.support import AS_OF, DemoEnv

INSTITUTIONS = load_institutions(Path(__file__).resolve().parent.parent / "data" / "reference" / "institutions.yaml")
ALL_ID = ["first_nations", "inuit", "metis"]


def ev(raw_mandatory, profile, preferences=()):
    elig, issues = parse_eligibility(
        {"mandatory": raw_mandatory, "preferences": list(preferences), "unstructured": []}, "/e"
    )
    assert elig is not None, issues
    return evaluate_eligibility(elig, profile)


def pr(field, op, value, **kw):
    return {"type": "predicate", "field": field, "op": op, "value": value, "evidence_ids": ["e"], **kw}


def run(rid, profile, *, as_of=AS_OF, cycle_key=None, **opts):
    record = DemoEnv.get().record(rid)
    options = MatchOptions(as_of=as_of, cycle_key=cycle_key, include_closed=True, **opts)
    return evaluate_record(record, profile, options, INSTITUTIONS.resolve)


def match_all(profile, **kw):
    options = MatchOptions(as_of=kw.pop("as_of", AS_OF), limit=100, **kw)
    return match_records(DemoEnv.get().all_records(), profile, options, INSTITUTIONS.resolve, data_mode="demo")


class ThreeValuedLogicTests(unittest.TestCase):
    def test_all_any_truth_tables(self):
        t, f, u = (
            pr("institution_id", "eq", "a"),
            pr("institution_id", "eq", "b"),
            {"type": "unknown", "reason": "local"},
        )
        profile = {"institution_id": "a"}  # t true, f false
        cases = [
            ({"type": "all", "children": [t, t]}, True),
            ({"type": "all", "children": [t, f]}, False),
            ({"type": "all", "children": [t, u]}, None),
            ({"type": "all", "children": [f, u]}, False),
            ({"type": "any", "children": [f, f]}, False),
            ({"type": "any", "children": [f, t]}, True),
            ({"type": "any", "children": [f, u]}, None),
            ({"type": "any", "children": [t, u]}, True),
        ]
        for node, expected in cases:
            with self.subTest(node=node["type"], children=[c["type"] + str(c.get("value")) for c in node["children"]]):
                self.assertIs(ev([node], profile).value, expected)

    def test_empty_groups_and_empty_rules_never_pass(self):
        for node in ({"type": "all", "children": []}, {"type": "any", "children": []}):
            elig, issues = parse_eligibility({"mandatory": [node], "preferences": [], "unstructured": []}, "/e")
            self.assertIsNone(elig)
            self.assertEqual(issues[0].code, "rule.empty_group")
        out = ev([], {"institution_id": "a"})
        self.assertIsNone(out.value)  # no recorded rules: unknown, not "eligible"

    def test_whitelist_only(self):
        for bad in (pr("password", "eq", "x"), pr("institution_id", "regex", ".*"), pr("gpa", "gte", "3.0")):
            elig, issues = parse_eligibility({"mandatory": [bad], "preferences": [], "unstructured": []}, "/e")
            self.assertIsNone(elig, bad)
            self.assertTrue(issues)

    def test_gpa_requires_matching_scale(self):
        node = pr("gpa", "gte", "3.0", scale="4.0")
        self.assertIs(ev([node], {"gpa": "3.5", "gpa_scale": "4.0"}).value, True)
        self.assertIs(ev([node], {"gpa": "2.5", "gpa_scale": "4.0"}).value, False)
        mismatch = ev([node], {"gpa": "3.9", "gpa_scale": "4.3"})
        self.assertIsNone(mismatch.value)
        self.assertEqual(mismatch.unknown[0].reason_kind, "profile_scale_mismatch")
        self.assertEqual(ev([node], {"gpa": "3.5"}).unknown[0].missing_fields, ("gpa_scale",))

    def test_soft_text_is_never_a_hard_fail(self):
        out = ev([pr("home_community", "in", ["Demo First Nation"])], {"home_community": "Demo First Nations Band"})
        self.assertIsNone(out.value)
        self.assertEqual(out.unknown[0].reason_kind, "mapping_ambiguous")
        self.assertIs(
            ev([pr("home_community", "in", ["Demo First Nation"])], {"home_community": " demo  first nation "}).value,
            True,
        )

    def test_preferences_never_disqualify(self):
        mandatory = [pr("education_level", "eq", "undergraduate")]
        pref = [pr("program_field", "in", ["environmental science"])]
        self.assertEqual(
            len(
                ev(
                    mandatory, {"education_level": "undergraduate", "program_field": "Environmental Science"}, pref
                ).preference_matches
            ),
            1,
        )
        miss = ev(mandatory, {"education_level": "undergraduate", "program_field": "History"}, pref)
        self.assertIs(miss.value, True)
        self.assertEqual(miss.preference_matches, [])


class DemoCaseTests(unittest.TestCase):
    """The twelve required situations, evaluated through the real matching engine."""

    P_OK = {"indigenous_identity": ["metis"], "institution_id": "demo_college", "education_level": "undergraduate"}

    def test_1_supported_award(self):
        item = run("demo_supported_award", self.P_OK)
        self.assertEqual((item["eligibility_result"], item["match_status"]), ("pass", "potential_fit"))
        self.assertEqual(item["availability_status"], "open")
        self.assertGreaterEqual(len(item["passed_rules"]), 3)
        self.assertTrue(all(ref["quote"] for ref in item["evidence_refs"]))
        self.assertNotIn("probability", json.dumps(item).lower())

    def test_2_clarification_award(self):
        item = run("demo_clarification_award", self.P_OK)
        self.assertEqual(item["match_status"], "needs_information")
        self.assertEqual(item["missing_profile_fields"], ["study_status"])
        self.assertTrue(any("full-time" in q for q in item["clarification_questions"]))
        full = run("demo_clarification_award", {**self.P_OK, "study_status": "full_time"})
        self.assertEqual(full["match_status"], "potential_fit")
        part = run("demo_clarification_award", {**self.P_OK, "study_status": "part_time"})
        self.assertEqual(part["match_status"], "not_eligible")

    def test_3_shared_application_and_independent_exception(self):
        profile = {"indigenous_identity": ["inuit"], "residence_province": "BC", "education_level": "undergraduate"}
        out = match_all(profile, group_by_application=True)
        groups = {g["group_id"]: g for g in out["groups"]}
        shared = groups["demo_foundation_shared_form"]
        statuses = {m["opportunity_id"]: m["match_status"] for m in shared["members"]}
        self.assertEqual(
            statuses, {"demo_shared_application_a": "potential_fit", "demo_shared_application_b": "not_eligible"}
        )
        self.assertIn("share one application form", shared["notice"])  # one member fitting is not "all fit"
        exception = next(
            g for g in out["groups"] if g["members"][0]["opportunity_id"] == "demo_shared_application_exception"
        )
        self.assertIsNone(exception["group_id"])
        self.assertEqual(len(exception["members"]), 1)
        self.assertEqual(out["total_groups"], len(out["groups"]))

    def test_4_identity_specific_conditions_need_more_than_broad_identity(self):
        fn = "demo_first_nations_registered_award"
        broad = {"indigenous_identity": ["first_nations"]}
        self.assertEqual(run(fn, broad)["match_status"], "needs_information")
        self.assertIn("first_nations_registered", run(fn, broad)["missing_profile_fields"])
        self.assertEqual(run(fn, {**broad, "first_nations_registered": False})["match_status"], "not_eligible")
        self.assertEqual(run(fn, {**broad, "first_nations_registered": True})["match_status"], "potential_fit")
        metis = "demo_metis_citizen_award"
        self.assertEqual(run(metis, {"indigenous_identity": ["metis"]})["match_status"], "needs_information")
        self.assertEqual(
            run(metis, {"metis_citizen": True, "metis_org": "Demo Métis Authority"})["match_status"], "potential_fit"
        )
        self.assertEqual(
            run(metis, {"metis_citizen": True, "metis_org": "Some Other Nation"})["match_status"],
            "needs_provider_confirmation",
        )
        self.assertEqual(run(metis, {"metis_citizen": False})["match_status"], "not_eligible")
        inuit = "demo_inuit_beneficiary_award"
        self.assertEqual(run(inuit, {"indigenous_identity": ["inuit"]})["match_status"], "needs_information")
        self.assertEqual(run(inuit, {"inuit_beneficiary": True})["match_status"], "potential_fit")

    def test_5_residence_home_community_and_school_province_are_separate(self):
        rid = "demo_residence_community_award"
        ok = {"residence_province": "BC", "home_community": "Demo First Nation", "institution_province": "AB"}
        self.assertEqual(run(rid, ok)["match_status"], "potential_fit")
        swapped = {"residence_province": "AB", "home_community": "Demo First Nation", "institution_province": "BC"}
        self.assertEqual(run(rid, swapped)["match_status"], "not_eligible")  # fields must not be mixed up
        item = run(rid, {"residence_province": "BC", "institution_province": "AB"})
        self.assertEqual(item["match_status"], "needs_information")
        self.assertEqual(item["missing_profile_fields"], ["home_community"])

    def test_6_preference_is_not_a_requirement(self):
        base = {"indigenous_identity": ["inuit"], "education_level": "undergraduate"}
        plain = run("demo_preference_award", base)
        self.assertEqual((plain["match_status"], plain["preference_matches"]), ("potential_fit", []))
        better = run("demo_preference_award", {**base, "program_field": "environmental science"})
        self.assertEqual(len(better["preference_matches"]), 1)
        other = run("demo_preference_award", {**base, "program_field": "history"})
        self.assertEqual(other["match_status"], "potential_fit")

    def test_7_or_rule(self):
        rid = "demo_or_rule_award"
        ident = {"indigenous_identity": ["metis"]}
        self.assertEqual(
            run(rid, {**ident, "home_community": "Demo First Nation", "institution_id": "other"})["match_status"],
            "potential_fit",
        )
        self.assertEqual(run(rid, {**ident, "institution_id": "demo_college"})["match_status"], "potential_fit")
        # false + unknown(profile) => unknown, and the student can fix it by answering
        self.assertEqual(run(rid, {**ident, "institution_id": "other"})["match_status"], "needs_information")
        # false + unknown(mapping) => provider must confirm
        self.assertEqual(
            run(rid, {**ident, "institution_id": "other", "home_community": "Elsewhere"})["match_status"],
            "needs_provider_confirmation",
        )
        unknown_branch = "demo_or_unknown_branch_award"
        self.assertEqual(
            run(unknown_branch, {**ident, "institution_id": "demo_college"})["match_status"], "potential_fit"
        )
        self.assertEqual(
            run(unknown_branch, {**ident, "institution_id": "other"})["match_status"], "needs_provider_confirmation"
        )
        self.assertIs(
            ev(
                [{"type": "any", "children": [pr("institution_id", "eq", "a"), pr("institution_id", "eq", "b")]}],
                {"institution_id": "c"},
            ).value,
            False,
        )

    def test_8_amounts_are_not_personal_figures(self):
        unknown = run("demo_amount_unknown_award", self.P_OK)["amount"]
        self.assertEqual(unknown["kind"], "unspecified")
        self.assertIn("not zero", unknown["interpretation"])
        self.assertNotIn("fixed", unknown)
        pooled = run("demo_pooled_total_award", self.P_OK)["amount"]
        self.assertEqual(
            (pooled["kind"], pooled["pooled_total"], pooled["is_per_recipient_figure"]),
            ("pooled_total", "50000", False),
        )
        self.assertIn("not an amount any one student gets", pooled["interpretation"])
        cap = run("demo_maximum_award", self.P_OK)["amount"]
        self.assertFalse(cap["is_per_recipient_figure"])
        self.assertIn("not a guaranteed", cap["interpretation"])
        self.assertTrue(all(not a["personal_benefit_estimated"] for a in (unknown, pooled, cap)))

    def test_9_deadline_kinds(self):
        old = run("demo_deadline_2020_award", self.P_OK)
        self.assertEqual(
            (old["availability_status"], old["match_status"]), ("closed", "potential_fit")
        )  # closed != ineligible
        self.assertIn("historical_cycle_only", old["freshness_flags"])
        annual = run("demo_annual_rule_award", self.P_OK)
        self.assertEqual(annual["availability_status"], "unknown")
        self.assertEqual(annual["deadlines"][0]["closing"]["state"], "unresolved")
        self.assertIn("annual_rule_unconfirmed", annual["freshness_flags"])
        self.assertIsNone(annual["deadlines"][0].get("date"))  # month/day never invented into a date
        rounds = run("demo_multi_deadline_award", self.P_OK)
        self.assertEqual(len(rounds["deadlines"]), 2)  # two consideration rounds, still ONE item
        self.assertEqual(
            sum(1 for i in match_all(self.P_OK)["results"] if i["opportunity_id"] == "demo_multi_deadline_award"), 1
        )
        local = run("demo_local_admin_deadline_award", self.P_OK)
        self.assertEqual(local["availability_status"], "contact_administrator")

    def test_10_timezones(self):
        unknown_tz = "demo_tz_unknown_award"
        item = run(unknown_tz, self.P_OK)
        self.assertEqual(item["availability_status"], "open")
        self.assertIn("timezone_unknown", item["availability"] and item["freshness_flags"])
        self.assertEqual(
            run(unknown_tz, self.P_OK, as_of=parse_as_of("2026-10-10T00:00:00Z"))["availability_status"], "open"
        )  # not closed early
        self.assertEqual(
            run(unknown_tz, self.P_OK, as_of=parse_as_of("2026-10-10T06:00:00Z"))["availability_status"], "closed"
        )
        dst = run("demo_tz_dst_boundary_award", self.P_OK)["deadlines"][0]["closing"]
        self.assertEqual((dst["earliest_utc"], dst["latest_utc"]), ("2026-11-01T05:31:00Z", "2026-11-01T06:31:00Z"))
        self.assertIn("dst_repeated_local_time", dst["flags"])
        day = "demo_date_only_deadline_award"
        self.assertEqual(
            run(day, self.P_OK, as_of=parse_as_of("2026-10-07T20:00:00Z"))["availability_status"], "open"
        )  # same day
        self.assertEqual(
            run(day, self.P_OK, as_of=parse_as_of("2026-10-08T08:00:00Z"))["availability_status"], "closed"
        )

    def test_12_funding_channel_with_thin_rules(self):
        item = run("demo_funding_channel", self.P_OK)
        self.assertEqual(item["match_status"], "needs_provider_confirmation")
        self.assertEqual(item["application_route"]["contact_url"], "https://demo.invalid/regional/contact")
        self.assertIn("Contact them via", item["next_action"])
        self.assertTrue(item["source_uncertainties"])


class FunderSideTests(unittest.TestCase):
    def test_conditions_on_the_funds_recipient_never_decide_the_students_result(self):
        for profile in (
            {},
            {"indigenous_identity": ["metis"], "institution_id": "demo_college"},
            {"indigenous_identity": ["inuit"], "residence_province": "ON", "education_level": "doctoral"},
        ):
            item = run("demo_funding_channel", profile)
            self.assertEqual(item["match_status"], "needs_provider_confirmation")
            self.assertEqual(item["failed_rules"], [])
            self.assertEqual(len(item["funder_side_conditions"]), 1)
            self.assertIn("annual education plan", item["funder_side_conditions"][0]["text"])
            self.assertTrue(
                any(
                    "No structured eligibility rules" in r["rule"] or "locally" in r["rule"]
                    for r in item["unknown_rules"]
                )
            )
            quoted = {ref["quote"] for ref in item["evidence_refs"]}
            self.assertTrue(any("annual education plan" in q for q in quoted))  # the funder-side evidence is shown too

    def test_ordinary_awards_have_no_funder_side_conditions(self):
        self.assertEqual(run("demo_supported_award", DemoCaseTests.P_OK)["funder_side_conditions"], [])


class ListingBehaviourTests(unittest.TestCase):
    P = {"indigenous_identity": ["metis"], "institution_id": "demo_college", "education_level": "undergraduate"}

    def test_collections_are_navigation_only(self):
        ids = {i["opportunity_id"] for i in match_all(self.P)["results"]}
        self.assertNotIn("demo_award_collection", ids)

    def test_closed_is_hidden_by_default_and_counted(self):
        out = match_all(self.P)
        self.assertEqual(out["excluded_closed_count"], 1)
        shown = match_all(self.P, include_closed=True)
        self.assertEqual(shown["total"], out["total"] + 1)

    def test_sorted_paginated_and_deterministic(self):
        a, b = match_all(self.P)["results"], match_all(self.P)["results"]
        self.assertEqual([i["opportunity_id"] for i in a], [i["opportunity_id"] for i in b])
        rank = {"potential_fit": 0, "needs_information": 1, "needs_provider_confirmation": 2, "not_eligible": 3}
        ranks = [rank[i["match_status"]] for i in a]
        self.assertEqual(ranks, sorted(ranks))
        page = (
            match_all(self.P, limit=5, offset=5)
            if False
            else match_records(
                DemoEnv.get().all_records(),
                self.P,
                MatchOptions(as_of=AS_OF, limit=5, offset=5),
                None,
                data_mode="demo",
            )
        )
        self.assertEqual([i["opportunity_id"] for i in page["results"]], [i["opportunity_id"] for i in a[5:10]])
        self.assertEqual(page["total"], len(a))

    def test_response_never_echoes_the_profile(self):
        secret = {"indigenous_identity": ["metis"], "home_community": "ZZ-UNIQUE-COMMUNITY-NAME"}
        self.assertNotIn("ZZ-UNIQUE-COMMUNITY-NAME", json.dumps(match_all(secret)))

    def test_cycle_selection(self):
        record = DemoEnv.get().record("demo_multi_cycle_award")
        cycle, avail = select_cycle(record, AS_OF)
        self.assertEqual((cycle["cycle_key"], avail["status"]), ("2026-27", "open"))
        old, old_avail = select_cycle(record, AS_OF, "2019-20")
        self.assertEqual((old["cycle_key"], old_avail["status"]), ("2019-20", "closed"))
        self.assertEqual(select_cycle(record, AS_OF, "1999"), (None, None))

    def test_availability_requires_a_verifiable_window(self):
        future = {
            "cycle_key": "x",
            "deadlines": [
                {
                    "kind": "date",
                    "date": "2027-01-01",
                    "timezone": "Pacific Time",
                    "raw_text": "",
                    "precision": "day",
                    "evidence_ids": [],
                }
            ],
        }
        self.assertEqual(
            cycle_availability(future, AS_OF)["status"], "unknown"
        )  # a future deadline alone is not "open"
        self.assertEqual(cycle_availability({**future, "starts_on": "2026-09-01"}, AS_OF)["status"], "open")
        self.assertEqual(cycle_availability({**future, "starts_on": "2027-01-01"}, AS_OF)["status"], "upcoming")


if __name__ == "__main__":
    unittest.main()
