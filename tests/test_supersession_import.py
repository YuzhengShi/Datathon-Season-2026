import copy
import unittest

from navigator.ingestion.planner import plan_one
from tests.support import DemoEnv, refinger


class SupersessionImportTests(unittest.TestCase):
    def pair(self):
        existing = DemoEnv.get().record("demo_supported_award")
        incoming = copy.deepcopy(existing)
        incoming["source_record_key"] = "provider_page#the-same-award"
        return existing, refinger(incoming)

    def test_a_new_source_record_key_under_the_same_id_waits_for_a_person(self):
        existing, incoming = self.pair()
        item = plan_one(incoming, existing, expected_mode="demo")
        self.assertEqual(item.action, "pending_review")
        self.assertIn("source_record_key changed", item.reasons[0])

    def test_the_same_change_goes_through_when_this_run_registered_the_supersession(self):
        existing, incoming = self.pair()
        item = plan_one(incoming, existing, expected_mode="demo", superseding=frozenset({existing["id"]}))
        self.assertEqual(item.action, "updated")
        self.assertEqual(item.record["source_record_key"], "provider_page#the-same-award")

    def test_registering_one_id_does_not_free_another(self):
        existing, incoming = self.pair()
        item = plan_one(incoming, existing, expected_mode="demo", superseding=frozenset({"some_other_id"}))
        self.assertEqual(item.action, "pending_review")


if __name__ == "__main__":
    unittest.main()
