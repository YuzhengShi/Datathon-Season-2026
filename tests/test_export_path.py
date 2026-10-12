"""One complete path: prepared dataset -> database -> the API the web app calls -> what a student sees, compared with the data.

The dataset is loaded WITHOUT the saved source pages (--trust-export), exactly as in a fresh clone of the repository.
"""

import json
import shutil
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path

from tests.support import isolated_runtime, requires_web_stack

ROOT = Path(__file__).resolve().parent.parent
EXPORT = ROOT / "data" / "awards.jsonl"


def dataset_moment(path: Path) -> str:
    """The latest time the dataset itself states (fetched or verified). The tests run "as of" that moment, so a dataset that
    was refreshed later never looks like it comes from the future (validation rejects timestamps after as-of)."""
    stamps = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            record = json.loads(line)
            stamps += [record.get("last_fetched_at"), record.get("last_verified_at")]
    return max(s for s in stamps if s)


AS_OF = dataset_moment(EXPORT) if EXPORT.is_file() else "2026-10-08T12:00:00Z"
PROFILE = {
    "indigenous_identity": ["first_nations"],
    "first_nations_registered": True,
    "residence_province": "BC",
    "education_level": "undergraduate",
    "study_status": "full_time",
    "institution_id": "sfu",
    "institution_province": "BC",
}


@requires_web_stack
@unittest.skipUnless(EXPORT.is_file(), "the prepared dataset is not in this checkout")
class ExportPathTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from fastapi.testclient import TestClient
        from typer.testing import CliRunner

        from navigator.api.app import create_app
        from navigator.cli import app as cli

        cls.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        tmp = Path(cls.tmp.name)
        (tmp / "reference").mkdir()
        shutil.copy(ROOT / "data" / "reference" / "institutions.yaml", tmp / "reference")
        cls.rt = isolated_runtime(cls.tmp.name, "live", SOURCE_CONFIG=str(ROOT / "sources.yaml"))
        env = {
            "DATA_DIR": cls.tmp.name,
            "DATA_MODE": "live",
            "DATABASE_URL": cls.rt.database_url,
            "SOURCE_CONFIG": str(ROOT / "sources.yaml"),
        }
        runner = CliRunner()
        up = runner.invoke(cli, ["db", "upgrade", "--mode", "live"], env=env)
        assert up.exit_code == 0, up.output
        cls.load = runner.invoke(
            cli,
            [
                "import-data",
                "--input",
                str(EXPORT),
                "--artifact-root",
                cls.tmp.name,
                "--mode",
                "live",
                "--trust-export",
                "--as-of",
                AS_OF,
            ],
            env=env,
        )
        cls.app = create_app(cls.rt)
        cls.client = TestClient(cls.app)
        cls.export = [json.loads(line) for line in EXPORT.read_text(encoding="utf-8").splitlines() if line.strip()]

    @classmethod
    def tearDownClass(cls):
        cls.app.state.engine.dispose()
        cls.tmp.cleanup()

    def pages(self, fetch):
        """Every result of a paged endpoint (at most 100 per page)."""
        out, offset = [], 0
        while True:
            batch = fetch(offset)
            out += batch
            if len(batch) < 100:
                return out
            offset += 100

    def listing(self):
        rows = self.pages(
            lambda offset: self.client.get(f"/opportunities?limit=100&offset={offset}&as_of={AS_OF}").json()["results"]
        )
        return {item["id"]: item for item in rows}

    def matches(self, profile):
        return self.pages(
            lambda offset: self.client.post(
                "/match", json={"profile": profile, "limit": 100, "offset": offset, "as_of": AS_OF}
            ).json()["results"]
        )

    def test_the_dataset_loads_without_the_saved_pages(self):
        self.assertEqual(self.load.exit_code, 0, self.load.output[-1500:])
        self.assertEqual(len(self.listing()), len(self.export))

    def test_what_the_api_serves_is_what_the_dataset_says(self):
        served = self.listing()
        for record in self.export:
            item = served[record["id"]]
            self.assertEqual(item["title"], record["title"])
            self.assertEqual(item["official_url"], record["official_url"], record["id"])
            self.assertEqual(item["provider"]["name"], record["provider"]["name"])
            amount, shown = record["cycles"][0]["amount"], item["current_cycle"]["amount"]
            self.assertEqual(shown["kind"], amount["kind"], record["id"])
            for key in ("fixed", "maximum", "minimum"):
                if amount.get(key) is not None:
                    self.assertEqual(Decimal(str(shown[key])), Decimal(str(amount[key])), f"{record['id']} {key}")

    def test_every_amount_and_date_shown_is_in_the_quote_that_supports_it(self):
        checked = 0
        for record in self.export:
            quotes = {e["id"]: e["quote"] for e in record["evidence"]}
            for cycle in record["cycles"]:
                amount = cycle["amount"]
                for key in ("fixed", "maximum"):
                    if amount.get(key):
                        value = int(Decimal(str(amount[key])))
                        said = " ".join(quotes[i] for i in amount["evidence_ids"])
                        self.assertTrue(
                            f"{value:,}" in said or str(value) in said,
                            f"{record['id']}: ${value} is not in its quote {said!r}",
                        )
                        checked += 1
                for deadline in cycle["deadlines"]:
                    said = " ".join(quotes[i] for i in deadline.get("evidence_ids", []))
                    if deadline["kind"] == "date":
                        self.assertIn(
                            str(int(deadline["date"][8:10])), said, f"{record['id']}: day of {deadline['date']}"
                        )
                        self.assertIn(deadline["date"][:4], said, f"{record['id']}: year of {deadline['date']}")
                        checked += 1
                    if deadline["kind"] == "annual_rule":
                        self.assertIn(str(deadline["annual_day"]), said, f"{record['id']}: day of the yearly deadline")
                        checked += 1
        self.assertGreater(checked, 60, "the check must have looked at real amounts and dates")

    def test_the_demo_student_sees_what_the_data_supports(self):
        rows = self.matches(PROFILE)
        self.assertEqual(len(rows), len(self.export))
        results = {}
        for r in rows:
            results.setdefault(
                r["title"], r
            )  # a few directory titles are used by two providers; the ones checked below are not
        self.assertEqual(
            results["Phyllis Webstad Award for Indigenous Students"]["match_status"], "needs_provider_confirmation"
        )
        self.assertEqual(
            results["Laura Finch Memorial Scholarship"]["match_status"],
            "not_eligible",
            "a VIU award is for VIU students",
        )
        self.assertEqual(
            results["MNBC STEPS - Education and Skills Training Funding"]["match_status"],
            "not_eligible",
            "MNBC STEPS is for Métis citizens",
        )
        self.assertEqual(results["Nutrien Indigenous Youth Financial Management Awards"]["availability_status"], "open")
        cummins = next(r for r in self.export if r["title"].startswith("Cummins"))
        self.assertEqual(
            cummins["cycles"][0]["amount"]["fixed"], "1000", "the provider's page replaced the directory's $500"
        )

    def test_a_skipped_question_becomes_a_clarification_question(self):
        skipped = {k: v for k, v in PROFILE.items() if k != "first_nations_registered"}
        rows = self.matches(skipped)
        asking = [r for r in rows if "first_nations_registered" in r["missing_profile_fields"]]
        self.assertEqual([r["title"] for r in asking], ["Post-Secondary Student Support Program (PSSSP)"])
        self.assertIn("Indian Act", asking[0]["clarification_questions"][0])
        self.assertIn("No card or registry number is needed", asking[0]["clarification_questions"][0])


if __name__ == "__main__":
    unittest.main()
