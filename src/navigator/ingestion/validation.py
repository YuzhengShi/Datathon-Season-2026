"""Candidate-record validation: JSON Schema, semantics, evidence and cross-record checks.

Layers (every finding is an :class:`Issue` with a JSON-Pointer path):

1. structure - the JSON Schema from :mod:`navigator.core.contract`;
2. semantics - ids, URLs, statuses, deadlines, amounts, rule trees, application groups;
3. evidence  - coverage (every amount/date/rule/document/route needs evidence), field-path
   linkage, and (given an artifact root) hash recomputation and quote verification;
4. file level - UTF-8, one JSON object per line, duplicate ids / keys, conflicting groups.

A quote being found is *necessary, not sufficient*: the source-specific adapters and their
tests are what prove paragraph attribution, amount scope and rule semantics.
"""

from __future__ import annotations

import calendar
import json
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from navigator.core import contract
from navigator.core.evidence import verify_evidence_item, verify_source_ref
from navigator.core.fingerprint import compute_fingerprint
from navigator.core.ids import is_valid_id
from navigator.core.issues import Issue, has_errors, pointer_join
from navigator.core.jsonschema_lite import validate as validate_schema
from navigator.core.money import validate_amount
from navigator.core.timeutil import canonical_deadline_utc, parse_iso_datetime, resolve_timezone
from navigator.core.urlpolicy import canonicalize_url, check_url
from navigator.matching.rules import GroupNode, UnknownNode, iter_predicates, parse_eligibility

_SCHEMA = contract.record_schema()
_PUBLISHABLE = {"machine_checked", "human_reviewed"}


@dataclass
class ValidationContext:
    artifact_root: Path | None = None
    expected_mode: str | None = None  # "live" | "demo"
    known_source_ids: frozenset[str] | None = None
    now: datetime | None = None
    verify_files: bool = True
    cache: dict = field(default_factory=dict)


def _related(evidence_path: str, referencing_path: str) -> bool:
    return (
        evidence_path == referencing_path
        or evidence_path.startswith(referencing_path + "/")
        or referencing_path.startswith(evidence_path + "/")
    )


def _resolves(record: Any, pointer: str) -> bool:
    """JSON-Pointer lookup; under a list, a token may be a ``cycle_key`` or an index."""
    node = record
    for token in pointer.split("/")[1:]:
        token = token.replace("~1", "/").replace("~0", "~")
        if isinstance(node, dict) and token in node:
            node = node[token]
        elif isinstance(node, list):
            match = next((i for i in node if isinstance(i, dict) and i.get("cycle_key") == token), None)
            if match is not None:
                node = match
            elif token.isdigit() and int(token) < len(node):
                node = node[int(token)]
            else:
                return False
        else:
            return False
    return True


def _public_url_issue(url: str | None, path: str) -> Issue | None:
    if not url:
        return None
    decision = check_url(url, [_ANY_HOST])
    if not decision.ok and decision.reason != "outside_allowlist":
        return Issue(path, f"url.{decision.reason}", f"URL is not acceptable: {decision.reason}")
    return None


class _AnyHost:
    def matches(self, host: str, path: str) -> bool:  # noqa: ARG002
        return True


_ANY_HOST: Any = _AnyHost()


class _EvidenceIndex:
    """Reference bookkeeping shared by the individual checks."""

    def __init__(self, record: dict, issues: list[Issue]) -> None:
        self.by_id: dict[str, dict] = {}
        self.used: set[str] = set()
        self.issues = issues
        for index, ev in enumerate(record["evidence"]):
            path = pointer_join("/evidence", index)
            if ev["id"] in self.by_id:
                issues.append(Issue(pointer_join(path, "id"), "evidence.duplicate_id", f"duplicate id {ev['id']!r}"))
            self.by_id[ev["id"]] = ev
            if not _resolves(record, ev["field_path"]):
                issues.append(
                    Issue(
                        pointer_join(path, "field_path"),
                        "evidence.field_path_unresolved",
                        f"{ev['field_path']!r} does not point at anything in the record",
                    )
                )

    def check(
        self, ids: list[str], path: str, *, required: bool, what: str, alt_paths: tuple[str, ...] = ()
    ) -> list[dict]:
        found: list[dict] = []
        if required and not ids:
            self.issues.append(Issue(path, "evidence.missing", f"{what} needs at least one evidence id"))
        for eid in ids:
            ev = self.by_id.get(eid)
            if ev is None:
                self.issues.append(Issue(path, "evidence.unknown_id", f"{what} cites unknown evidence {eid!r}"))
                continue
            self.used.add(eid)
            if not any(_related(ev["field_path"], p) for p in (path, *alt_paths)):
                self.issues.append(
                    Issue(
                        path,
                        "evidence.wrong_field",
                        f"evidence {eid!r} is attached to {ev['field_path']!r}, not to this {what}",
                    )
                )
            found.append(ev)
        return found


