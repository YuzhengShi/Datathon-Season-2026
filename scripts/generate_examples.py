"""Regenerate examples/requests/*.json (complete valid POST /match bodies) and examples/expected/*.json
(real excerpts of what the matching engine returns for them on the synthetic demo data).

The excerpts are produced by running the engine, never typed by hand. Run after changing the demo data or
the engine:  python scripts/generate_examples.py
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from navigator.core.timeutil import parse_as_of  # noqa: E402
from navigator.demo.dataset import build_demo_artifacts, build_demo_records  # noqa: E402
from navigator.matching.engine import MatchOptions, match_records  # noqa: E402
from navigator.reference import load_institutions  # noqa: E402

AS_OF = "2026-10-07"
REQUESTS = {
    "1_supported_match": {
        "profile": {"indigenous_identity": ["metis"], "institution_id": "demo_college", "education_level": "undergraduate"},
        "as_of": AS_OF, "limit": 100,
    },
    "2_needs_clarification": {
        "profile": {"indigenous_identity": ["inuit"], "institution_id": "demo_college", "education_level": "undergraduate"},
        "as_of": AS_OF, "limit": 100,
    },
    "3_shared_application": {
        "profile": {"indigenous_identity": ["inuit"], "residence_province": "BC", "education_level": "undergraduate"},
        "as_of": AS_OF, "group_by_application": True, "limit": 100,
    },
}
FOCUS = {"1_supported_match": ["demo_supported_award"], "2_needs_clarification": ["demo_clarification_award"],
         "3_shared_application": ["demo_shared_application_a", "demo_shared_application_b", "demo_shared_application_exception"]}


def main() -> None:
    institutions = load_institutions(ROOT / "data" / "reference" / "institutions.yaml")
    as_of = parse_as_of(AS_OF)
    with tempfile.TemporaryDirectory() as tmp:
        records = build_demo_records(build_demo_artifacts(Path(tmp), as_of))
    records = [dict(r, last_verified_at="2026-10-07T12:00:00Z") for r in records]
    (ROOT / "examples" / "requests").mkdir(parents=True, exist_ok=True)
    (ROOT / "examples" / "expected").mkdir(parents=True, exist_ok=True)
    for name, body in REQUESTS.items():
        (ROOT / "examples" / "requests" / f"{name}.json").write_text(json.dumps(body, indent=2) + "\n", encoding="utf-8")
        options = MatchOptions(as_of=as_of, group_by_application=body.get("group_by_application", False), limit=body["limit"])
        response = match_records(records, body["profile"], options, institutions.resolve, data_mode="demo")
        focus = set(FOCUS[name])
        if response["results"] is not None:
            excerpt = [i for i in response["results"] if i["opportunity_id"] in focus]
        else:
            excerpt = [g for g in response["groups"] if g["group_id"] == "demo_foundation_shared_form"
                       or any(m["opportunity_id"] in focus for m in g["members"])]
        expected = {"note": "Excerpt of a real engine run on SYNTHETIC demo data (data_mode=demo); not real funding.",
                    "data_mode": response["data_mode"], "as_of": response["as_of"],
                    "total": response["total"], "total_groups": response["total_groups"],
                    "results" if response["results"] is not None else "groups": excerpt}
        (ROOT / "examples" / "expected" / f"{name}.response.json").write_text(
            json.dumps(expected, indent=2, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
        print("wrote", name)


if __name__ == "__main__":
    main()
