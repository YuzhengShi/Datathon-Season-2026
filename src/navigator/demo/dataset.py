"""Builds the synthetic snapshots and the demo opportunity records.

The records are *curated with evidence*: each quote is located in the extracted text of a
stored synthetic snapshot, so evidence ids, locators and hashes are real. Records are marked
``is_demo`` / ``extraction_method=demo_synthetic`` and are never real funding information.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from navigator import SCHEMA_VERSION
from navigator.core.timeutil import canonical_deadline_utc, format_utc
from navigator.demo import content as C
from navigator.ingestion.builder import Q, SnapshotView, attach_evidence, finalize
from navigator.ingestion.snapshots import SnapshotStore
from navigator.ingestion.text import EXTRACTOR_NAME, EXTRACTOR_VERSION, extract

PROVIDERS = {
    "college": {"id": "demo_college", "name": "Demo College (synthetic)", "donor_name": None},
    "foundation": {"id": "demo_foundation", "name": "Demo Foundation (synthetic)", "donor_name": None},
    "regional": {
        "id": "demo_regional_authority",
        "name": "Demo Regional Authority (synthetic)",
        "donor_name": None,
    },
}
PORTAL = "https://demo.invalid/college/portal"
FOUNDATION_APPLY = "https://demo.invalid/foundation/apply"
SHARED_FORM = "https://demo.invalid/foundation/shared-form"
REGIONAL_CONTACT = "https://demo.invalid/regional/contact"
SHARED_GROUP = "demo_foundation_shared_form"
_UNSET: Any = object()

DEMO_SOURCES = [
    {
        "source_id": p.source_id,
        "url": p.url,
        "provider_id": PROVIDERS[p.key]["id"],
        "provider_name": PROVIDERS[p.key]["name"],
        "role": p.role,
        "parser": "demo_catalog",
        "language": "en",
        "access_status": "synthetic",
    }
    for p in C.PAGES
] + [
    {
        "source_id": C.GUIDE_SOURCE_ID,
        "url": C.GUIDE_URL,
        "provider_id": "demo_foundation",
        "provider_name": PROVIDERS["foundation"]["name"],
        "role": "synthetic_guide",
        "parser": "demo_catalog",
        "language": "en",
        "access_status": "synthetic",
    },
    {
        "source_id": C.SCANNED_SOURCE_ID,
        "url": C.SCANNED_URL,
        "provider_id": "demo_foundation",
        "provider_name": PROVIDERS["foundation"]["name"],
        "role": "synthetic_scanned_notice",
        "parser": "demo_catalog",
        "language": "en",
        "access_status": "synthetic",
    },
]


@dataclass
class DemoArtifacts:
    snaps: dict[str, SnapshotView]
    extraction_status: dict[str, str]
    fetched_at: str
    notes: dict[str, str | None] = field(default_factory=dict)


def build_demo_artifacts(root: Path, as_of: datetime) -> DemoArtifacts:
    """Write synthetic raw files + extracted text under ``root`` (idempotent, content-addressed)."""
    store = SnapshotStore(root)
    fetched = format_utc(as_of)
    snaps: dict[str, SnapshotView] = {}
    status: dict[str, str] = {}
    notes: dict[str, str | None] = {}

    def add(key: str, source_id: str, url: str, data: bytes, media: str, role: str, modified: str | None) -> None:
        raw = store.save_raw(data, media)
        doc = extract(data, media, url)
        stored = store.save_text(raw.raw_sha256, doc.text, EXTRACTOR_NAME, EXTRACTOR_VERSION)
        status[key], notes[key] = doc.status, doc.note
        snaps[key] = SnapshotView(
            key,
            source_id,
            url,
            media,
            raw.snapshot_id,
            raw.raw_sha256,
            raw.raw_path,
            stored.text_sha256,
            stored.text_path,
            fetched,
            doc.text,
            role,
            modified,
            None,
        )

    for page in C.PAGES:
        add(
            page.key,
            page.source_id,
            page.url,
            C.render_html(page),
            "text/html",
            page.role,
            f"{page.modified}T00:00:00Z",
        )
    add("guide", C.GUIDE_SOURCE_ID, C.GUIDE_URL, C.render_guide_pdf(), "application/pdf", "synthetic_guide", None)
    add(
        "scanned",
        C.SCANNED_SOURCE_ID,
        C.SCANNED_URL,
        C.render_scanned_pdf(),
        "application/pdf",
        "synthetic_scanned_notice",
        None,
    )
    return DemoArtifacts(snaps, status, fetched, notes)


# ----------------------------------------------------------------- tiny record-building DSL


def _q(x: Any) -> Any:
    return Q(x) if isinstance(x, str) else x


def pred(field_: str, op: str, value: Any, *quotes: Any, scale: str | None = None) -> dict:
    node: dict = {
        "type": "predicate",
        "field": field_,
        "op": op,
        "value": value,
        "evidence_ids": [_q(q) for q in quotes],
    }
    if scale:
        node["scale"] = scale
    return node


def ident(quote: str) -> dict:
    return pred("indigenous_identity", "overlaps", ["first_nations", "inuit", "metis"], quote)


def group(mode: str, *children: dict) -> dict:
    return {"type": mode, "children": list(children)}


def unknown(reason: str, *quotes: Any) -> dict:
    return {"type": "unknown", "reason": reason, "evidence_ids": [_q(q) for q in quotes]}


def elig(
    mandatory: list,
    preferences: list | None = None,
    unstructured: list | None = None,
    funder_conditions: list | None = None,
) -> dict:
    out = {
        "mandatory": mandatory,
        "preferences": preferences or [],
        "unstructured": unstructured or [],
        "rules_version": None,
    }
    if funder_conditions:
        out["funder_conditions"] = funder_conditions
    return out


def amt(kind: str, raw: str, quote: str | None = None, *, unit: str = "unspecified", **numbers: str) -> dict:
    amount: dict = {
        "kind": kind,
        "currency": "CAD" if numbers else None,
        "unit": unit,
        "renewable": None,
        "raw_text": raw,
        "evidence_ids": [Q(quote)] if quote else [],
    }
    amount.update(numbers)
    return amount


_PRECISION = {"date": "day", "datetime": "minute", "annual_rule": "month_day"}


def dl(
    kind: str,
    raw: str,
    quote: str,
    *,
    date: str | None = None,
    time: str | None = None,
    tz: str | None = None,
    month: int | None = None,
    day: int | None = None,
) -> dict:
    d: dict = {"kind": kind, "raw_text": raw, "precision": _PRECISION.get(kind, "none"), "evidence_ids": [Q(quote)]}
    for key, value in (
        ("date", date),
        ("local_time", time),
        ("timezone", tz),
        ("annual_month", month),
        ("annual_day", day),
    ):
        if value is not None:
            d[key] = value
    if kind in {"date", "datetime"}:
        exact = canonical_deadline_utc(d)
        if exact is not None:
            d["deadline_at_utc"] = exact
    return d


def cyc(
    key: str,
    label: str,
    deadlines: list,
    amount: dict,
    eligibility: dict,
    *,
    starts: str | None = None,
    ends: str | None = None,
    window_quote: str | None = None,
    group_id: Any = _UNSET,
    group_quotes: list | None = None,
) -> dict:
    cycle: dict = {
        "cycle_key": key,
        "label_raw": label,
        "starts_on": starts,
        "ends_on": ends,
        "deadlines": deadlines,
        "amount": amount,
        "eligibility": eligibility,
    }
    if window_quote:
        cycle["window_evidence_ids"] = [Q(window_quote)]
    if group_id is not _UNSET:
        cycle["application_group_id"] = group_id
        cycle["group_evidence_ids"] = [_q(q) for q in (group_quotes or [])]
    return cycle


def route(
    url: str | None,
    kind: str,
    quote: str | list,
    *,
    contact: str | None = None,
    group_id: str | None = None,
    label: str | None = None,
    instructions: str | None = None,
) -> dict:
    quotes = quote if isinstance(quote, list) else [quote]
    return {
        "url": url,
        "route_type": kind,
        "instructions": instructions,
        "contact_url": contact,
        "group_id": group_id,
        "group_label": label,
        "evidence_ids": [_q(q) for q in quotes],
    }


def doc(kind: str, label: str, quote: Any) -> dict:
    return {"type": kind, "label": label, "required": True, "evidence_ids": [_q(quote)]}


def portal_route() -> dict:
    return route(PORTAL, "institution_portal", C.APPLY_PORTAL, instructions="Apply in the college awards portal.")


def foundation_route() -> dict:
    return route(
        FOUNDATION_APPLY, "online_application", C.APPLY_FOUNDATION, instructions="Apply on the foundation website."
    )


def build_demo_records(art: DemoArtifacts) -> list[dict]:
    """The 25 demo opportunities (see docs/DATA_MODEL.md for the case each one covers)."""
    fetched = art.fetched_at
    out: list[dict] = []

    def add(
        page: C.Page,
        anchor: str,
        rid: str,
        title: str,
        summary: str,
        application: dict,
        cycles: list,
        documents: list | None = None,
        otype: str = "award",
    ) -> None:
        record = {
            "schema_version": SCHEMA_VERSION,
            "id": rid,
            "source_record_key": f"demo_catalog:{page.key}#{anchor}",
            "title": title,
            "opportunity_type": otype,
            "provider": PROVIDERS[page.key],
            "official_url": f"{page.url}#{anchor}",
            "application": application,
            "summary": summary,
            "cycles": cycles,
            "required_documents": documents or [],
            "evidence": [],
            "source_refs": [],
            "review_status": "machine_checked",
            "publication_status": "published",
            "extraction_method": "demo_synthetic",
            "last_fetched_at": fetched,
            "last_verified_at": None,
            "content_fingerprint": "sha256:" + "0" * 64,
            "is_demo": True,
        }
        out.append(finalize(attach_evidence(record, art.snaps, page.key)))

    pac = "Pacific Time"
    college = C.COLLEGE
    # 1 - everything is stated and checkable -> potential_fit
    add(
        college,
        "supported-award",
        "demo_supported_award",
        "Demo Supported Award",
        "Synthetic award for Indigenous undergraduate students at Demo College.",
        portal_route(),
        [
            cyc(
                "2026-27",
                "2026-27",
                [
                    dl(
                        "datetime",
                        "November 15, 2026 at 11:59 p.m. Pacific Time",
                        "The deadline is November 15, 2026 at 11:59 p.m. Pacific Time.",
                        date="2026-11-15",
                        time="23:59",
                        tz=pac,
                    )
                ],
                amt(
                    "fixed",
                    "$2,500 CAD, awarded once per year",
                    "Value: $2,500 CAD, awarded once per year.",
                    unit="per_year",
                    fixed="2500",
                ),
                elig(
                    [
                        ident("self-identify as First Nations, Inuit or Métis"),
                        pred("institution_id", "eq", "demo_college", "be enrolled at Demo College"),
                        pred("education_level", "in", ["undergraduate"], "be in an undergraduate program"),
                    ]
                ),
                starts="2026-09-01",
                window_quote="Applications open September 1, 2026.",
            )
        ],
        [
            doc("essay", "short essay", "a short essay"),
            doc("proof_of_enrolment", "proof of enrolment", "proof of enrolment"),
        ],
    )
    # 2 - one profile condition (study status) is needed -> needs_information
    add(
        college,
        "clarification-award",
        "demo_clarification_award",
        "Demo Clarification Award",
        "Synthetic award that asks whether the student studies full-time.",
        portal_route(),
        [
            cyc(
                "2026-27",
                "2026-27",
                [
                    dl(
                        "date",
                        "December 1, 2026 (Pacific Time)",
                        "close on December 1, 2026 (Pacific Time)",
                        date="2026-12-01",
                        tz=pac,
                    )
                ],
                amt("fixed", "$1,000 CAD", "Value: $1,000 CAD.", fixed="1000"),
                elig(
                    [
                        ident("self-identify as First Nations, Inuit or Métis"),
                        pred("institution_id", "eq", "demo_college", "are enrolled full-time at Demo College"),
                        pred("study_status", "eq", "full_time", "are enrolled full-time at Demo College"),
                    ]
                ),
                starts="2026-10-01",
                window_quote="Applications open October 1, 2026",
            )
        ],
    )
    # 4 - FN registration / Metis citizenship / Inuit beneficiary: broad identity is not enough
    add(
        college,
        "first-nations-registered-award",
        "demo_first_nations_registered_award",
        "Demo First Nations Registration Award",
        "Synthetic award that requires First Nations registration, not just self-identification.",
        portal_route(),
        [
            cyc(
                "2026-27",
                "2026-27",
                [
                    dl(
                        "date",
                        "January 31, 2027 (Pacific Time)",
                        "The application deadline is January 31, 2027 (Pacific Time).",
                        date="2027-01-31",
                        tz=pac,
                    )
                ],
                amt("fixed", "$1,500 CAD", "Value: $1,500 CAD.", fixed="1500"),
                elig(
                    [
                        pred(
                            "first_nations_registered",
                            "eq",
                            True,
                            "must be registered First Nations persons under the Indian Act",
                        )
                    ]
                ),
            )
        ],
    )
    add(
        college,
        "metis-citizen-award",
        "demo_metis_citizen_award",
        "Demo Métis Citizenship Award",
        "Synthetic award for citizens of a named Métis authority.",
        portal_route(),
        [
            cyc(
                "2026-27",
                "2026-27",
                [
                    dl(
                        "date",
                        "February 15, 2027 (Pacific Time)",
                        "The application deadline is February 15, 2027 (Pacific Time).",
                        date="2027-02-15",
                        tz=pac,
                    )
                ],
                amt("fixed", "$1,200 CAD", "Value: $1,200 CAD.", fixed="1200"),
                elig(
                    [
                        pred("metis_citizen", "eq", True, "must be citizens of the Demo Métis Authority"),
                        pred(
                            "metis_org", "in", ["Demo Métis Authority"], "must be citizens of the Demo Métis Authority"
                        ),
                    ]
                ),
            )
        ],
    )
    add(
        college,
        "inuit-beneficiary-award",
        "demo_inuit_beneficiary_award",
        "Demo Inuit Beneficiary Award",
        "Synthetic award for beneficiaries of a named land claim agreement.",
        portal_route(),
        [
            cyc(
                "2026-27",
                "2026-27",
                [
                    dl(
                        "date",
                        "February 28, 2027 (Pacific Time)",
                        "The application deadline is February 28, 2027 (Pacific Time).",
                        date="2027-02-28",
                        tz=pac,
                    )
                ],
                amt("fixed", "$1,800 CAD", "Value: $1,800 CAD.", fixed="1800"),
                elig(
                    [
                        pred(
                            "inuit_beneficiary",
                            "eq",
                            True,
                            "must be beneficiaries of the Demo Inuit Land Claim Agreement",
                        )
                    ]
                ),
            )
        ],
    )
    # 5 - home community, residence and school province are different fields
    add(
        college,
        "residence-community-award",
        "demo_residence_community_award",
        "Demo Residence and Community Award",
        "Synthetic award that separates home community, province of residence and school province.",
        portal_route(),
        [
            cyc(
                "2026-27",
                "2026-27",
                [
                    dl(
                        "date",
                        "March 15, 2027 (Pacific Time)",
                        "The application deadline is March 15, 2027 (Pacific Time).",
                        date="2027-03-15",
                        tz=pac,
                    )
                ],
                amt("fixed", "$900 CAD", "Value: $900 CAD.", fixed="900"),
                elig(
                    [
                        pred("home_community", "in", ["Demo First Nation"], "belong to Demo First Nation"),
                        pred("residence_province", "eq", "BC", "currently live in British Columbia"),
                        pred("institution_province", "eq", "AB", "attend a school located in Alberta"),
                    ]
                ),
            )
        ],
    )
    # 6 - a preference never becomes a disqualifier
    add(
        college,
        "preference-award",
        "demo_preference_award",
        "Demo Environmental Preference Award",
        "Synthetic award with a stated preference for environmental science students.",
        portal_route(),
        [
            cyc(
                "2026-27",
                "2026-27",
                [
                    dl(
                        "date",
                        "April 1, 2027 (Pacific Time)",
                        "The application deadline is April 1, 2027 (Pacific Time).",
                        date="2027-04-01",
                        tz=pac,
                    )
                ],
                amt("fixed", "$2,000 CAD", "Value: $2,000 CAD.", fixed="2000"),
                elig(
                    [
                        ident("open to First Nations, Inuit and Métis undergraduate students"),
                        pred(
                            "education_level",
                            "in",
                            ["undergraduate"],
                            "open to First Nations, Inuit and Métis undergraduate students",
                        ),
                    ],
                    preferences=[
                        pred(
                            "program_field",
                            "in",
                            ["environmental science"],
                            "Preference is given to applicants studying environmental science.",
                        )
                    ],
                ),
            )
        ],
    )
    # 7 - OR rules: any branch can satisfy; unknown + false stays unknown
    add(
        college,
        "or-rule-award",
        "demo_or_rule_award",
        "Demo Either-Or Award",
        "Synthetic award open to members of a community or students of the college.",
        portal_route(),
        [
            cyc(
                "2026-27",
                "2026-27",
                [
                    dl(
                        "date",
                        "April 15, 2027 (Pacific Time)",
                        "The application deadline is April 15, 2027 (Pacific Time).",
                        date="2027-04-15",
                        tz=pac,
                    )
                ],
                amt("fixed", "$1,100 CAD", "Value: $1,100 CAD.", fixed="1100"),
                elig(
                    [
                        ident("self-identify as First Nations, Inuit or Métis"),
                        group(
                            "any",
                            pred(
                                "home_community",
                                "in",
                                ["Demo First Nation"],
                                "either belong to Demo First Nation or attend Demo College",
                            ),
                            pred(
                                "institution_id",
                                "eq",
                                "demo_college",
                                "either belong to Demo First Nation or attend Demo College",
                            ),
                        ),
                    ]
                ),
            )
        ],
    )
    add(
        college,
        "or-unknown-branch-award",
        "demo_or_unknown_branch_award",
        "Demo Either-Or Local Award",
        "Synthetic award where one OR branch is decided by a local office.",
        portal_route(),
        [
            cyc(
                "2026-27",
                "2026-27",
                [
                    dl(
                        "date",
                        "April 30, 2027 (Pacific Time)",
                        "The application deadline is April 30, 2027 (Pacific Time).",
                        date="2027-04-30",
                        tz=pac,
                    )
                ],
                amt("fixed", "$700 CAD", "Value: $700 CAD.", fixed="700"),
                elig(
                    [
                        ident("self-identify as First Nations, Inuit or Métis"),
                        group(
                            "any",
                            pred("institution_id", "eq", "demo_college", "either attend Demo College"),
                            unknown(
                                "Another requirement is decided by the local band office",
                                "meet another requirement that the local band office decides",
                            ),
                        ),
                    ]
                ),
            )
        ],
    )

    # 9 - an old cycle is kept next to the current one
    def same_elig(q: str) -> dict:
        return elig([ident(q), pred("institution_id", "eq", "demo_college", q)])

    q_multi = "self-identified First Nations, Inuit or Métis students at Demo College"
    add(
        college,
        "multi-cycle-award",
        "demo_multi_cycle_award",
        "Demo Two-Cycle Award",
        "Synthetic award with a closed historical intake and a current intake.",
        portal_route(),
        [
            cyc(
                "2019-20",
                "2019-20",
                [
                    dl(
                        "date",
                        "March 1, 2020 (Pacific Time)",
                        "The 2019-20 intake closed on March 1, 2020 (Pacific Time).",
                        date="2020-03-01",
                        tz=pac,
                    )
                ],
                amt("fixed", "$800 CAD in each intake", "Value: $800 CAD in each intake.", fixed="800"),
                same_elig(q_multi),
            ),
            cyc(
                "2026-27",
                "2026-27",
                [
                    dl(
                        "date",
                        "May 1, 2027 (Pacific Time)",
                        "closes on May 1, 2027 (Pacific Time)",
                        date="2027-05-01",
                        tz=pac,
                    )
                ],
                amt("fixed", "$800 CAD in each intake", "Value: $800 CAD in each intake.", fixed="800"),
                same_elig(q_multi),
                starts="2026-09-15",
                window_quote="opens September 15, 2026",
            ),
        ],
    )
    add(
        college,
        "college-directory",
        "demo_award_collection",
        "Demo College Awards Directory",
        "Synthetic navigation page that lists the awards above; it is not an award itself.",
        route(None, "unknown", []),
        [cyc("unspecified", "not stated", [], amt("unspecified", "not applicable"), elig([]))],
        otype="award_collection",
    )

    foundation = C.FOUNDATION
    shared_quotes = [
        "Apply with the Demo Foundation Shared Application Form.",
        "The Demo Foundation Shared Application Form covers both the Demo Northern Scholarship and the Demo Coastal Bursary.",
        Q(
            "Only one shared form is needed for the Northern Scholarship and the Coastal Bursary.",
            snap="guide",
            pdf_page=2,
        ),
    ]

    def shared_cycle_deadline() -> list:
        return [
            dl(
                "date",
                "November 30, 2026 (Pacific Time)",
                "The shared form is due November 30, 2026 (Pacific Time).",
                date="2026-11-30",
                tz=pac,
            )
        ]

    shared_docs = lambda: [  # noqa: E731
        doc("transcript", "official transcript", Q("an official transcript", snap="guide", pdf_page=1)),
        doc(
            "community_support_letter",
            "community support letter",
            Q("a community support letter", snap="guide", pdf_page=1),
        ),
    ]
    # 3 - two awards share one form but have different eligibility; one is explicitly independent
    add(
        foundation,
        "northern-scholarship",
        "demo_shared_application_a",
        "Demo Northern Scholarship",
        "Synthetic award applied for with the shared foundation form.",
        route(
            SHARED_FORM,
            "shared_application_form",
            shared_quotes,
            group_id=SHARED_GROUP,
            label="Demo Foundation Shared Application Form",
            instructions="Use the shared form.",
        ),
        [
            cyc(
                "2026-27",
                "2026-27",
                shared_cycle_deadline(),
                amt("fixed", "$3,000 CAD", "Value: $3,000 CAD.", fixed="3000"),
                elig(
                    [
                        ident("First Nations, Inuit or Métis students"),
                        pred("residence_province", "in", ["BC", "YT"], "live in British Columbia or Yukon"),
                    ]
                ),
                starts="2026-10-01",
                window_quote="Applications open October 1, 2026.",
            )
        ],
        shared_docs(),
    )
    add(
        foundation,
        "coastal-bursary",
        "demo_shared_application_b",
        "Demo Coastal Bursary",
        "Synthetic bursary applied for with the shared foundation form.",
        route(
            SHARED_FORM,
            "shared_application_form",
            shared_quotes,
            group_id=SHARED_GROUP,
            label="Demo Foundation Shared Application Form",
            instructions="Use the shared form.",
        ),
        [
            cyc(
                "2026-27",
                "2026-27",
                shared_cycle_deadline(),
                amt("fixed", "$1,500 CAD", "Value: $1,500 CAD.", fixed="1500"),
                elig(
                    [
                        ident("First Nations, Inuit or Métis students"),
                        pred(
                            "education_level", "in", ["college", "trades_vocational"], "in a college or trades program"
                        ),
                    ]
                ),
                starts="2026-10-01",
                window_quote="Applications open October 1, 2026.",
            )
        ],
        shared_docs(),
    )
    add(
        foundation,
        "leadership-award",
        "demo_shared_application_exception",
        "Demo Leadership Award",
        "Synthetic award from the same foundation that is explicitly NOT part of the shared form.",
        route(
            FOUNDATION_APPLY,
            "independent_application",
            "The Demo Leadership Award is not part of the shared application. Apply separately.",
            instructions="Apply separately from the shared form.",
        ),
        [
            cyc(
                "2026-27",
                "2026-27",
                [
                    dl(
                        "date",
                        "December 10, 2026 (Pacific Time)",
                        "The separate application is due December 10, 2026 (Pacific Time).",
                        date="2026-12-10",
                        tz=pac,
                    )
                ],
                amt("fixed", "$2,200 CAD", "Value: $2,200 CAD.", fixed="2200"),
                elig(
                    [
                        ident("First Nations, Inuit or Métis students"),
                        pred("gpa", "gte", "3.0", "a GPA of at least 3.0 on a 4.0 scale", scale="4.0"),
                    ]
                ),
                starts="2026-10-01",
                window_quote="Applications open October 1, 2026.",
            )
        ],
    )

    # 8 - amounts that must not be read as "what I will get"
    def mar1() -> list:
        return [
            dl(
                "date",
                "March 1, 2027 (Pacific Time)",
                "The application deadline is March 1, 2027 (Pacific Time).",
                date="2027-03-01",
                tz=pac,
            )
        ]

    start_oct = dict(starts="2026-10-01", window_quote="Applications open October 1, 2026.")
    add(
        foundation,
        "discretionary-award",
        "demo_amount_unknown_award",
        "Demo Discretionary Award",
        "Synthetic award whose value is not published (unknown, not zero).",
        foundation_route(),
        [
            cyc(
                "2026-27",
                "2026-27",
                mar1(),
                amt(
                    "unspecified",
                    "set each year by the selection committee and is not published",
                    "set each year by the selection committee and is not published",
                ),
                elig([ident("First Nations, Inuit or Métis students")]),
                **start_oct,
            )
        ],
    )
    add(
        foundation,
        "community-pool-award",
        "demo_pooled_total_award",
        "Demo Community Pool Award",
        "Synthetic award that publishes only a combined yearly total for all recipients.",
        foundation_route(),
        [
            cyc(
                "2026-27",
                "2026-27",
                mar1(),
                amt(
                    "pooled_total",
                    "a combined total of $50,000 CAD each year among all recipients",
                    "The Demo Foundation distributes a combined total of $50,000 CAD each year among all recipients.",
                    unit="per_year",
                    pooled_total="50000",
                ),
                elig([ident("First Nations, Inuit or Métis students")]),
                **start_oct,
            )
        ],
    )
    add(
        foundation,
        "need-based-award",
        "demo_maximum_award",
        "Demo Need-Based Maximum Award",
        "Synthetic award that states only a maximum and an unstructured need condition.",
        foundation_route(),
        [
            cyc(
                "2026-27",
                "2026-27",
                mar1(),
                amt(
                    "maximum",
                    "up to $5,000 CAD",
                    "Awards of up to $5,000 CAD are available.",
                    unit="per_student",
                    maximum="5000",
                ),
                elig(
                    [ident("First Nations, Inuit or Métis students")],
                    unstructured=[
                        {
                            "text": "Applicants must show demonstrated financial need.",
                            "evidence_ids": [Q("Applicants must show demonstrated financial need.")],
                        }
                    ],
                ),
                **start_oct,
            )
        ],
    )

    regional = C.REGIONAL
    all_q = "First Nations, Inuit or Métis students"
    sep1 = dict(starts="2026-09-01", window_quote="Applications open September 1, 2026")
    # 9 - deadline semantics
    add(
        regional,
        "heritage-award",
        "demo_deadline_2020_award",
        "Demo Heritage Award (historical)",
        "Synthetic award whose only known deadline is in 2020.",
        route(None, "unknown", []),
        [
            cyc(
                "unspecified",
                "not stated",
                [
                    dl(
                        "date",
                        "March 1, 2020 (Pacific Time)",
                        "The deadline was March 1, 2020 (Pacific Time).",
                        date="2020-03-01",
                        tz=pac,
                    )
                ],
                amt("fixed", "$600 CAD", "Value: $600 CAD.", fixed="600"),
                elig([ident(all_q)]),
            )
        ],
    )
    add(
        regional,
        "annual-march-award",
        "demo_annual_rule_award",
        "Demo Annual March Award",
        "Synthetic award with a month-and-day rule but no confirmed cycle.",
        route(None, "unknown", []),
        [
            cyc(
                "unspecified",
                "not stated",
                [
                    dl(
                        "annual_rule",
                        "every year on March 1",
                        "Applications are due every year on March 1.",
                        month=3,
                        day=1,
                    )
                ],
                amt("fixed", "$750 CAD", "Value: $750 CAD.", fixed="750"),
                elig([ident(all_q)]),
            )
        ],
    )
    add(
        regional,
        "two-round-award",
        "demo_multi_deadline_award",
        "Demo Two-Round Award",
        "Synthetic award considered in two rounds; it is still one application.",
        route(
            None,
            "unknown",
            "This is one application; the two dates are consideration rounds, not separate applications.",
            instructions="One application covers both rounds.",
        ),
        [
            cyc(
                "2026-27",
                "2026-27",
                [
                    dl(
                        "date",
                        "January 15, 2027",
                        "considered in two rounds: January 15, 2027",
                        date="2027-01-15",
                        tz=pac,
                    ),
                    dl(
                        "date",
                        "June 15, 2027 (Pacific Time)",
                        "June 15, 2027 (Pacific Time)",
                        date="2027-06-15",
                        tz=pac,
                    ),
                ],
                amt("fixed", "$950 CAD", "Value: $950 CAD.", fixed="950"),
                elig([ident(all_q)]),
                starts="2026-10-01",
                window_quote="Applications open October 1, 2026",
            )
        ],
    )
    add(
        regional,
        "community-administered-award",
        "demo_local_admin_deadline_award",
        "Demo Community Administered Award",
        "Synthetic award whose deadline and eligibility are set by each community administrator.",
        route(
            None,
            "contact_administrator",
            "Contact your local education office.",
            contact=REGIONAL_CONTACT,
            instructions="Contact your local education office.",
        ),
        [
            cyc(
                "unspecified",
                "not stated",
                [
                    dl(
                        "local_administrator",
                        "set by each community education administrator",
                        "Deadlines are set by each community education administrator.",
                    )
                ],
                amt("unspecified", "not stated"),
                elig(
                    [
                        unknown(
                            "Eligibility is determined by each community education administrator",
                            "Eligibility: determined by each community education administrator.",
                        )
                    ]
                ),
            )
        ],
    )
    # 10 - timezone handling
    add(
        regional,
        "no-timezone-award",
        "demo_tz_unknown_award",
        "Demo No-Timezone Award",
        "Synthetic award with a clock time but no timezone.",
        route(None, "unknown", []),
        [
            cyc(
                "2026-27",
                "2026-27",
                [
                    dl(
                        "datetime",
                        "October 9, 2026 at 5:00 p.m.",
                        "close October 9, 2026 at 5:00 p.m.",
                        date="2026-10-09",
                        time="17:00",
                    )
                ],
                amt("fixed", "$400 CAD", "Value: $400 CAD.", fixed="400"),
                elig([ident(all_q)]),
                **sep1,
            )
        ],
    )
    add(
        regional,
        "eastern-time-award",
        "demo_tz_dst_boundary_award",
        "Demo Eastern Time Award",
        "Synthetic award that closes inside the repeated hour when daylight saving time ends.",
        route(None, "unknown", []),
        [
            cyc(
                "2026-27",
                "2026-27",
                [
                    dl(
                        "datetime",
                        "November 1, 2026 at 1:30 a.m. Eastern Time",
                        "close November 1, 2026 at 1:30 a.m. Eastern Time.",
                        date="2026-11-01",
                        time="01:30",
                        tz="Eastern Time",
                    )
                ],
                amt("fixed", "$450 CAD", "Value: $450 CAD.", fixed="450"),
                elig([ident(all_q)]),
                **sep1,
            )
        ],
    )
    add(
        regional,
        "date-only-award",
        "demo_date_only_deadline_award",
        "Demo Date-Only Award",
        "Synthetic award with a date-only deadline (open through the end of that day).",
        route(None, "unknown", []),
        [
            cyc(
                "2026-27",
                "2026-27",
                [
                    dl(
                        "date",
                        "October 7, 2026 (Pacific Time)",
                        "close October 7, 2026 (Pacific Time).",
                        date="2026-10-07",
                        tz=pac,
                    )
                ],
                amt("fixed", "$350 CAD", "Value: $350 CAD.", fixed="350"),
                elig([ident(all_q)]),
                **sep1,
            )
        ],
    )
    # 12 - a legitimate funding channel with insufficient source rules
    add(
        regional,
        "regional-funding",
        "demo_funding_channel",
        "Demo Regional Education Funding",
        "Synthetic funding channel: rules are set locally, so students must contact the office.",
        route(
            None,
            "contact_administrator",
            "Contact the education office to apply.",
            contact=REGIONAL_CONTACT,
            instructions="Contact the regional education office.",
        ),
        [
            cyc(
                "unspecified",
                "not stated",
                [],
                amt("unspecified", "not stated"),
                elig(
                    [
                        unknown(
                            "Funding decisions and eligibility are made locally",
                            "Funding decisions and eligibility are made locally.",
                        )
                    ],
                    funder_conditions=[
                        {
                            "text": "Funding goes to First Nations education authorities that submit an annual education plan.",
                            "evidence_ids": [
                                Q(
                                    "Funding is provided to First Nations education authorities that submit an annual "
                                    "education plan to the Demo Regional Authority."
                                )
                            ],
                        }
                    ],
                ),
            )
        ],
        otype="funding_channel",
    )
    return sorted(out, key=lambda r: r["id"])