def _check_deadline(d: dict, path: str, cycle: dict, idx: _EvidenceIndex, issues: list[Issue]) -> None:
    kind = d["kind"]
    quotes = idx.check(d["evidence_ids"], path, required=kind != "unspecified", what="deadline")
    has_exact = d.get("date") is not None
    other = [k for k in ("date", "local_time", "annual_month", "annual_day", "deadline_at_utc") if d.get(k) is not None]
    if kind in {"date", "datetime"}:
        if not has_exact:
            issues.append(Issue(pointer_join(path, "date"), "deadline.date_required", f"kind={kind} needs a date"))
        if kind == "datetime" and not d.get("local_time"):
            issues.append(
                Issue(pointer_join(path, "local_time"), "deadline.time_required", "kind=datetime needs local_time")
            )
        if kind == "date" and d.get("local_time"):
            issues.append(
                Issue(
                    pointer_join(path, "local_time"),
                    "deadline.kind_time_mismatch",
                    "a date-only deadline must not carry a time (use kind=datetime)",
                )
            )
        for key in ("annual_month", "annual_day"):
            if d.get(key) is not None:
                issues.append(
                    Issue(pointer_join(path, key), "deadline.unexpected_field", f"{key} is only for annual_rule")
                )
    elif kind == "annual_rule":
        month, day = d.get("annual_month"), d.get("annual_day")
        if month is None or day is None:
            issues.append(Issue(path, "deadline.annual_fields", "annual_rule needs annual_month and annual_day"))
        elif day > calendar.monthrange(2000, month)[1]:
            issues.append(Issue(path, "deadline.annual_invalid", f"{month}/{day} is not a real calendar day"))
        for key in ("date", "local_time", "deadline_at_utc"):
            if d.get(key) is not None:
                issues.append(
                    Issue(
                        pointer_join(path, key),
                        "deadline.annual_no_concrete_date",
                        "an annual rule must not be presented as a concrete date",
                    )
                )
    elif other:
        issues.append(Issue(path, "deadline.unexpected_fields", f"kind={kind} must not carry {other}"))

    tz = d.get("timezone")
    if tz and kind in {"date", "datetime"}:
        day = date.fromisoformat(d["date"]) if has_exact else None
        if resolve_timezone(tz, day).status == "unknown":
            issues.append(
                Issue(
                    pointer_join(path, "timezone"),
                    "deadline.timezone_unrecognised",
                    "timezone kept verbatim but cannot be interpreted; closing time stays ambiguous",
                    "warning",
                )
            )
    if kind in {"date", "datetime"} and has_exact:
        expected = canonical_deadline_utc(d)
        stated = d.get("deadline_at_utc")
        if stated is not None:
            if expected is None:
                issues.append(
                    Issue(
                        pointer_join(path, "deadline_at_utc"),
                        "deadline.utc_not_exact",
                        "timezone unknown or ambiguous: deadline_at_utc must be null",
                    )
                )
            elif parse_iso_datetime(stated) != parse_iso_datetime(expected):
                drift = abs(parse_iso_datetime(stated) - parse_iso_datetime(expected))
                if drift <= timedelta(hours=2):  # what a daylight-saving rule change looks like
                    issues.append(
                        Issue(
                            pointer_join(path, "deadline_at_utc"),
                            "deadline.utc_tz_rules_changed",
                            f"stored value differs by {drift} from the instant computed with the current "
                            f"time-zone rules ({expected}); matching always recomputes, re-run extraction "
                            "to refresh the stored value",
                            "warning",
                        )
                    )
                else:
                    issues.append(
                        Issue(
                            pointer_join(path, "deadline_at_utc"),
                            "deadline.utc_mismatch",
                            f"recomputed closing instant is {expected}",
                        )
                    )
        year = d["date"][:4]
        derived = d.get("derived_from")
        supported = any(year in ev["quote"] for ev in quotes) or (
            derived is not None and (year in cycle["cycle_key"] or year in cycle["label_raw"])
        )
        if not supported:
            issues.append(
                Issue(
                    path,
                    "deadline.year_not_supported",
                    f"year {year} appears in no evidence quote; an undated month/day must not be "
                    "turned into a concrete date without documented derivation (derived_from)",
                )
            )
    expected_precision = {"date": {"day"}, "datetime": {"minute", "second"}, "annual_rule": {"month_day"}}.get(
        kind, {"none"}
    )
    if d["precision"] not in expected_precision:
        issues.append(
            Issue(
                pointer_join(path, "precision"),
                "deadline.precision_mismatch",
                f"kind={kind} normally has precision in {sorted(expected_precision)}",
                "warning",
            )
        )


