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

    def test_the_root_leads_to_the_app_and_the_app_is_served(self):
        client = self.client("demo")
        self.assertIn(client.get("/").status_code, (302, 307))
        self.assertEqual(client.get("/").headers["location"], "/app/")
        page = client.get("/app/")
        self.assertEqual(page.status_code, 200)
        self.assertIn('id="root"', page.text)

    def test_scripts_have_a_module_safe_content_type_and_the_page_is_locked_down(self):
        client = self.client("demo")
        script = client.get("/app/assets/main.js")
        self.assertEqual(script.status_code, 200)
        self.assertIn(
            "javascript", script.headers["content-type"]
        )  # never text/plain: browsers refuse that for modules
        for response in (script, client.get("/app/")):
            self.assertEqual(response.headers["x-content-type-options"], "nosniff")
            self.assertIn("default-src 'self'", response.headers["content-security-policy"])
            self.assertIn("frame-ancestors 'none'", response.headers["content-security-policy"])
        self.assertNotIn("content-security-policy", client.get("/health").headers)  # the API docs are left alone

    def test_nothing_outside_the_frontend_folder_is_served(self):
        client = self.client("demo")
        for path in (
            "/app/../pyproject.toml",
            "/app/%2e%2e/pyproject.toml",
            "/app/assets/../../sources.yaml",
            "/app/nope.js",
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


if __name__ == "__main__":
    unittest.main()
