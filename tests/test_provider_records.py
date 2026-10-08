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