def _check_cycle(record: dict, cycle: dict, idx: _EvidenceIndex, issues: list[Issue]) -> None:
    base = pointer_join("/cycles", cycle["cycle_key"])
    starts = date.fromisoformat(cycle["starts_on"]) if cycle.get("starts_on") else None
    ends = date.fromisoformat(cycle["ends_on"]) if cycle.get("ends_on") else None
    if starts and ends and starts > ends:
        issues.append(Issue(base, "cycle.dates_inverted", "starts_on is after ends_on"))
    if starts or ends:
        idx.check(
            cycle.get("window_evidence_ids") or [],
            pointer_join(base, "starts_on"),
            required=True,
            what="cycle start/end date",
            alt_paths=(pointer_join(base, "ends_on"),),
        )
    for di, d in enumerate(cycle["deadlines"]):
        _check_deadline(d, pointer_join(base, "deadlines", di), cycle, idx, issues)

    amount = cycle["amount"]
    apath = pointer_join(base, "amount")
    issues.extend(validate_amount(amount, apath))
    quotes = idx.check(amount["evidence_ids"], apath, required=amount["kind"] != "unspecified", what="amount")
    for name in ("fixed", "minimum", "maximum", "pooled_total"):
        value = amount.get(name)
        if value is not None and quotes:
            digits = str(value).split(".")[0]
            haystack = " ".join(ev["quote"] for ev in quotes).replace(",", "").replace(" ", "")
            if digits not in haystack and digits not in str(amount.get("raw_text", "")).replace(",", ""):
                issues.append(
                    Issue(
                        pointer_join(apath, name),
                        "amount.value_not_in_quote",
                        f"{value} does not appear in the cited quote",
                        "warning",
                    )
                )

    epath = pointer_join(base, "eligibility")
    elig, rule_issues = parse_eligibility(cycle["eligibility"], epath)
    issues.extend(rule_issues)
    if elig is not None:
        for pred in iter_predicates([*elig.mandatory, *elig.preferences]):
            idx.check(list(pred.evidence_ids), pred.path, required=True, what="rule")

        def visit(node: Any) -> None:
            if isinstance(node, UnknownNode):
                idx.check(list(node.evidence_ids), node.path, required=False, what="unknown rule")
            elif isinstance(node, GroupNode):
                for child in node.children:
                    visit(child)

        for node in elig.mandatory:
            visit(node)
        for u in elig.unstructured:
            idx.check(list(u.evidence_ids), u.path, required=True, what="unstructured condition")
        for f in elig.funder_conditions:
            idx.check(list(f.evidence_ids), f.path, required=True, what="funder-side condition")
        if not elig.mandatory and not elig.unstructured and record["opportunity_type"] != "award_collection":
            issues.append(
                Issue(
                    epath,
                    "eligibility.no_rules",
                    "no eligibility rules recorded: matching will always need provider confirmation",
                    "warning",
                )
            )

    group_key = "application_group_id" in cycle
    cycle_group = cycle.get("application_group_id")
    record_group = record["application"].get("group_id")
    needs_evidence = bool(cycle_group) or (group_key and cycle_group != record_group)
    idx.check(
        cycle.get("group_evidence_ids") or [],
        pointer_join(base, "application_group_id"),
        required=needs_evidence,
        what="application-group membership/exception",
        alt_paths=("/application/group_id", "/application"),
    )
    if record["application"]["route_type"] == "independent_application" and cycle_group:
        issues.append(
            Issue(
                base,
                "application.independent_but_grouped",
                "an independent application must not belong to a shared-application group",
            )
        )


