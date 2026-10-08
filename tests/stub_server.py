"""A TEST DOUBLE of the HTTP layer (stdlib only): the same routes and error shapes as the real FastAPI
app, backed by the same pure services. It exists so scripts/smoke_test.py can be exercised in an
environment without FastAPI. It is NOT the real API and proves nothing about FastAPI itself."""

from __future__ import annotations

import json
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlsplit

from navigator import __version__
from navigator.api.body import error_body
from navigator.config import derive_runtime
from navigator.core.timeutil import parse_as_of
from navigator.ingestion.memory_repo import MemoryRepository
from navigator.matching.engine import MatchOptions, match_records
from navigator.matching.rules import PROFILE_FIELDS, PROVINCES
from navigator.reference import load_institutions
from navigator.reports.freshness import build_freshness_report
from navigator.services.pipeline import run_demo_pipeline
from navigator.services.query import list_opportunities, opportunity_detail
from tests.support import AS_OF

ROOT = Path(__file__).resolve().parent.parent
INSTITUTIONS = load_institutions(ROOT / "data" / "reference" / "institutions.yaml")
TOP_KEYS = {"profile", "as_of", "cycle_key", "group_by_application", "include_closed", "limit", "offset"}


class StubServer:
    def __init__(self, *, reported_mode: str = "demo", echo_validation_input: bool = False, migrated: bool = True) -> None:
        self.mode, self.echo, self.migrated = reported_mode, echo_validation_input, migrated
        self._tmp = tempfile.TemporaryDirectory()
        rt = derive_runtime({"DATA_DIR": self._tmp.name}, "demo")
        self.repo = MemoryRepository()
        run_demo_pipeline(self.repo, rt, as_of=AS_OF)
        self.records = self.repo.list_records(published_only=True, is_demo=True)
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), self._handler())
        self.url = f"http://127.0.0.1:{self.httpd.server_address[1]}"
        self._thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)

    def __enter__(self) -> "StubServer":
        self._thread.start()
        return self

    def __exit__(self, *exc) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()
        self._tmp.cleanup()

    def _handler(self):
        stub = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):  # silence
                pass

            def send(self, status: int, payload: dict) -> None:
                data = json.dumps(payload).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def invalid(self, loc: list[str], received) -> None:
                details = [{"loc": loc, "type": "value_error", "msg": "invalid value"}]
                if stub.echo:  # a deliberately broken variant for the negative test
                    details[0]["input"] = received
                self.send(422, error_body("validation_error", "request validation failed", stub.mode, details))

            def do_GET(self):  # noqa: N802
                parts = urlsplit(self.path)
                query = {k: v[0] for k, v in parse_qs(parts.query).items()}
                if parts.path == "/health":
                    return self.send(200, {"status": "ok", "data_mode": stub.mode, "version": __version__,
                                           "database": {"connected": True},
                                           "migrations": {"current": "0001", "expected": "0001", "up_to_date": stub.migrated}})
                if parts.path == "/opportunities":
                    limit = int(query.get("limit", 20))
                    if not 1 <= limit <= 100:
                        return self.invalid(["query", "limit"], limit)
                    out = list_opportunities(
                        stub.records, as_of=AS_OF, freshness_days=30, data_mode=stub.mode, q=query.get("q"),
                        province=query.get("province"), education_level=query.get("education_level"),
                        opportunity_type=query.get("opportunity_type"), limit=limit, offset=int(query.get("offset", 0)))
                    return self.send(200, out)
                if parts.path.startswith("/opportunities/"):
                    rid = unquote(parts.path[len("/opportunities/"):])
                    record = next((r for r in stub.records if r["id"] == rid), None)
                    if record is None:
                        return self.send(404, error_body("http_404", "opportunity not found", stub.mode))
                    return self.send(200, opportunity_detail(record, stub.records, as_of=AS_OF, freshness_days=30, data_mode=stub.mode))
                if parts.path == "/reports/freshness":
                    records = stub.repo.list_records(published_only=False, is_demo=True)
                    return self.send(200, build_freshness_report(records, mode=stub.mode, as_of=AS_OF, generated_at=AS_OF,
                                                                 freshness_days=30, run_context=stub.repo.latest_run_context("demo")))
                return self.send(404, error_body("http_404", "not found", stub.mode))

            def do_POST(self):  # noqa: N802
                if urlsplit(self.path).path != "/match":
                    return self.send(404, error_body("http_404", "not found", stub.mode))
                body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
                profile = body.get("profile", {})
                for key in body:
                    if key not in TOP_KEYS:
                        return self.invalid(["body", key], body[key])
                for key, value in profile.items():
                    if key not in PROFILE_FIELDS:
                        return self.invalid(["body", "profile", key], value)
                    if key in {"residence_province", "institution_province"} and value not in PROVINCES:
                        return self.invalid(["body", "profile", key], value)
                options = MatchOptions(as_of=parse_as_of(body.get("as_of")), group_by_application=body.get("group_by_application", False),
                                       include_closed=body.get("include_closed", False), limit=body.get("limit", 20), offset=body.get("offset", 0))
                return self.send(200, match_records(stub.records, profile, options, INSTITUTIONS.resolve, data_mode=stub.mode))

        return Handler
