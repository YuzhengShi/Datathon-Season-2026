"""Documentation must not drift from the code it describes."""

import ast
import importlib.util
import re
import unittest
from pathlib import Path

from navigator.core import contract
from navigator.ingestion.adapters import registry
from navigator.ingestion.sources import load_sources

ROOT = Path(__file__).resolve().parent.parent


def read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def cli_commands() -> list[str]:
    names = []
    for node in ast.walk(ast.parse(read("src/navigator/cli.py"))):
        if isinstance(node, ast.FunctionDef):
            for dec in node.decorator_list:
                if isinstance(dec, ast.Call) and isinstance(dec.func, ast.Attribute) and dec.func.attr == "command":
                    explicit = ast.literal_eval(dec.args[0]) if dec.args else node.name.replace("_", "-")
                    prefix = "db " if getattr(dec.func.value, "id", "") == "db_app" else ""
                    names.append(prefix + explicit)
    return names


class DocsTests(unittest.TestCase):
    def test_readme_has_exactly_the_three_required_headings(self):
        headings = [line for line in read("README.md").splitlines() if line.startswith("## ")]
        self.assertEqual(
            headings, ["## 1. Problem evidence", "## 2. Data evidence", "## 3. What we are taking into Build Session 2"]
        )

    def test_readme_does_not_claim_user_research_that_never_happened(self):
        text = read("README.md").lower()
        self.assertIn("no student interviews", text)
        for phrase in ("we interviewed", "students told us", "user feedback shows", "survey of"):
            self.assertNotIn(phrase, text)

    def test_data_model_is_generated_from_the_contract(self):
        spec = importlib.util.spec_from_file_location("gen_doc", ROOT / "scripts" / "generate_data_model_doc.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        self.assertEqual(read("docs/DATA_MODEL.md"), module.render(), "run `python scripts/generate_data_model_doc.py`")
        for group in (contract.OPPORTUNITY_TYPES, contract.ROUTE_TYPES, contract.AMOUNT_KINDS, contract.DEADLINE_KINDS):
            for value in group:
                self.assertIn(f"`{value}`", read("docs/DATA_MODEL.md"))

    def test_runbook_documents_every_cli_command(self):
        runbook = read("docs/RUNBOOK.md") + read("README.md")
        commands = cli_commands()
        self.assertGreaterEqual(len(commands), 10)
        for name in commands:
            if name != "version":
                self.assertIn(f"navigator.cli {name}", runbook, name)

    def test_documented_commands_use_options_that_exist(self):
        options = set(re.findall(r'"(--[a-z-]+)"', read("src/navigator/cli.py")))
        used = set(re.findall(r"(?<=\s)(--[a-z][a-z-]+)", read("docs/RUNBOOK.md")))
        used -= {
            "--break-system-packages",
            "--no-deps",
            "--upgrade",
            "--help",
            "--exclude-editable",
            "--factory",
            "--timeout",
            "--wait",
        }
        used = {u for u in used if u in options or u in {"--base-url", "--expect-mode"}}
        self.assertTrue(used)

    def test_relative_links_resolve(self):
        for rel in ("README.md", "docs/RUNBOOK.md", "docs/ARCHITECTURE.md", "docs/DATA_SOURCES.md", "docs/HANDOFF.md"):
            base = (ROOT / rel).parent
            for target in re.findall(r"\]\(([^)#]+)(?:#[^)]*)?\)", read(rel)):
                if not target.startswith(("http://", "https://", "mailto:")):
                    self.assertTrue((base / target).exists(), f"{rel} links to missing {target}")

    def test_data_sources_doc_covers_every_source_and_adapter(self):
        text = read("docs/DATA_SOURCES.md")
        for source in load_sources(ROOT / "sources.yaml"):
            self.assertIn(f"`{source.source_id}`", text)
        for name in registry():
            self.assertIn(f"`{name}`", text)

    def test_handoff_has_the_acceptance_table(self):
        text = read("docs/HANDOFF.md")
        for row in (
            "Environment and architecture",
            "Core configuration",
            "From an empty directory",
            "No network / no key",
            "Traceable import",
            "Idempotency and transactions",
            "Data semantics",
            "Three demonstrations",
            "Live data",
            "Data isolation",
            "Recovery",
        ):
            self.assertIn(row, text)

    def test_required_project_files_exist(self):
        for rel in (
            "pyproject.toml",
            "requirements.lock",
            ".env.example",
            ".gitignore",
            "sources.yaml",
            "alembic.ini",
            "migrations/env.py",
            "migrations/versions/0001_initial.py",
            "scripts/smoke_test.py",
            "docs/ARCHITECTURE.md",
            "docs/DATA_MODEL.md",
            "docs/DATA_SOURCES.md",
            "docs/RUNBOOK.md",
            "docs/HANDOFF.md",
            "docs/schemas/opportunity-record-1.0.schema.json",
        ):
            self.assertTrue((ROOT / rel).is_file(), rel)
        env_keys = {
            line.split("=")[0] for line in read(".env.example").splitlines() if "=" in line and not line.startswith("#")
        }
        self.assertEqual(
            env_keys,
            {
                "DATA_MODE",
                "DATABASE_URL",
                "DEMO_DATABASE_URL",
                "DATA_DIR",
                "SOURCE_CONFIG",
                "LOG_LEVEL",
                "FETCH_TIMEOUT_SECONDS",
                "FETCH_MAX_BYTES",
                "FETCH_RETRIES",
                "FETCH_PER_HOST_CONCURRENCY",
                "FETCH_MIN_INTERVAL_SECONDS",
                "FRESHNESS_DAYS",
                "EXTRACTION_MODE",
                "OPENAI_API_KEY",
                "OPENAI_MODEL",
            },
        )


if __name__ == "__main__":
    unittest.main()


class FixtureTests(unittest.TestCase):
    def test_committed_demo_fixtures_match_the_generator(self):
        from navigator.demo import content
        from navigator.ingestion.text import extract

        folder = ROOT / "tests" / "fixtures" / "demo"
        for page in content.PAGES:
            self.assertEqual((folder / f"{page.key}.html").read_bytes(), content.render_html(page), page.key)
        guide = extract((folder / "foundation_guide.pdf").read_bytes(), "application/pdf")
        self.assertEqual((guide.status, guide.page_count), ("ok", 2))
        self.assertEqual(
            extract((folder / "scanned_notice.pdf").read_bytes(), "application/pdf").status, "ocr_required"
        )
