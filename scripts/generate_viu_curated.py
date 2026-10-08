"""Write data/curated/prov_viu_ca_financialaid_awards_aspx.yaml from the stored VIU awards page.

VIU publishes one page with every award (a heading, "$1,000 | 1 available", then the conditions) and says that ONE profile in the student
record covers all of them. This script selects the awards whose conditions are written for Indigenous students and turns each into a curated
record. Nothing is invented: every quote is cut verbatim from the stored page text, an award is "for Indigenous students" only when its
conditions open with "Available to ... Indigenous/Aboriginal/First Nations ...", and a preference stays a preference. Anything else in the
conditions (programme, year, residence, need, merit) is kept as the provider's own words and as one rule only VIU can judge.

    python scripts/generate_viu_curated.py            # dry run: prints the classification
    python scripts/generate_viu_curated.py --write    # writes the curated file
"""

from __future__ import annotations

import json
import pathlib
import re
import sys

import yaml

from navigator.core.contract import ROUTE_TYPES
from navigator.core.ids import slugify
from navigator.ingestion.adapters.isc_detail import quote_prefix

SOURCE_ID = "prov_viu_ca_financialaid_awards_aspx"
TERMS = r"(?:indigenous|aboriginal|first nations)"
REQUIRES = re.compile(rf"Available to (?:[\w'-]+[ ,]+){{0,4}}?{TERMS}\b", re.I)
PREFERENCE = re.compile(
    rf"[^.]*\b(?:preference|priority)\b[^.]*{TERMS}\b[^.]*\.|[^.]*{TERMS}\b[^.]*\b(?:preference|priority)\b[^.]*\.",
    re.I,
)
AMOUNT = re.compile(r"\$[\d,]+(?: \| \d+ available)?")
# the three awards the ISC directory also lists: the provider's record replaces the directory one (same id)
SAME_AS_DIRECTORY = {
    "Cummins Western Canada Dependability Award": "vancouver_island_university:isc_cummins_western_canada_dependability_award_vancouver_island_university",
    "Dennis Alphonse Memorial Scholarship": "vancouver_island_university:isc_dennis_alphonse_memorial_award_vancouver_island_university",
    "Elizabeth Newham Award": "vancouver_island_university:isc_elizabeth_newham_award_vancouver_island_university",
}


def load_page() -> list[str]:
    index = json.loads(pathlib.Path("data/discovery/fetch_index.json").read_text(encoding="utf-8"))
    entry = next(e for e in index["entries"].values() if e["source_id"] == SOURCE_ID)
    text = pathlib.Path("data", entry["text_path"]).read_text(encoding="utf-8")
    return [p.strip() for p in text.split("\n\n") if p.strip()]


def split_awards(paragraphs: list[str]) -> list[tuple[str, list[str]]]:
    awards, current = [], None
    for p in paragraphs:
        if p.startswith("### "):
            current = (p[4:].strip(), [])
            awards.append(current)
        elif p.startswith("## "):  # a new section of the page ends the previous award
            current = None
        elif current is not None:
            current[1].append(p)
    return awards


def classify(body: list[str]) -> tuple[str, str]:
    """('requires'|'prefers'|'skip', the verbatim text that decided it)."""
    description = [p for p in body if not p.startswith("#### ")]
    first = description[0] if description else ""
    m = REQUIRES.match(first)
    if m:
        return "requires", m.group(0)
    for p in description:
        pm = PREFERENCE.search(p)
        if pm:
            return "prefers", pm.group(0).strip()
    return "skip", ""


