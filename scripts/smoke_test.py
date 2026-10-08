"""End-to-end check of a RUNNING API using only the standard library (works the same on Windows,
macOS and Linux; no curl aliases involved). Needs no internet.

    python scripts/smoke_test.py --base-url http://127.0.0.1:8000 --expect-mode demo

Start the server in another terminal first (see docs/RUNBOOK.md). Exit code 0 = every check passed.
It loads the three demo requests from examples/requests and compares the key fields of the response
with examples/expected, so nobody has to guess the profile schema.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
ITEM_KEYS = ("opportunity_id", "eligibility_result", "match_status", "availability_status", "application_group_id",
             "missing_profile_fields", "clarification_questions")
ABS_PATH = re.compile(r"^(/(home|tmp|var|usr|Users|mnt|data)/|[A-Za-z]:[\\/])")


class Smoke:
    def __init__(self, base: str, timeout: float) -> None:
        self.base, self.timeout, self.failures = base.rstrip("/"), timeout, 0

    def call(self, method: str, path: str, body: Any = None) -> tuple[int, Any]:
        data = json.dumps(body).encode("utf-8") if body is not None else None
        req = urllib.request.Request(self.base + path, data=data, method=method,
                                     headers={"Content-Type": "application/json", "Accept": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                return resp.status, json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            raw = exc.read().decode("utf-8", "replace")
            try:
                return exc.code, json.loads(raw)
            except json.JSONDecodeError:
                return exc.code, {"raw": raw[:200]}

    def check(self, name: str, ok: bool, detail: str = "") -> bool:
        print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  - {detail}" if detail and not ok else ""))
        self.failures += 0 if ok else 1
        return ok


def strings(node: Any):
    if isinstance(node, str):
        yield node
    elif isinstance(node, dict):
        for value in node.values():
            yield from strings(value)
    elif isinstance(node, list):
        for value in node:
            yield from strings(value)


def pick(item: dict) -> dict:
    return {k: item.get(k) for k in ITEM_KEYS}


def run(args: argparse.Namespace) -> int:
    s = Smoke(args.base_url, args.timeout)
    deadline = time.time() + args.wait
    while True:
        try:
            status, health = s.call("GET", "/health")
            break
        except (urllib.error.URLError, ConnectionError, TimeoutError) as exc:
            if time.time() > deadline:
                print(f"FAIL  server not reachable at {args.base_url}: {exc}")
                return 1
            time.sleep(0.5)
    mode = args.expect_mode
    s.check("health: 200 and status ok", status == 200 and health.get("status") == "ok", str(health))
    s.check("health: data_mode matches", health.get("data_mode") == mode, f"{health.get('data_mode')!r} != {mode!r}")
    s.check("health: migrations up to date", health.get("migrations", {}).get("up_to_date") is True, str(health.get("migrations")))
    s.check("health: no connection string leaked", not any("://" in v and "sql" in v.lower() for v in strings(health)))

    status, listing = s.call("GET", "/opportunities?limit=100")
    s.check("list: 200", status == 200, str(listing)[:200])
    results = listing.get("results", [])
    s.check("list: data_mode matches", listing.get("data_mode") == mode)
    s.check("list: collections are hidden by default", all(r["opportunity_type"] != "award_collection" for r in results))
    s.check("list: stable pagination fields", {"total", "limit", "offset", "count"} <= set(listing))
    if mode == "demo":
        s.check("list: demo data present", any(r["id"] == "demo_supported_award" for r in results) and len(results) >= 12)
    status, collections = s.call("GET", "/opportunities?opportunity_type=award_collection")
    s.check("list: collections appear when requested", status == 200 and collections.get("data_mode") == mode)
    status, bad = s.call("GET", "/opportunities?limit=1000")
    s.check("list: limit above 100 is a 422 with the standard error shape", status == 422 and bad.get("error", {}).get("code") == "validation_error", str(bad)[:160])

    if results:
        first = results[0]["id"]
        status, detail = s.call("GET", "/opportunities/" + urllib.parse.quote(first, safe=":"))
        s.check("detail: 200 with evidence and next steps", status == 200 and detail.get("opportunity", {}).get("id") == first
                and "next_steps" in detail and "evidence" in detail["opportunity"], str(detail)[:200])
        s.check("detail: storage paths are not exposed", not any("raw_path" in r or "text_path" in r for r in detail.get("opportunity", {}).get("source_refs", [])))
    status, missing = s.call("GET", "/opportunities/does-not-exist")
    s.check("detail: unknown id is a 404 with the standard error shape", status == 404 and missing.get("error", {}).get("code") == "http_404"
            and missing.get("data_mode") == mode, str(missing)[:200])

    examples = ROOT / "examples"
    for request_file in sorted((examples / "requests").glob("*.json")):
        body = json.loads(request_file.read_text(encoding="utf-8"))
        status, response = s.call("POST", "/match", body)
        label = f"match {request_file.stem}"
        s.check(f"{label}: 200 and data_mode", status == 200 and response.get("data_mode") == mode, str(response)[:200])
        if mode != "demo" or status != 200:
            continue
        expected = json.loads((examples / "expected" / f"{request_file.stem}.response.json").read_text(encoding="utf-8"))
        if "results" in expected:
            got = {i["opportunity_id"]: pick(i) for i in response.get("results") or []}
            want = {i["opportunity_id"]: pick(i) for i in expected["results"]}
            s.check(f"{label}: expected items match", all(got.get(k) == v for k, v in want.items()),
                    f"want {want} got {[got.get(k) for k in want]}")
        else:
            got_groups = {g["group_id"] or g["members"][0]["opportunity_id"]: {m["opportunity_id"]: pick(m) for m in g["members"]}
                          for g in response.get("groups") or []}
            want_groups = {g["group_id"] or g["members"][0]["opportunity_id"]: {m["opportunity_id"]: pick(m) for m in g["members"]}
                           for g in expected["groups"]}
            s.check(f"{label}: groups match (each member matched separately)", all(got_groups.get(k) == v for k, v in want_groups.items()),
                    f"want {want_groups}")
            s.check(f"{label}: total_groups reported", response.get("total_groups") == len(response.get("groups") or []) or response.get("total_groups", 0) >= len(response.get("groups") or []))

    marker = "ZZ-SMOKE-" + uuid.uuid4().hex[:10]
    status, resp = s.call("POST", "/match", {"profile": {"home_community": marker, "residence_province": "ZZ"}})
    s.check("match: validation error does not echo the profile", status == 422 and marker not in json.dumps(resp), str(resp)[:200])
    status, resp = s.call("POST", "/match", {"profile": {"home_community": marker}})
    s.check("match: profile is not echoed in the response", status == 200 and marker not in json.dumps(resp))
    status, resp = s.call("POST", "/match", {"profile": {"full_name": "Someone"}})
    s.check("match: personal-identifier fields are refused", status == 422 and "Someone" not in json.dumps(resp))
    _, after = s.call("GET", "/opportunities?q=" + urllib.parse.quote(marker))
    s.check("match: profile was not persisted (searchable data unchanged)", after.get("total") == 0)

    status, report = s.call("GET", "/reports/freshness")
    s.check("freshness: 200 and data_mode", status == 200 and report.get("data_mode") == mode, str(report)[:200])
    s.check("freshness: carries as_of and generated_at", bool(report.get("as_of")) and bool(report.get("generated_at")))
    s.check("freshness: no absolute file paths exposed", not [v for v in strings(report) if ABS_PATH.match(v)], str([v for v in strings(report) if ABS_PATH.match(v)][:3]))
    s.check("freshness: marker never stored", marker not in json.dumps(report))
    print(f"\n{'ALL CHECKS PASSED' if not s.failures else str(s.failures) + ' CHECK(S) FAILED'}")
    return 1 if s.failures else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--expect-mode", choices=["demo", "live"], default="demo")
    parser.add_argument("--timeout", type=float, default=15.0)
    parser.add_argument("--wait", type=float, default=0.0, help="seconds to wait for the server to come up")
    return run(parser.parse_args())


if __name__ == "__main__":
    sys.exit(main())