def _check_status(record: dict, ctx: ValidationContext, issues: list[Issue]) -> None:
    review, pub = record["review_status"], record["publication_status"]
    if review == "human_reviewed" and not record.get("review"):
        issues.append(
            Issue("/review", "review.record_missing", "human_reviewed needs a review record (reviewer, reviewed_at)")
        )
    if record.get("last_verified_at") and review not in _PUBLISHABLE:
        issues.append(
            Issue(
                "/last_verified_at",
                "verification.status_mismatch",
                "last_verified_at may only be set on machine_checked/human_reviewed records",
            )
        )
    if pub == "published" and review not in _PUBLISHABLE:
        issues.append(
            Issue(
                "/publication_status",
                "publication.not_reviewed",
                "only machine_checked or human_reviewed records can be published",
            )
        )
    if record["extraction_method"] == "llm" and (pub == "published" or review == "machine_checked"):
        issues.append(
            Issue("/extraction_method", "publication.llm_unreviewed", "unreviewed LLM output must stay pending + draft")
        )
    demo = record["is_demo"]
    if demo != (record["extraction_method"] == "demo_synthetic"):
        issues.append(
            Issue(
                "/is_demo", "demo.method_mismatch", "is_demo must be true exactly when extraction_method=demo_synthetic"
            )
        )
    if demo and not record["id"].startswith("demo_"):
        issues.append(Issue("/id", "demo.id_prefix", "synthetic records must have ids starting with 'demo_'"))
    if ctx.expected_mode == "live" and demo:
        issues.append(Issue("/is_demo", "mode.demo_in_live", "synthetic demo data must never enter live data"))
    if ctx.expected_mode == "demo" and not demo:
        issues.append(Issue("/is_demo", "mode.live_in_demo", "real data must not enter the demo dataset"))
    if ctx.now is not None:
        limit = ctx.now + timedelta(minutes=5)
        for key in ("last_fetched_at", "last_verified_at"):
            if record.get(key) and parse_iso_datetime(record[key]) > limit:
                issues.append(Issue(f"/{key}", "time.in_future", f"{key} is in the future"))