def main(write: bool) -> None:
    assert "institution_portal" in ROUTE_TYPES, "the record contract no longer has this route type"
    paragraphs = load_page()
    sab = next(p for p in paragraphs if p.startswith("The profile is open now on your VIU student record"))
    apr = next(p for p in paragraphs if p.startswith("April 30 (midnight)"))
    oct_ = next(p for p in paragraphs if p.startswith("October 30 (midnight)"))
    group = next(p for p in paragraphs if p.startswith("When you complete your SAB Profile"))
    records, report = [], []
    for name, body in split_awards(paragraphs):
        kind, decided = classify(body)
        if kind == "skip":
            continue
        heading = next((p for p in body if p.startswith("#### ")), "")
        amount_text = (AMOUNT.search(heading) or [None])[0] if heading else None
        description = [p for p in body if not p.startswith("#### ")]
        first = description[0]
        quote = quote_prefix(first, 300)
        mandatory = [
            {
                "type": "predicate",
                "field": "institution_id",
                "op": "eq",
                "value": "viu",
                "quotes": ["The profile is open now on your VIU student record"],
            },
        ]
        preferences = []
        if kind == "requires":
            mandatory.insert(
                0,
                {
                    "type": "predicate",
                    "field": "indigenous_identity",
                    "op": "overlaps",
                    "value": ["first_nations", "inuit", "metis"],
                    "quotes": [decided],
                },
            )
        else:
            preferences.append(
                {
                    "type": "predicate",
                    "field": "indigenous_identity",
                    "op": "overlaps",
                    "value": ["first_nations", "inuit", "metis"],
                    "quotes": [decided if len(decided) <= 300 else quote_prefix(decided, 300)],
                }
            )
        mandatory.append(
            {
                "type": "unknown",
                "reason": "VIU judges the other conditions in its description (programme, year of study, residence, need or merit)",
                "quotes": [quote],
            }
        )
        cycle = {
            "cycle_key": "unspecified",
            "label_raw": "profile deadline each year: April 30 for awards and scholarships",
            "application_group_id": "viu_sab_profile",
            "group_quotes": [group],
            "deadlines": [
                {
                    "kind": "annual_rule",
                    "annual_month": 4,
                    "annual_day": 30,
                    "raw_text": "April 30 (midnight)",
                    "quotes": [apr],
                }
            ],
            "amount": (
                {
                    "kind": "fixed",
                    "fixed": re.sub(r"[^\d]", "", amount_text.split("|")[0]),
                    "currency": "CAD",
                    "unit": "unspecified",
                    "raw_text": amount_text.split("|")[0].strip(),
                    "quotes": [amount_text],
                }
                if amount_text
                else {
                    "kind": "unspecified",
                    "currency": None,
                    "unit": "unspecified",
                    "raw_text": "not stated on the page",
                }
            ),
            "eligibility": {
                "mandatory": mandatory,
                "preferences": preferences,
                "unstructured": [
                    {"text": " ".join(description)[:1500], "quotes": [quote]},
                    {
                        "text": "Submit the scholarship, award and bursary profile by April 30 for awards and scholarships issued in September, or by October 30 for bursaries awarded in January.",
                        "quotes": [oct_],
                    },
                ],
            },
        }
        record = {
            "key": "viu-" + slugify(name, 60),
            "title": name,
            "opportunity_type": "award",
            "summary": f"Vancouver Island University award. {quote} One profile in your VIU student record covers every VIU award you are eligible for.",
            "application": {
                "route_type": "institution_portal",
                "url": "https://services.viu.ca/financial-aid-awards/scholarships-awards",
                "instructions": "Log in to your VIU student record, choose Finances, then the Scholarship, Award and Bursary profile.",
                "quotes": [sab],
            },
            "cycles": [cycle],
        }
        if name in SAME_AS_DIRECTORY:
            record["id"] = SAME_AS_DIRECTORY[name]
        records.append(record)
        report.append((kind, name, amount_text or "-", decided[:70]))
    for kind, name, amount, decided in report:
        print(f"{kind:<8} {amount:<22} {name[:62]:<62} | {decided}".encode("ascii", "backslashreplace").decode("ascii"))
    print(
        f"\n{len(records)} awards selected ({sum(1 for r in report if r[0] == 'requires')} for Indigenous students, {sum(1 for r in report if r[0] == 'prefers')} with a preference)"
    )
    missing = [n for n in SAME_AS_DIRECTORY if n not in {r["title"] for r in records}]
    print(
        "directory records that this page replaces:", len(SAME_AS_DIRECTORY) - len(missing), "| not selected:", missing
    )
    if write:
        header = (
            "# GENERATED by scripts/generate_viu_curated.py from the stored VIU awards page; every quote is verbatim from it.\n"
            "# Re-run the script after a fresh fetch; do not edit by hand.\n"
        )
        out = pathlib.Path("data/curated") / f"{SOURCE_ID}.yaml"
        out.write_text(
            header
            + yaml.safe_dump(
                {"source_id": SOURCE_ID, "records": records}, allow_unicode=True, sort_keys=False, width=100000
            ),
            encoding="utf-8",
            newline="\n",
        )
        print("wrote", out)


if __name__ == "__main__":
    main("--write" in sys.argv)
