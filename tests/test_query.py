import unittest

from navigator.services.query import applicability, list_opportunities, opportunity_detail, public_record
from tests.support import AS_OF, DemoEnv


def listing(**kw):
    return list_opportunities(DemoEnv.get().all_records(), as_of=kw.pop("as_of", AS_OF), freshness_days=30,
                              data_mode="demo", limit=kw.pop("limit", 100), **kw)


def ids(out):
    return [r["id"] for r in out["results"]]


class ListingTests(unittest.TestCase):
    def test_defaults_hide_collections_and_closed_records(self):
        out = listing()
        self.assertNotIn("demo_award_collection", ids(out))
        self.assertNotIn("demo_deadline_2020_award", ids(out))
        self.assertEqual((out["total"], out["count"], out["data_mode"]), (23, 23, "demo"))

    def test_explicit_type_and_include_closed(self):
        self.assertEqual(ids(listing(opportunity_type="award_collection")), ["demo_award_collection"])
        self.assertEqual(ids(listing(opportunity_type="funding_channel")), ["demo_funding_channel"])
        self.assertIn("demo_deadline_2020_award", ids(listing(include_closed=True)))

    def test_text_search_is_case_and_accent_insensitive_and_all_terms(self):
        self.assertEqual(ids(listing(q="métis citizenship")), ["demo_metis_citizen_award"])
        self.assertEqual(ids(listing(q="METIS  citizenship")), ["demo_metis_citizen_award"])  # accents/case/spacing ignored
        self.assertIn("demo_supported_award", ids(listing(q="supported")))
        self.assertEqual(ids(listing(q="no-such-thing")), [])

    def test_unknown_applicability_is_not_treated_as_not_applicable(self):
        out = listing(province="ON")
        shown = set(ids(out))
        self.assertIn("demo_supported_award", shown)  # no recorded province rule -> unknown -> still listed
        self.assertNotIn("demo_shared_application_a", shown)  # only BC/YT residents: recorded as not applicable
        self.assertNotIn("demo_residence_community_award", shown)
        row = next(r for r in out["results"] if r["id"] == "demo_supported_award")
        self.assertEqual(row["applicability"]["province"], "unknown")
        strict = set(ids(listing(province="BC", exclude_unknown_applicability=True)))
        self.assertIn("demo_shared_application_a", strict)
        self.assertNotIn("demo_supported_award", strict)

    def test_education_level_filter(self):
        shown = set(ids(listing(education_level="college")))
        self.assertIn("demo_shared_application_b", shown)
        self.assertNotIn("demo_supported_award", shown)  # undergraduate only
        self.assertIn("demo_amount_unknown_award", shown)  # no level rule -> unknown -> listed

    def test_applicability_helper(self):
        cycle = DemoEnv.get().record("demo_shared_application_a")["cycles"][0]
        self.assertEqual(applicability(cycle, ("residence_province",), "BC"), "applies")
        self.assertEqual(applicability(cycle, ("residence_province",), "ON"), "not_applicable")
        self.assertEqual(applicability(cycle, ("campus",), "x"), "unknown")

    def test_stable_sort_and_pagination(self):
        full = ids(listing())
        self.assertEqual(full, ids(listing()))
        self.assertEqual(ids(listing(limit=5, offset=5)), full[5:10])
        page = listing(limit=5, offset=20)
        self.assertEqual((page["count"], page["total"]), (3, 23))
        out = listing()
        ranks = [{"open": 0, "upcoming": 1, "contact_administrator": 2, "unknown": 3, "closed": 4}[r["current_cycle"]["availability_status"]]
                 for r in out["results"]]
        self.assertEqual(ranks, sorted(ranks))

    def test_listing_rows_carry_amount_guidance_and_flags(self):
        row = next(r for r in listing()["results"] if r["id"] == "demo_pooled_total_award")
        self.assertFalse(row["current_cycle"]["amount"]["is_per_recipient_figure"])
        self.assertIsInstance(row["freshness_flags"], list)

    def test_only_published_records_are_listed(self):
        records = DemoEnv.get().all_records()
        records[0]["publication_status"] = "draft"
        out = list_opportunities(records, as_of=AS_OF, freshness_days=30, data_mode="demo", limit=100)
        self.assertNotIn(records[0]["id"], ids(out))


class DetailTests(unittest.TestCase):
    def test_detail_hides_storage_paths_and_explains_next_steps(self):
        env = DemoEnv.get()
        out = opportunity_detail(env.record("demo_supported_award"), env.all_records(), as_of=AS_OF, freshness_days=30, data_mode="demo")
        refs = out["opportunity"]["source_refs"]
        self.assertTrue(all("raw_path" not in r and "text_path" not in r for r in refs))
        self.assertIn("raw_path", env.record("demo_supported_award")["source_refs"][0])  # the export keeps them
        self.assertTrue(any(s.startswith("Apply here:") for s in out["next_steps"]))
        self.assertTrue(any(s.startswith("Prepare:") for s in out["next_steps"]))
        self.assertIn("not human review", out["verification"]["note"])
        self.assertEqual(out["current_cycle_key"], "2026-27")

    def test_shared_application_siblings_and_cycles(self):
        env = DemoEnv.get()
        out = opportunity_detail(env.record("demo_shared_application_a"), env.all_records(), as_of=AS_OF, freshness_days=30, data_mode="demo")
        self.assertEqual([s["id"] for s in out["shared_application_with"]], ["demo_shared_application_b"])
        multi = opportunity_detail(env.record("demo_multi_cycle_award"), env.all_records(), as_of=AS_OF, freshness_days=30, data_mode="demo")
        self.assertEqual({c["cycle_key"]: c["availability"]["status"] for c in multi["cycles"]}, {"2019-20": "closed", "2026-27": "open"})

    def test_public_record_does_not_mutate_the_original(self):
        record = DemoEnv.get().record("demo_supported_award")
        public_record(record)
        self.assertIn("raw_path", record["source_refs"][0])


if __name__ == "__main__":
    unittest.main()
