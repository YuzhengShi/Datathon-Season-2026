import unittest
from pathlib import Path

from navigator.config import DEFAULTS
from navigator.services.live import checked_user_agent

ROOT = Path(__file__).resolve().parent.parent


class UserAgentTests(unittest.TestCase):
    def test_the_default_says_what_the_crawler_is_for(self):
        default = DEFAULTS["USER_AGENT"]
        for phrase in ("non-commercial", "Indigenous students", "robots.txt"):
            self.assertIn(phrase, default)

    def test_a_missing_contact_is_reported(self):
        with self.assertLogs("navigator.services.live", level="WARNING"):
            checked_user_agent(DEFAULTS["USER_AGENT"])
        with self.assertLogs("navigator.services.live", level="WARNING"):
            checked_user_agent("Bot/1.0 (contact: YOUR-EMAIL@example.org)")

    def test_a_contact_address_or_page_passes_silently_and_is_sent_unchanged(self):
        for agent in ("Bot/1.0 (contact: team@example.org)", "Bot/1.0 (+https://example.org/about-the-bot)"):
            with self.assertNoLogs("navigator.services.live", level="WARNING"):
                self.assertEqual(checked_user_agent(agent), agent)

    def test_the_example_env_file_shows_the_pattern(self):
        text = (ROOT / ".env.example").read_text(encoding="utf-8")
        self.assertIn("non-commercial project that helps Indigenous students", text)
        self.assertIn("contact: YOUR-EMAIL", text)


if __name__ == "__main__":
    unittest.main()
