"""Tests that use the REAL network. Off by default; opt in with NAVIGATOR_LIVE_TESTS=1 and `pytest -m live`.

They only touch ``example.com``, the domain IANA reserves for documentation and testing - never a funding source.
"""

import os
import unittest

import pytest

from navigator.core.urlpolicy import AllowRule

LIVE = os.environ.get("NAVIGATOR_LIVE_TESTS") == "1"


@pytest.mark.live
@unittest.skipUnless(LIVE, "set NAVIGATOR_LIVE_TESTS=1 to run tests that use the real network")
class RealNetworkTests(unittest.TestCase):
    def fetcher(self):
        from navigator.ingestion.fetcher import Fetcher, FetchPolicy
        from navigator.ingestion.http_transport import HttpxTransport, system_resolver

        policy = FetchPolicy(
            "IndigenousFundingNavigatorBot/0.1 (automated test; reserved demo domain only)",
            timeout=20.0,
            retries=1,
            min_interval=1.0,
        )
        return Fetcher(HttpxTransport(), policy, resolver=system_resolver)

    def test_a_reserved_demo_domain_end_to_end(self):
        outcome = self.fetcher().fetch("https://example.com/", [AllowRule(("example.com",), ("/",))])
        self.assertEqual(outcome.outcome, "ok", outcome.reason)
        self.assertEqual(outcome.media_type, "text/html")
        self.assertIn(b"Example Domain", outcome.body or b"")
        self.assertIn(outcome.robots_status, {"present", "not_found"})  # robots.txt really was consulted
        self.assertEqual(outcome.status, 200)

    def test_private_targets_are_refused_with_the_real_resolver(self):
        fetcher = self.fetcher()
        for url, reason in (
            ("http://127.0.0.1/", "url_private_address"),
            ("http://localhost/", "url_private_hostname"),
            ("http://169.254.169.254/latest/meta-data/", "url_private_address"),
        ):
            outcome = fetcher.fetch(url, [AllowRule(("127.0.0.1", "localhost", "169.254.169.254"), ("/",))])
            self.assertEqual((outcome.outcome, outcome.reason), ("blocked", reason), url)

    def test_a_path_outside_the_allowlist_is_never_requested(self):
        outcome = self.fetcher().fetch("https://example.com/other", [AllowRule(("example.com",), ("/allowed/",))])
        self.assertEqual((outcome.outcome, outcome.reason), ("blocked", "url_outside_allowlist"))


if __name__ == "__main__":
    unittest.main()
