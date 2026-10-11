import unittest

from navigator.services.live import prefer_provider_records


def rec(rid, method, source="s"):
    return {"id": rid, "title": rid.upper(), "extraction_method": method, "source_refs": [{"source_id": source}]}


class ProviderRecordTests(unittest.TestCase):
    def test_the_provider_page_record_replaces_the_directory_record_with_the_same_id(self):
        directory, provider = rec("a:x", "deterministic_adapter", "isc"), rec("a:x", "curated", "prov_a")
        other = rec("b:y", "deterministic_adapter", "isc")
        kept, replaced = prefer_provider_records([directory, other, provider])
        self.assertEqual([r["id"] for r in kept], ["b:y", "a:x"])
        self.assertIs(kept[1], provider)
        self.assertEqual(replaced, [(directory, provider)])

    def test_the_same_title_with_a_matching_provider_is_one_opportunity_even_under_another_id(self):
        directory = {
            "id": "isc_edu:isc_metis_x",
            "title": "M\u00e9tis Nation Post-Secondary Education Strategy",
            "extraction_method": "deterministic_adapter",
            "provider": {"name": "Indigenous Services Canada \u2013 Education Branch"},
        }
        curated = {
            "id": "isc:metis_x",
            "title": "Metis Nation Post-Secondary Education Strategy",
            "extraction_method": "curated",
            "provider": {"name": "Indigenous Services Canada"},
        }
        kept, replaced = prefer_provider_records([directory, curated])
        self.assertEqual((kept, replaced), ([curated], [(directory, curated)]))

    def test_a_title_alone_is_not_enough_to_call_two_records_one_opportunity(self):
        directory = {
            "id": "a:x",
            "title": "Indigenous Bursary",
            "extraction_method": "deterministic_adapter",
            "provider": {"name": "Some College"},
        }
        curated = {
            "id": "b:y",
            "title": "Indigenous Bursary",
            "extraction_method": "curated",
            "provider": {"name": "Other University"},
        }
        self.assertEqual(prefer_provider_records([directory, curated]), ([directory, curated], []))

    def test_nothing_is_replaced_without_a_curated_twin(self):
        records = [rec("a:x", "deterministic_adapter"), rec("b:y", "curated")]
        kept, replaced = prefer_provider_records(records)
        self.assertEqual((kept, replaced), (records, []))

    def test_duplicates_of_the_same_kind_are_left_for_the_planner_to_reject(self):
        same = [rec("a:x", "deterministic_adapter"), rec("a:x", "deterministic_adapter")]
        self.assertEqual(prefer_provider_records(same), (same, []))
        two_curated = [rec("a:x", "curated", "one"), rec("a:x", "curated", "two")]
        self.assertEqual(prefer_provider_records(two_curated), (two_curated, []))


if __name__ == "__main__":
    unittest.main()
