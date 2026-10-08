"""Command-line behaviour through Typer's CliRunner. Needs the pinned stack (see requirements.lock)."""

import gc
import json
import tempfile
import unittest
from pathlib import Path

from tests.support import requires_web_stack

ROOT = Path(__file__).resolve().parent.parent


@requires_web_stack
class CliTests(unittest.TestCase):
    def setUp(self):
        from typer.testing import CliRunner

        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.env = {
            "DATA_DIR": self.tmp.name,
            "DATA_MODE": "live",
            "SOURCE_CONFIG": str(ROOT / "sources.yaml"),
            "DATABASE_URL": f"sqlite:///{Path(self.tmp.name).as_posix()}/navigator.db",
            "DEMO_DATABASE_URL": f"sqlite:///{Path(self.tmp.name).as_posix()}/demo/navigator.db",
        }
        self.runner = CliRunner()

    def tearDown(self):
        gc.collect()
        self.tmp.cleanup()

    def run_cli(self, *args):
        from navigator.cli import app

        return self.runner.invoke(app, list(args), env=self.env)

    def test_help_lists_every_documented_command(self):
        out = self.run_cli("--help").stdout
        for command in ("db", "pipeline", "fetch", "extract", "validate", "import-data", "export", "report", "serve"):
            self.assertIn(command, out)

    def test_demo_flow_end_to_end(self):
        self.assertEqual(self.run_cli("db", "upgrade", "--mode", "demo").exit_code, 0)
        first = self.run_cli("pipeline", "--mode", "demo", "--as-of", "2026-10-07")
        self.assertEqual(first.exit_code, 0, first.output)
        self.assertEqual(json.loads(first.stdout)["import_counts"]["created"], 25)
        second = self.run_cli("pipeline", "--mode", "demo", "--as-of", "2026-10-07")
        self.assertEqual(json.loads(second.stdout)["import_counts"]["unchanged"], 25)
        root = Path(self.tmp.name) / "demo"
        self.assertTrue((root / "awards.jsonl").is_file())
        self.assertFalse((Path(self.tmp.name) / "navigator.db").exists())  # live database untouched
        ok = self.run_cli(
            "validate",
            "--input",
            str(root / "candidates" / "awards.jsonl"),
            "--artifact-root",
            str(root),
            "--mode",
            "demo",
            "--as-of",
            "2026-10-07",
        )
        self.assertEqual(ok.exit_code, 0, ok.output)
        dry = self.run_cli(
            "import-data",
            "--mode",
            "demo",
            "--input",
            str(root / "candidates" / "awards.jsonl"),
            "--artifact-root",
            str(root),
            "--dry-run",
            "--as-of",
            "2026-10-07",
        )
        self.assertEqual(dry.exit_code, 0, dry.output)
        out = root / "exported.jsonl"
        self.assertEqual(self.run_cli("export", "--mode", "demo", "--output", str(out)).exit_code, 0)
        self.assertEqual(len(out.read_text(encoding="utf-8").splitlines()), 25)
        self.assertEqual(self.run_cli("report", "--mode", "demo", "--as-of", "2026-10-07").exit_code, 0)

    def test_corrupted_candidates_exit_1_and_are_quarantined(self):
        self.run_cli("pipeline", "--mode", "demo", "--as-of", "2026-10-07")
        root = Path(self.tmp.name) / "demo"
        lines = (root / "candidates" / "awards.jsonl").read_text(encoding="utf-8").splitlines()
        record = json.loads(lines[0])
        record["evidence"][0]["quote"] = "forged sentence"
        broken = root / "broken.jsonl"
        broken.write_text("\n".join([json.dumps(record), *lines[1:]]) + "\n", encoding="utf-8")
        result = self.run_cli(
            "validate", "--input", str(broken), "--artifact-root", str(root), "--mode", "demo", "--as-of", "2026-10-07"
        )
        self.assertEqual(result.exit_code, 1)
        self.assertTrue(list((root / "quarantine").glob("validate-*.jsonl")))

    def test_configuration_and_argument_errors_exit_2(self):
        self.assertEqual(self.run_cli("pipeline", "--mode", "bogus").exit_code, 2)
        self.assertEqual(self.run_cli("pipeline", "--mode", "demo", "--as-of", "not-a-date").exit_code, 2)
        self.assertEqual(self.run_cli("fetch", "--mode", "demo").exit_code, 2)  # demo never touches the network
        self.env["DEMO_DATABASE_URL"] = self.env["DATABASE_URL"]
        self.assertEqual(
            self.run_cli("db", "upgrade", "--mode", "demo").exit_code, 2
        )  # unsafe: demo would share the live DB

    def test_explicit_mode_beats_data_mode(self):
        self.env["DATA_MODE"] = "demo"
        self.assertEqual(self.run_cli("db", "upgrade", "--mode", "live").exit_code, 0)
        self.assertTrue((Path(self.tmp.name) / "navigator.db").exists())


if __name__ == "__main__":
    unittest.main()
