"""Checks that stand in for running the web/database layers where those libraries are unavailable.

They also keep guarding the code after the stack is installed: response models must match what the
services return, the ORM must match the migration, and no syntax newer than Python 3.11 may creep in.
"""

import ast
import importlib.util
import json
import unittest
from pathlib import Path

from navigator.core import contract
from navigator.core.timeutil import parse_as_of
from navigator.matching import rules
from navigator.matching.engine import MatchOptions, evaluate_record, match_records
from navigator.services.query import list_opportunities, opportunity_detail
from tests.support import AS_OF, DemoEnv

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("check_static", ROOT / "scripts" / "check_static.py")
check_static = importlib.util.module_from_spec(spec)
spec.loader.exec_module(check_static)


def model_fields() -> dict[str, dict[str, bool]]:
    """class name -> {field: required?} read from schemas/api.py and schemas/profile.py without importing pydantic."""
    out: dict[str, dict[str, bool]] = {}
    for rel in ("schemas/api.py", "schemas/profile.py"):
        for cls in [n for n in ast.parse((ROOT / "src/navigator" / rel).read_text()).body if isinstance(n, ast.ClassDef)]:
            fields = {}
            for stmt in cls.body:
                if isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name):
                    value = stmt.value
                    if value is None:
                        required = True
                    elif isinstance(value, ast.Call) and ast.unparse(value.func) == "Field":
                        required = not value.args and not any(k.arg in {"default", "default_factory"} for k in value.keywords)
                    else:
                        required = False
                    fields[stmt.target.id] = required
            out[cls.name] = fields
    return out


class StaticChecks(unittest.TestCase):
    def test_no_static_findings(self):
        files = check_static.ALL_FILES
        findings = (check_static.check_py311_fstrings(files) + check_static.check_unused_imports(files)
                    + check_static.check_internal_imports(files) + check_static.check_undefined_names(files)
                    + check_static.check_fstring_quotes(files) + check_static.check_ruff_defaults(files)
                    + check_static.check_schema_sync())
        self.assertEqual(findings, [])

    def test_exported_json_schema_is_current(self):
        path = ROOT / "docs" / "schemas" / "opportunity-record-1.0.schema.json"
        self.assertTrue(path.is_file(), "run `python scripts/export_schema.py`")
        self.assertEqual(json.loads(path.read_text(encoding="utf-8")), contract.record_schema())


class ResponseModelTests(unittest.TestCase):
    """FastAPI silently drops keys the model lacks and 500s on missing required keys: compare both ways."""

    def assert_matches(self, cls: str, output: dict):
        fields = model_fields()[cls]
        self.assertEqual(sorted(set(output) - set(fields)), [], f"{cls}: service returns keys the model would drop")
        missing = sorted(k for k, required in fields.items() if required and k not in output)
        self.assertEqual(missing, [], f"{cls}: required model fields the service does not return")

    def test_match_models(self):
        env = DemoEnv.get()
        profile = {"indigenous_identity": ["metis"], "institution_id": "demo_college", "education_level": "undergraduate"}
        flat = match_records(env.all_records(), profile, MatchOptions(as_of=AS_OF, limit=50), None, data_mode="demo")
        self.assert_matches("MatchResponse", flat)
        item = flat["results"][0]
        self.assert_matches("MatchItem", item)
        self.assert_matches("ApplicationRoute", item["application_route"])
        self.assert_matches("AvailabilityInfo", item["availability"])
        grouped = match_records(env.all_records(), profile, MatchOptions(as_of=AS_OF, limit=50, group_by_application=True), None, data_mode="demo")
        self.assert_matches("MatchResponse", grouped)
        self.assert_matches("MatchGroup", grouped["groups"][0])
        shared = next(g for g in grouped["groups"] if g["group_id"])
        self.assert_matches("MatchGroup", shared)
        every = [evaluate_record(r, profile, MatchOptions(as_of=AS_OF, include_closed=True)) for r in env.all_records()]
        for one in filter(None, every):
            self.assert_matches("MatchItem", one)

    def test_listing_and_detail_models(self):
        env = DemoEnv.get()
        out = list_opportunities(env.all_records(), as_of=AS_OF, freshness_days=30, data_mode="demo", province="BC", limit=100)
        self.assert_matches("OpportunityList", out)
        for row in out["results"]:
            self.assert_matches("OpportunitySummary", row)
            self.assert_matches("CurrentCycle", row["current_cycle"])
            self.assert_matches("ApplicabilityInfo", row["applicability"])
            self.assert_matches("ApplicationRoute", row["application_route"])
            self.assert_matches("ProviderRef", row["provider"])
        detail = opportunity_detail(env.record("demo_shared_application_a"), env.all_records(), as_of=AS_OF, freshness_days=30, data_mode="demo")
        self.assert_matches("OpportunityDetail", detail)
        self.assert_matches("SiblingRef", detail["shared_application_with"][0])

    def test_health_error_and_profile_models(self):
        health = {"status": "ok", "data_mode": "demo", "version": "x", "database": {"connected": True},
                  "migrations": {"current": "0001", "expected": "0001", "up_to_date": True}}
        self.assert_matches("HealthResponse", health)
        self.assert_matches("DatabaseState", health["database"])
        self.assert_matches("MigrationState", health["migrations"])
        from navigator.api.body import error_body
        body = error_body("validation_error", "request validation failed", "demo", [{"loc": ["body"], "type": "x", "msg": "y"}])
        self.assert_matches("ErrorResponse", body)
        self.assert_matches("ErrorBody", body["error"])
        profile_fields = set(model_fields()["Profile"])
        self.assertEqual(profile_fields, set(rules.PROFILE_FIELDS))  # every engine input is reachable, nothing extra is accepted
        self.assertTrue({"name", "email", "sin", "address", "student_number", "status_card_number", "income"}.isdisjoint(profile_fields))

    def test_match_request_defaults_agree_with_engine_options(self):
        fields = model_fields()["MatchRequest"]
        self.assertEqual(set(fields), {"profile", "as_of", "cycle_key", "group_by_application", "include_closed", "limit", "offset"})
        self.assertEqual([k for k, required in fields.items() if required], ["profile"])
        self.assertIsNotNone(parse_as_of("2026-10-07"))


if __name__ == "__main__":
    unittest.main()
