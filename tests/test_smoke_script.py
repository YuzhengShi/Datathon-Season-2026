import ast
import subprocess
import sys
import unittest
from pathlib import Path

from tests.stub_server import StubServer

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "smoke_test.py"


def smoke(url: str, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--base-url", url, "--timeout", "10", *args],
        capture_output=True,
        text=True,
        timeout=120,
    )


class SmokeScriptTests(unittest.TestCase):
    """Runs the real smoke script against a stdlib stand-in for the API (see tests/stub_server.py)."""

    def test_passes_against_a_conforming_server(self):
        with StubServer() as stub:
            out = smoke(stub.url, "--expect-mode", "demo")
        self.assertEqual(out.returncode, 0, out.stdout + out.stderr)
        self.assertIn("ALL CHECKS PASSED", out.stdout)
        self.assertGreaterEqual(out.stdout.count("PASS"), 25)
        self.assertNotIn("FAIL", out.stdout)

    def test_fails_when_the_server_reports_the_wrong_mode(self):
        with StubServer(reported_mode="live") as stub:
            out = smoke(stub.url, "--expect-mode", "demo")
        self.assertEqual(out.returncode, 1)
        self.assertIn("FAIL  health: data_mode matches", out.stdout)

    def test_fails_when_validation_errors_echo_the_profile(self):
        with StubServer(echo_validation_input=True) as stub:
            out = smoke(stub.url)
        self.assertEqual(out.returncode, 1)
        self.assertIn("does not echo the profile", out.stdout)

    def test_fails_when_migrations_are_not_applied(self):
        with StubServer(migrated=False) as stub:
            out = smoke(stub.url)
        self.assertEqual(out.returncode, 1)
        self.assertIn("migrations up to date", out.stdout)

    def test_unreachable_server_is_a_failure_not_a_hang(self):
        out = smoke("http://127.0.0.1:9", "--wait", "0")
        self.assertEqual(out.returncode, 1)
        self.assertIn("not reachable", out.stdout)

    def test_the_script_needs_only_the_standard_library(self):
        stdlib = set(sys.stdlib_module_names)
        imported = set()
        for node in ast.walk(ast.parse(SCRIPT.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Import):
                imported.update(a.name.split(".")[0] for a in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module.split(".")[0])
        self.assertEqual(imported - stdlib, set())


if __name__ == "__main__":
    unittest.main()