def validate_record(record: Any, ctx: ValidationContext | None = None) -> list[Issue]:
    """All findings for one record (structure errors short-circuit the deeper checks)."""
    ctx = ctx or ValidationContext()
    if not isinstance(record, dict):
        return [Issue("", "json.not_object", "each line must be one JSON object")]
    issues = validate_schema(record, _SCHEMA)
    if has_errors(issues):
        return issues

    if not is_valid_id(record["id"]):
        issues.append(Issue("/id", "id.invalid", "id must be lowercase [a-z0-9_.:/-]"))
    for key, url in (
        ("/official_url", record["official_url"]),
        ("/application/url", record["application"].get("url")),
        ("/application/contact_url", record["application"].get("contact_url")),
    ):
        if (issue := _public_url_issue(url, key)) is not None:
            issues.append(issue)

    idx = _EvidenceIndex(record, issues)
    seen_cycles: set[str] = set()
    for ci, cycle in enumerate(record["cycles"]):
        if cycle["cycle_key"] in seen_cycles:
            issues.append(
                Issue(
                    pointer_join("/cycles", ci, "cycle_key"),
                    "cycle.duplicate_key",
                    f"duplicate cycle_key {cycle['cycle_key']!r}",
                )
            )
        seen_cycles.add(cycle["cycle_key"])
        _check_cycle(record, cycle, idx, issues)

    conflicts = record.get("conflicts") or []
    for ci, conflict in enumerate(conflicts):
        cpath = pointer_join("/conflicts", ci)
        if not _resolves(record, conflict["field_path"]):
            issues.append(
                Issue(
                    pointer_join(cpath, "field_path"),
                    "conflict.field_unresolved",
                    f"{conflict['field_path']!r} does not point at anything in the record",
                )
            )
        found = idx.check(conflict["evidence_ids"], cpath, required=True, what="conflict")
        if len({ev["quote"] for ev in found}) < 2:
            issues.append(
                Issue(
                    cpath,
                    "conflict.needs_two_statements",
                    "a conflict must cite two different statements (different quotes)",
                )
            )
    if conflicts and (record["review_status"] != "pending" or record["publication_status"] == "published"):
        issues.append(
            Issue(
                "/review_status",
                "conflict.must_be_pending",
                "a record with conflicting statements must stay pending and unpublished until a person resolves it",
            )
        )

    app = record["application"]
    idx.check(
        app["evidence_ids"],
        "/application",
        required=app["route_type"] != "unknown" or bool(app.get("url")),
        what="application route",
    )
    if app.get("group_id") and app["route_type"] != "shared_application_form":
        issues.append(
            Issue(
                "/application/route_type",
                "application.group_route_mismatch",
                "a record with group_id must use route_type=shared_application_form",
            )
        )
    if app["route_type"] == "shared_application_form" and not app.get("group_id"):
        issues.append(
            Issue("/application/group_id", "application.group_missing", "shared_application_form needs group_id")
        )
    if app["route_type"] == "independent_application" and app.get("group_id"):
        issues.append(
            Issue(
                "/application/group_id",
                "application.independent_but_grouped",
                "an independent application must not carry a group_id",
            )
        )
    for di, doc in enumerate(record["required_documents"]):
        idx.check(doc["evidence_ids"], pointer_join("/required_documents", di), required=True, what="required document")

    refs_by_snapshot: dict[str, dict] = {}
    for ri, ref in enumerate(record["source_refs"]):
        rpath = pointer_join("/source_refs", ri)
        if ref["snapshot_id"] in refs_by_snapshot:
            issues.append(Issue(pointer_join(rpath, "snapshot_id"), "source_ref.duplicate", "duplicate snapshot_id"))
        refs_by_snapshot[ref["snapshot_id"]] = ref
        if ctx.known_source_ids is not None and ref["source_id"] not in ctx.known_source_ids:
            issues.append(
                Issue(
                    pointer_join(rpath, "source_id"),
                    "source_ref.unknown_source",
                    f"source {ref['source_id']!r} is not in the source configuration",
                )
            )
        if ctx.artifact_root is not None and ctx.verify_files:
            issues.extend(verify_source_ref(ref, ctx.artifact_root, rpath, ctx.cache))
    for ei, ev in enumerate(record["evidence"]):
        epath = pointer_join("/evidence", ei)
        ref = refs_by_snapshot.get(ev["snapshot_id"])
        if ref is not None and canonicalize_url(ev["source_url"]) != canonicalize_url(ref["url"]):
            issues.append(
                Issue(
                    pointer_join(epath, "source_url"),
                    "evidence.url_mismatch",
                    "source_url differs from the snapshot's URL",
                )
            )
        if ctx.artifact_root is not None and ctx.verify_files:
            issues.extend(verify_evidence_item(ev, refs_by_snapshot, ctx.artifact_root, epath, ctx.cache))
    for ev in record["evidence"]:
        if ev["id"] not in idx.used:
            issues.append(
                Issue(
                    "/evidence", "evidence.unreferenced", f"evidence {ev['id']!r} is not cited by any field", "warning"
                )
            )

    _check_status(record, ctx, issues)
    if record["content_fingerprint"] != compute_fingerprint(record):
        issues.append(
            Issue(
                "/content_fingerprint", "fingerprint.mismatch", "content_fingerprint does not match the record content"
            )
        )
    return issues


# --------------------------------------------------------------------------- file level


@dataclass
class LineResult:
    line_no: int
    record: dict | None
    record_id: str | None
    issues: list[Issue]
    excerpt: str = ""

    @property
    def ok(self) -> bool:
        return not has_errors(self.issues)


