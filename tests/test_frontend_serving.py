"""The web app is served by the API itself (same origin, no CORS) and the API gives it what it needs."""

import shutil
import tempfile
import unittest
from pathlib import Path

from tests.support import isolated_runtime, requires_web_stack

ROOT = Path(__file__).resolve().parent.parent


class SourceKindTests(unittest.TestCase):
    def test_a_directory_entry_is_not_presented_as_the_providers_own_page(self):
        from navigator.services.query import source_kind

        self.assertEqual(source_kind({"source_refs": [{"role": "discovery_index"}]}), "directory_listing")
        self.assertEqual(
            source_kind({"source_refs": [{"role": "discovery_index"}, {"role": "award_listing"}]}), "official_page"
        )
        self.assertEqual(source_kind({"source_refs": [{"role": "funding_channel"}]}), "official_page")
        self.assertEqual(source_kind({"source_refs": []}), "official_page")


@requires_web_stack
class FrontendServingTests(unittest.TestCase):
    def client(self, mode):
        from fastapi.testclient import TestClient

        from navigator.api.app import create_app

        tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(tmp.cleanup)
        (Path(tmp.name) / "reference").mkdir()  # reference data lives under DATA_DIR
        shutil.copy(ROOT / "data" / "reference" / "institutions.yaml", Path(tmp.name) / "reference")
        app = create_app(isolated_runtime(tmp.name, mode))
        self.addCleanup(app.state.engine.dispose)
        return TestClient(app, follow_redirects=False)

    def test_the_root_serves_the_site_and_the_questionnaire_app_is_served_at_app(self):
        client = self.client("demo")
        site = client.get("/")
        self.assertEqual(site.status_code, 200)
        self.assertIn("insights.js", site.text)  # the site: Explore, Statistics, AI search
        page = client.get("/app/")
        self.assertEqual(page.status_code, 200)
        self.assertIn("api.js", page.text)  # the questionnaire app talks to the core API
        self.assertIn('id="main"', page.text)

    def test_scripts_have_a_module_safe_content_type_and_the_page_is_locked_down(self):
        client = self.client("demo")
        script = client.get("/app/app.js")
        self.assertEqual(script.status_code, 200)
        self.assertIn(
            "javascript", script.headers["content-type"]
        )  # never text/plain: browsers refuse that for modules
        for response in (script, client.get("/app/")):
            self.assertEqual(response.headers["x-content-type-options"], "nosniff")
            self.assertIn("default-src 'self'", response.headers["content-security-policy"])
            self.assertIn("frame-ancestors 'none'", response.headers["content-security-policy"])
        self.assertNotIn("content-security-policy", client.get("/health").headers)  # the API docs are left alone
        # the site is not under the questionnaire app's CSP (its charts use inline styles), but is never sniffed
        site_script = client.get("/insights.js")
        self.assertEqual(site_script.status_code, 200)
        self.assertIn("javascript", site_script.headers["content-type"])
        self.assertEqual(site_script.headers["x-content-type-options"], "nosniff")
        self.assertNotIn("content-security-policy", site_script.headers)

    def test_nothing_outside_the_frontend_folders_is_served(self):
        client = self.client("demo")
        for path in (
            "/app/../pyproject.toml",
            "/app/%2e%2e/pyproject.toml",
            "/app/assets/../../sources.yaml",
            "/app/nope.js",
            "/%2e%2e/pyproject.toml",
            "/data/%2e%2e/%2e%2e/sources.yaml",
            "/nope.js",
        ):
            self.assertEqual(client.get(path).status_code, 404, path)

    def test_the_institution_list_is_mode_scoped(self):
        demo = self.client("demo").get("/reference/institutions").json()
        live = self.client("live").get("/reference/institutions").json()
        self.assertEqual((demo["data_mode"], [i["id"] for i in demo["institutions"]]), ("demo", ["demo_college"]))
        ids = [i["id"] for i in live["institutions"]]
        self.assertEqual(live["data_mode"], "live")
        self.assertNotIn("demo_college", ids)
        self.assertTrue({"ubc", "sfu", "uvic", "viu", "langara"} <= set(ids))
        self.assertEqual(
            ids, sorted(ids, key=lambda i: next(x["name"].lower() for x in live["institutions"] if x["id"] == i))
        )

    def test_the_site_dataset_and_the_api_always_agree_about_the_mode(self):
        """The site loads its records from the same read model as /api/*: it cannot show another mode's data."""
        import json

        from fastapi.testclient import TestClient

        from navigator.api.app import create_app
        from navigator.app.config import Settings
        from navigator.app.publish import DEFAULT_DATASET, DEMO_DATASET, ensure_read_model, load_records

        expected = {
            "demo": len(json.loads(DEMO_DATASET.read_text(encoding="utf-8"))["records"]),
            "live": len(load_records(DEFAULT_DATASET)),
        }
        for mode in ("demo", "live"):
            with self.subTest(mode=mode):
                tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
                self.addCleanup(tmp.cleanup)
                (Path(tmp.name) / "reference").mkdir()
                shutil.copy(ROOT / "data" / "reference" / "institutions.yaml", Path(tmp.name) / "reference")
                settings = Settings(_env_file=None, data_mode=mode, data_dir=tmp.name, llm_enabled=False)
                ensure_read_model(settings)
                app = create_app(isolated_runtime(tmp.name, mode), app_settings=settings)
                self.addCleanup(app.state.engine.dispose)
                self.addCleanup(app.state.app_engine.dispose)
                client = TestClient(app, follow_redirects=False)
                dataset = client.get("/data/opportunities.json").json()
                health = client.get("/api/health").json()
                self.assertEqual((dataset["data_mode"], health["data_mode"]), (mode, mode))
                self.assertTrue(health["migration_ready"])
                self.assertEqual(len(dataset["records"]), expected[mode])
                self.assertTrue(all(bool(r["is_demo"]) == (mode == "demo") for r in dataset["records"]))
                orders = [r["display_order"] for r in dataset["records"]]
                self.assertEqual(orders, sorted(orders))  # the order the site shows is the published order
                total = client.post("/api/opportunities/search", json={"filters": {}}).json()["total"]
                self.assertEqual(total, expected[mode])


if __name__ == "__main__":
    unittest.main()
