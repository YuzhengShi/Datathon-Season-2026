"""HTTP contract of the FastAPI app (TestClient). Needs the pinned stack; written without being able to
run FastAPI at authoring time, so a failure here is a real finding to fix, not noise."""

import gc
import json
import tempfile
import unittest
from pathlib import Path

from navigator.services.pipeline import run_demo_pipeline
from tests.support import AS_OF, isolated_runtime, requires_web_stack

ROOT = Path(__file__).resolve().parent.parent
PROFILE = {"indigenous_identity": ["metis"], "institution_id": "demo_college", "education_level": "undergraduate"}


@requires_web_stack
class ApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from fastapi.testclient import TestClient

        from navigator.api.app import create_app
        from navigator.db import make_engine, make_session_factory, upgrade_database
        from navigator.models.repository import SqlRepository

        cls.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        cls.rt = isolated_runtime(cls.tmp.name, "demo")
        upgrade_database(cls.rt.database_url)
        engine = make_engine(cls.rt.database_url)
        run_demo_pipeline(SqlRepository(make_session_factory(engine), engine), cls.rt, as_of=AS_OF)
        engine.dispose()
        cls.app = create_app(cls.rt)
        cls.client = TestClient(cls.app, raise_server_exceptions=False)

    @classmethod
    def tearDownClass(cls):
        cls.app.state.engine.dispose()
        gc.collect()
        cls.tmp.cleanup()

    def match(self, body):
        return self.client.post("/match", json=body)

    # ------------------------------------------------------------------ system
    def test_health(self):
        body = self.client.get("/health").json()
        self.assertEqual((body["status"], body["data_mode"], body["migrations"]["up_to_date"]), ("ok", "demo", True))
        self.assertNotIn("sqlite", json.dumps(body).lower())  # no connection string

    def test_openapi_lists_every_endpoint_and_no_write_endpoints(self):
        schema = self.client.get("/openapi.json").json()
        methods = {(path, m.upper()) for path, item in schema["paths"].items() for m in item}
        self.assertEqual(
            methods,
            {
                ("/health", "GET"),
                ("/opportunities", "GET"),
                ("/opportunities/{opportunity_id}", "GET"),
                ("/match", "POST"),
                ("/reports/freshness", "GET"),
            },
        )
        self.assertIn("MatchRequest", schema["components"]["schemas"])

    # ----------------------------------------------------------- opportunities
    def test_listing_defaults_filters_and_pagination(self):
        out = self.client.get("/opportunities?limit=100").json()
        ids = [r["id"] for r in out["results"]]
        self.assertEqual((out["data_mode"], out["total"]), ("demo", 23))
        self.assertNotIn("demo_award_collection", ids)
        self.assertEqual(
            [r["id"] for r in self.client.get("/opportunities?limit=5&offset=5").json()["results"]], ids[5:10]
        )
        self.assertIn(
            "demo_shared_application_a",
            [r["id"] for r in self.client.get("/opportunities?province=BC&limit=100").json()["results"]],
        )
        self.assertNotIn(
            "demo_shared_application_a",
            [r["id"] for r in self.client.get("/opportunities?province=ON&limit=100").json()["results"]],
        )
        self.assertEqual(
            [r["id"] for r in self.client.get("/opportunities?opportunity_type=award_collection").json()["results"]],
            ["demo_award_collection"],
        )

    def test_detail_and_errors_share_one_shape(self):
        ok = self.client.get("/opportunities/demo_supported_award")
        self.assertEqual(ok.status_code, 200)
        self.assertTrue(ok.json()["opportunity"]["evidence"])
        missing = self.client.get("/opportunities/nope")
        self.assertEqual(
            (missing.status_code, missing.json()["error"]["code"], missing.json()["data_mode"]),
            (404, "http_404", "demo"),
        )
        bad = self.client.get("/opportunities?limit=101")
        self.assertEqual((bad.status_code, bad.json()["error"]["code"]), (422, "validation_error"))
        self.assertEqual(self.client.get("/opportunities?province=ZZ").status_code, 422)

    # ------------------------------------------------------------------- match
    def test_the_three_demos_through_the_real_api(self):
        for name in ("1_supported_match", "2_needs_clarification", "3_shared_application"):
            body = json.loads((ROOT / "examples" / "requests" / f"{name}.json").read_text(encoding="utf-8"))
            response = self.match(body)
            self.assertEqual(response.status_code, 200, response.text[:300])
            self.assertEqual(response.json()["data_mode"], "demo")
        one = {
            i["opportunity_id"]: i
            for i in self.match({"profile": PROFILE, "as_of": "2026-10-07", "limit": 100}).json()["results"]
        }
        self.assertEqual(one["demo_supported_award"]["match_status"], "potential_fit")
        self.assertEqual(one["demo_clarification_award"]["match_status"], "needs_information")
        grouped = self.match(
            json.loads((ROOT / "examples" / "requests" / "3_shared_application.json").read_text(encoding="utf-8"))
        ).json()
        shared = next(g for g in grouped["groups"] if g["group_id"] == "demo_foundation_shared_form")
        self.assertEqual(
            {m["opportunity_id"]: m["match_status"] for m in shared["members"]},
            {"demo_shared_application_a": "potential_fit", "demo_shared_application_b": "not_eligible"},
        )
        self.assertIsNone(
            next(
                g for g in grouped["groups"] if g["members"][0]["opportunity_id"] == "demo_shared_application_exception"
            )["group_id"]
        )

    def test_match_validation_never_echoes_or_accepts_personal_data(self):
        marker = "ZZ-UNIQUE-MARKER-123"
        bad = self.match({"profile": {"home_community": marker, "residence_province": "ZZ"}})
        self.assertEqual(bad.status_code, 422)
        self.assertNotIn(marker, bad.text)
        refused = self.match({"profile": {"full_name": marker}})
        self.assertEqual(refused.status_code, 422)
        self.assertNotIn(marker, refused.text)
        self.assertEqual(self.match({"profile": {}, "as_of": "not-a-date"}).status_code, 422)
        self.assertEqual(self.match({"profile": {}, "limit": 0}).status_code, 422)

    def test_the_profile_is_not_persisted_or_logged(self):
        marker = "ZZ-PERSIST-CHECK-987"
        with self.assertNoLogs("navigator", level="DEBUG"):  # the app logs nothing about a match call
            self.assertEqual(
                self.match({"profile": {"home_community": marker, "indigenous_identity": ["inuit"]}}).status_code, 200
            )
        database = Path(self.tmp.name) / "demo" / "navigator.db"
        self.assertNotIn(marker.encode(), database.read_bytes())
        for path in (Path(self.tmp.name) / "demo").rglob("*"):
            if path.is_file() and path.suffix in {".json", ".jsonl", ".md"}:
                self.assertNotIn(marker, path.read_text(encoding="utf-8"))

    # ----------------------------------------------------------------- reports
    def test_freshness_report_hides_file_paths(self):
        report = self.client.get("/reports/freshness").json()
        self.assertEqual((report["data_mode"], report["opportunities"]["total"]), ("demo", 25))
        self.assertNotIn(self.tmp.name, json.dumps(report))

    # --------------------------------------------------------------- hardening
    def test_cors_is_off_unless_origins_are_listed(self):
        from fastapi.testclient import TestClient

        from navigator.api.app import create_app

        self.assertNotIn(
            "access-control-allow-origin",
            self.client.get("/health", headers={"Origin": "https://evil.example"}).headers,
        )
        rt = isolated_runtime(self.tmp.name, "demo", CORS_ALLOW_ORIGINS="https://app.example")
        app = create_app(rt)
        try:
            client = TestClient(app)
            allowed = client.get("/health", headers={"Origin": "https://app.example"}).headers
            self.assertEqual(allowed.get("access-control-allow-origin"), "https://app.example")
            self.assertNotIn("access-control-allow-credentials", allowed)
            self.assertNotIn(
                "access-control-allow-origin", client.get("/health", headers={"Origin": "https://evil.example"}).headers
            )
        finally:
            app.state.engine.dispose()

    def test_unhandled_errors_do_not_leak_details(self):
        from unittest import mock

        with mock.patch("navigator.api.routes.list_opportunities", side_effect=RuntimeError("secret-internal-detail")):
            response = self.client.get("/opportunities")
        self.assertEqual((response.status_code, response.json()["error"]["code"]), (500, "internal_error"))
        self.assertNotIn("secret-internal-detail", response.text)


if __name__ == "__main__":
    unittest.main()