@dataclass
class FileValidation:
    path: str
    results: list[LineResult]
    file_issues: list[Issue]

    @property
    def total(self) -> int:
        return len(self.results)

    @property
    def valid_count(self) -> int:
        return sum(1 for r in self.results if r.ok)

    @property
    def invalid_count(self) -> int:
        return self.total - self.valid_count

    @property
    def ok(self) -> bool:
        return not has_errors(self.file_issues) and self.invalid_count == 0

    def valid_records(self) -> list[dict]:
        return [r.record for r in self.results if r.ok and r.record is not None]

    def summary(self) -> dict:
        codes: dict[str, int] = {}
        for r in self.results:
            for i in r.issues:
                codes[i.code] = codes.get(i.code, 0) + 1
        return {
            "path": self.path,
            "records": self.total,
            "valid": self.valid_count,
            "invalid": self.invalid_count,
            "ok": self.ok,
            "issue_counts": dict(sorted(codes.items())),
        }


class _DuplicateKey(ValueError):
    pass


def _no_duplicates(pairs: list[tuple[str, Any]]) -> dict:
    out: dict = {}
    for key, value in pairs:
        if key in out:
            raise _DuplicateKey(key)
        out[key] = value
    return out


def parse_jsonl_lines(data: bytes) -> tuple[list[tuple[int, str]], list[Issue]]:
    """Split bytes into (line_no, text) pairs; report encoding problems."""
    issues: list[Issue] = []
    if data.startswith(b"\xef\xbb\xbf"):
        data = data[3:]
        issues.append(Issue("", "file.bom", "UTF-8 BOM removed; write the file without a BOM", "warning"))
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        return [], [*issues, Issue("", "file.not_utf8", f"not valid UTF-8 at byte {exc.start}")]
    lines: list[tuple[int, str]] = []
    for number, line in enumerate(text.split("\n"), start=1):
        if line.strip():
            lines.append((number, line.rstrip("\r")))
    return lines, issues


def validate_lines(lines: list[tuple[int, str]], ctx: ValidationContext, path: str = "<memory>") -> FileValidation:
    results: list[LineResult] = []
    for number, text in lines:
        try:
            record = json.loads(text, object_pairs_hook=_no_duplicates)
        except _DuplicateKey as exc:
            results.append(
                LineResult(number, None, None, [Issue("", "json.duplicate_key", f"duplicate key {exc}")], text[:300])
            )
            continue
        except json.JSONDecodeError as exc:
            results.append(
                LineResult(
                    number, None, None, [Issue("", "json.invalid", f"line is not valid JSON: {exc.msg}")], text[:300]
                )
            )
            continue
        rid = record.get("id") if isinstance(record, dict) and isinstance(record.get("id"), str) else None
        results.append(
            LineResult(
                number, record if isinstance(record, dict) else None, rid, validate_record(record, ctx), text[:300]
            )
        )

    seen_ids: dict[str, int] = {}
    seen_keys: dict[str, tuple[str, int]] = {}
    groups: dict[tuple[str, str], tuple[tuple[str | None, str | None], int]] = {}
    for result in results:
        rec = result.record
        if rec is None or not result.ok:
            continue
        if rec["id"] in seen_ids:
            result.issues.append(Issue("/id", "file.duplicate_id", f"id also used on line {seen_ids[rec['id']]}"))
        seen_ids.setdefault(rec["id"], result.line_no)
        key = rec["source_record_key"]
        if key in seen_keys and seen_keys[key][0] != rec["id"]:
            result.issues.append(
                Issue(
                    "/source_record_key",
                    "file.source_key_conflict",
                    f"source_record_key already maps to {seen_keys[key][0]!r}",
                )
            )
        seen_keys.setdefault(key, (rec["id"], result.line_no))
        app = rec["application"]
        for cycle in rec["cycles"]:
            gid = cycle["application_group_id"] if "application_group_id" in cycle else app.get("group_id")
            if not gid:
                continue
            definition = (canonicalize_url(app["url"]) if app.get("url") else None, app.get("group_label"))
            gkey = (gid, cycle["cycle_key"])
            if gkey in groups and groups[gkey][0] != definition:
                result.issues.append(
                    Issue(
                        "/application",
                        "group.conflicting_definition",
                        f"group {gid!r} ({cycle['cycle_key']}) is defined differently on line {groups[gkey][1]}",
                    )
                )
            groups.setdefault(gkey, (definition, result.line_no))
    return FileValidation(path, results, [])


def validate_jsonl(path: Path, ctx: ValidationContext) -> FileValidation:
    lines, file_issues = parse_jsonl_lines(path.read_bytes())
    report = validate_lines(lines, ctx, str(path))
    report.file_issues = file_issues
    return report
