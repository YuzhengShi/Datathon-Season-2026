"""Eligibility rule AST: parsing/validation and three-valued (Kleene) evaluation.

* Only whitelisted profile fields and operators exist (``eq``/``in``/``overlaps``/``gte``/
  ``lte``). There is no ``eval`` and no free-form expression.
* ``all`` / ``any`` need at least one child. An empty ``all`` is never an implicit pass.
* Mandatory conditions (``eligibility.mandatory``) and preferences (``eligibility.preferences``)
  are separate; a missed preference never fails eligibility.
* Unknown is a first-class result and records *why* it is unknown: the profile lacks a field,
  the GPA scale differs, a free-text mapping (community, campus, field of study) cannot be
  confirmed by string equality, or the source itself has no structured rule.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from navigator.core.evidence import normalize_text
from navigator.core.issues import Issue, pointer_join
from navigator.core.money import to_decimal

MAX_DEPTH = 6
OPS = ("eq", "in", "overlaps", "gte", "lte")

PROVINCES = ("AB", "BC", "MB", "NB", "NL", "NS", "NT", "NU", "ON", "PE", "QC", "SK", "YT")
IDENTITIES = ("first_nations", "inuit", "metis")
EDUCATION_LEVELS = ("high_school", "trades_vocational", "college", "undergraduate", "masters", "doctoral")
STUDY_STATUSES = ("full_time", "part_time")

#: reason kinds that a student can fix by answering a question
INFO_KINDS = frozenset({"profile_missing", "profile_scale_mismatch"})
#: reason kinds that only the provider/administrator can settle
PROVIDER_KINDS = frozenset({"mapping_ambiguous", "source_unknown"})

_PRETTY = {
    "first_nations": "First Nations",
    "inuit": "Inuit",
    "metis": "Métis",
    "high_school": "high school",
    "trades_vocational": "trades/vocational",
    "full_time": "full-time",
    "part_time": "part-time",
}


@dataclass(frozen=True)
class FieldSpec:
    name: str
    label: str
    kind: str  # set | enum | bool | code | id | soft | int | decimal
    ops: tuple[str, ...]
    question: str
    values: tuple[str, ...] | None = None


def _specs() -> dict[str, FieldSpec]:
    items = [
        FieldSpec("indigenous_identity", "Indigenous identity", "set", ("overlaps",),
                  "Which of these do you identify as: First Nations, Inuit, Métis?", IDENTITIES),
        FieldSpec("first_nations_registered", "Registered First Nations person", "bool", ("eq",),
                  "Are you registered as a First Nations person under the Indian Act (yes/no)? "
                  "No card or registry number is needed."),
        FieldSpec("metis_citizen", "Métis citizenship/membership", "bool", ("eq",),
                  "Are you a citizen/member of a Métis government or organisation (yes/no)? "
                  "No membership number is needed."),
        FieldSpec("metis_org", "Métis organisation", "soft", ("eq", "in"),
                  "Which Métis government or organisation are you a citizen of?"),
        FieldSpec("inuit_beneficiary", "Inuit land-claim beneficiary", "bool", ("eq",),
                  "Are you an Inuit land-claim beneficiary (yes/no)? No enrolment number is needed."),
        FieldSpec("inuit_org", "Inuit organisation/region", "soft", ("eq", "in"),
                  "Which Inuit organisation or region are you enrolled with?"),
        FieldSpec("residence_province", "Province/territory of residence", "code", ("eq", "in"),
                  "Which province or territory do you live in (e.g. BC, ON)?", PROVINCES),
        FieldSpec("home_community", "Home community", "soft", ("eq", "in"),
                  "What is your home community (First Nation, Métis community or Inuit community)?"),
        FieldSpec("home_region", "Home region", "soft", ("eq", "in"),
                  "What is your home region?"),
        FieldSpec("institution_id", "Institution", "id", ("eq", "in"),
                  "Which school, college or university do you attend (or plan to attend)?"),
        FieldSpec("institution_province", "Province/territory of the institution", "code",
                  ("eq", "in"), "In which province or territory is your school located?", PROVINCES),
        FieldSpec("campus", "Campus", "soft", ("eq", "in"), "Which campus do you attend?"),
        FieldSpec("education_level", "Education level", "enum", ("eq", "in"),
                  "What level of study are you in or entering?", EDUCATION_LEVELS),
        FieldSpec("program_field", "Program or field of study", "soft", ("eq", "in"),
                  "What program or field are you studying?"),
        FieldSpec("study_status", "Study status", "enum", ("eq", "in"),
                  "Are you studying full-time or part-time?", STUDY_STATUSES),
        FieldSpec("year_of_study", "Year of study", "int", ("eq", "in", "gte", "lte"),
                  "Which year of your program are you in?"),
        FieldSpec("gpa", "GPA", "decimal", ("gte", "lte"),
                  "What is your GPA, and on what scale (e.g. 3.4 on a 4.0 scale)?"),
    ]
    return {spec.name: spec for spec in items}


FIELD_SPECS: dict[str, FieldSpec] = _specs()
#: profile keys the engine understands (``gpa_scale``/``institution_name`` are helpers)
PROFILE_FIELDS = tuple(FIELD_SPECS) + ("gpa_scale", "institution_name")


# --------------------------------------------------------------------------- AST nodes


@dataclass(frozen=True)
class Predicate:
    path: str
    field: str
    op: str
    value: Any
    scale: str | None
    evidence_ids: tuple[str, ...]
    label: str | None = None


@dataclass(frozen=True)
class UnknownNode:
    path: str
    reason: str
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class GroupNode:
    path: str
    mode: str  # "all" | "any"
    children: tuple[Any, ...]


@dataclass(frozen=True)
class Unstructured:
    path: str
    text: str
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class Eligibility:
    mandatory: tuple[Any, ...]
    preferences: tuple[Predicate, ...]
    unstructured: tuple[Unstructured, ...]
    rules_version: str | None = None
    funder_conditions: tuple[Unstructured, ...] = ()  # about the funds' recipient organisation, never the student


# --------------------------------------------------------------------------- parsing


def _pretty(value: Any) -> str:
    if isinstance(value, bool):
        return "yes" if value else "no"
    return _PRETTY.get(str(value), str(value).replace("_", " "))


def _scalar_ok(spec: FieldSpec, value: Any) -> str | None:
    """Return an error message when ``value`` is not valid for ``spec`` (scalar level)."""
    if spec.kind in {"enum", "code", "set"}:
        if not isinstance(value, str) or (spec.values and value not in spec.values):
            return f"value must be one of {list(spec.values or [])}"
    elif spec.kind == "bool":
        if not isinstance(value, bool):
            return "value must be true or false"
    elif spec.kind in {"id", "soft"}:
        if not isinstance(value, str) or not value.strip():
            return "value must be a non-empty string"
    elif spec.kind == "int":
        if isinstance(value, bool) or not isinstance(value, int):
            return "value must be an integer"
    elif spec.kind == "decimal":
        try:
            to_decimal(value if not isinstance(value, float) else "x")
        except (TypeError, ValueError):
            return "value must be a non-negative decimal string"
    return None


def _parse_predicate(raw: Mapping, path: str, issues: list[Issue]) -> Predicate | None:
    name, op, value = raw.get("field"), raw.get("op"), raw.get("value")
    spec = FIELD_SPECS.get(name) if isinstance(name, str) else None
    if spec is None:
        issues.append(Issue(pointer_join(path, "field"), "rule.unknown_field", f"unsupported field {name!r}"))
        return None
    if op not in spec.ops:
        issues.append(
            Issue(pointer_join(path, "op"), "rule.bad_operator", f"{name} supports {list(spec.ops)}, got {op!r}")
        )
        return None
    problems: list[str] = []
    if op in {"in", "overlaps"}:
        if not isinstance(value, list) or not value:
            problems.append("value must be a non-empty list")
        else:
            problems.extend(m for v in value if (m := _scalar_ok(spec, v)))
    elif (msg := _scalar_ok(spec, value)) is not None:
        problems.append(msg)
    scale = raw.get("scale")
    if spec.kind == "decimal":
        try:
            to_decimal(scale)
        except (TypeError, ValueError):
            problems.append("a GPA rule needs a decimal 'scale' (e.g. \"4.0\")")
    elif scale is not None:
        problems.append("'scale' is only valid for gpa rules")
    if problems:
        issues.append(Issue(pointer_join(path, "value"), "rule.bad_value", "; ".join(sorted(set(problems)))))
        return None
    ids = raw.get("evidence_ids") or []
    return Predicate(
        path, name, op, value, str(scale) if scale is not None else None, tuple(ids), raw.get("label")
    )


def parse_node(raw: Any, path: str, issues: list[Issue], depth: int = 0) -> Any | None:
    if not isinstance(raw, Mapping):
        issues.append(Issue(path, "rule.not_object", "rule node must be an object"))
        return None
    if depth > MAX_DEPTH:
        issues.append(Issue(path, "rule.too_deep", f"rule tree deeper than {MAX_DEPTH}"))
        return None
    kind = raw.get("type")
    if kind in {"all", "any"}:
        children = raw.get("children")
        if not isinstance(children, list) or not children:
            issues.append(
                Issue(
                    pointer_join(path, "children"),
                    "rule.empty_group",
                    f"'{kind}' needs at least one child (an empty group must never decide eligibility)",
                )
            )
            return None
        parsed = [parse_node(c, pointer_join(path, "children", i), issues, depth + 1) for i, c in enumerate(children)]
        if any(p is None for p in parsed):
            return None
        return GroupNode(path, kind, tuple(parsed))
    if kind == "predicate":
        return _parse_predicate(raw, path, issues)
    if kind == "unknown":
        reason = raw.get("reason")
        if not isinstance(reason, str) or not reason.strip():
            issues.append(Issue(pointer_join(path, "reason"), "rule.unknown_needs_reason", "say why it is unknown"))
            return None
        return UnknownNode(path, reason, tuple(raw.get("evidence_ids") or []))
    issues.append(Issue(pointer_join(path, "type"), "rule.bad_type", f"unsupported node type {kind!r}"))
    return None


def parse_eligibility(raw: Mapping, path: str) -> tuple[Eligibility | None, list[Issue]]:
    """Parse a cycle's ``eligibility`` object; returns (None, issues) on any error."""
    issues: list[Issue] = []
    mandatory = [
        parse_node(n, pointer_join(path, "mandatory", i), issues)
        for i, n in enumerate(raw.get("mandatory") or [])
    ]
    prefs: list[Predicate | None] = []
    for i, n in enumerate(raw.get("preferences") or []):
        p = pointer_join(path, "preferences", i)
        if not isinstance(n, Mapping) or n.get("type") != "predicate":
            issues.append(Issue(p, "rule.preference_shape", "a preference must be a single predicate"))
            prefs.append(None)
        else:
            prefs.append(_parse_predicate(n, p, issues))
    unstructured = [
        Unstructured(pointer_join(path, "unstructured", i), str(u.get("text", "")), tuple(u.get("evidence_ids") or []))
        for i, u in enumerate(raw.get("unstructured") or [])
    ]
    funder = [
        Unstructured(pointer_join(path, "funder_conditions", i), str(u.get("text", "")), tuple(u.get("evidence_ids") or []))
        for i, u in enumerate(raw.get("funder_conditions") or [])
    ]
    if issues or any(n is None for n in mandatory) or any(p is None for p in prefs):
        return None, issues
    return (
        Eligibility(tuple(mandatory), tuple(prefs), tuple(unstructured), raw.get("rules_version"), tuple(funder)),  # type: ignore[arg-type]
        issues,
    )


def iter_predicates(node: Any):
    """Yield every predicate under a node (or a sequence of nodes)."""
    if isinstance(node, Predicate):
        yield node
    elif isinstance(node, GroupNode):
        for child in node.children:
            yield from iter_predicates(child)
    elif isinstance(node, (list, tuple)):
        for child in node:
            yield from iter_predicates(child)


# --------------------------------------------------------------------------- evaluation


@dataclass(frozen=True)
class Leaf:
    path: str
    kind: str  # predicate | unknown_node | unstructured | no_rules
    description: str
    outcome: str  # pass | fail | unknown
    field: str | None = None
    reason_kind: str | None = None
    missing_fields: tuple[str, ...] = ()
    evidence_ids: tuple[str, ...] = ()
    detail: str | None = None

    def to_dict(self) -> dict:
        data = {
            "rule": self.description,
            "path": self.path,
            "field": self.field,
            "outcome": self.outcome,
            "evidence_ids": list(self.evidence_ids),
        }
        if self.outcome == "unknown":
            data["unknown_reason"] = self.reason_kind
        if self.detail:
            data["detail"] = self.detail
        return data


@dataclass
class NodeResult:
    value: bool | None
    passed: list[Leaf]
    failed: list[Leaf]
    unknown: list[Leaf]


@dataclass
class EligibilityOutcome:
    value: bool | None
    passed: list[Leaf]
    failed: list[Leaf]
    unknown: list[Leaf]
    preference_matches: list[dict]


InstitutionResolver = Callable[[str], "str | None"]


def describe_predicate(p: Predicate) -> str:
    spec = FIELD_SPECS[p.field]
    phrase = {
        "eq": "is",
        "in": "is one of",
        "overlaps": "includes at least one of",
        "gte": "is at least",
        "lte": "is at most",
    }[p.op]
    value = ", ".join(_pretty(v) for v in p.value) if isinstance(p.value, list) else _pretty(p.value)
    suffix = f" (on a {p.scale} scale)" if p.scale else ""
    return p.label or f"{spec.label} {phrase} {value}{suffix}"


def _norm(kind: str, value: Any) -> Any:
    if kind == "code":
        return str(value).strip().upper()
    if kind in {"enum", "set", "id"}:
        return str(value).strip().casefold()
    if kind == "soft":
        return normalize_text(str(value)).casefold()
    return value


def _leaf(p: Predicate, outcome: str, **kw: Any) -> Leaf:
    return Leaf(p.path, "predicate", describe_predicate(p), outcome, field=p.field,
                evidence_ids=p.evidence_ids, **kw)


def eval_predicate(p: Predicate, profile: Mapping[str, Any], resolver: InstitutionResolver | None = None) -> Leaf:
    spec = FIELD_SPECS[p.field]
    value = profile.get(p.field)
    if value is None and p.field == "institution_id" and profile.get("institution_name") and resolver:
        value = resolver(str(profile["institution_name"]))
    if value is None:
        return _leaf(p, "unknown", reason_kind="profile_missing", missing_fields=(p.field,))

    if spec.kind == "decimal":
        have_scale = profile.get("gpa_scale")
        if have_scale is None:
            return _leaf(p, "unknown", reason_kind="profile_missing", missing_fields=("gpa_scale",))
        if Decimal(str(have_scale)) != to_decimal(p.scale):
            return _leaf(p, "unknown", reason_kind="profile_scale_mismatch", missing_fields=("gpa",),
                         detail=f"profile GPA is on a {have_scale} scale; the rule uses {p.scale}")
        have = to_decimal(str(value))
        want = to_decimal(p.value)
        ok = have >= want if p.op == "gte" else have <= want
        return _leaf(p, "pass" if ok else "fail")

    if spec.kind == "int":
        want_list = p.value if isinstance(p.value, list) else [p.value]
        have_i = int(value)
        ok = {
            "eq": have_i == want_list[0],
            "in": have_i in want_list,
            "gte": have_i >= want_list[0],
            "lte": have_i <= want_list[0],
        }[p.op]
        return _leaf(p, "pass" if ok else "fail")

    if spec.kind == "bool":
        return _leaf(p, "pass" if bool(value) is p.value else "fail")

    if spec.kind == "set":
        have = {_norm("set", v) for v in value}
        want = {_norm("set", v) for v in p.value}
        return _leaf(p, "pass" if have & want else "fail")

    wanted = p.value if isinstance(p.value, list) else [p.value]
    matched = _norm(spec.kind, value) in {_norm(spec.kind, w) for w in wanted}
    if matched:
        return _leaf(p, "pass")
    if spec.kind == "soft":
        # free-text names cannot be compared by string equality alone: ask the provider
        return _leaf(p, "unknown", reason_kind="mapping_ambiguous",
                     detail="free-text value could not be matched to the rule; the provider must confirm")
    return _leaf(p, "fail")


def _eval(node: Any, profile: Mapping[str, Any], resolver: InstitutionResolver | None) -> NodeResult:
    if isinstance(node, Predicate):
        leaf = eval_predicate(node, profile, resolver)
        if leaf.outcome == "pass":
            return NodeResult(True, [leaf], [], [])
        if leaf.outcome == "fail":
            return NodeResult(False, [], [leaf], [])
        return NodeResult(None, [], [], [leaf])
    if isinstance(node, UnknownNode):
        leaf = Leaf(node.path, "unknown_node", node.reason, "unknown", reason_kind="source_unknown",
                    evidence_ids=node.evidence_ids)
        return NodeResult(None, [], [], [leaf])
    assert isinstance(node, GroupNode)
    results = [_eval(c, profile, resolver) for c in node.children]
    trues = [r for r in results if r.value is True]
    falses = [r for r in results if r.value is False]
    unknowns = [r for r in results if r.value is None]
    flat = lambda rs, attr: [leaf for r in rs for leaf in getattr(r, attr)]  # noqa: E731
    if node.mode == "all":
        if falses:
            return NodeResult(False, [], flat(falses, "failed"), [])
        if not unknowns:
            return NodeResult(True, flat(trues, "passed"), [], [])
        return NodeResult(None, flat(trues, "passed"), [], flat(unknowns, "unknown"))
    # any
    if trues:
        return NodeResult(True, flat(trues, "passed"), [], [])
    if not unknowns:
        return NodeResult(False, [], flat(falses, "failed"), [])
    return NodeResult(None, [], [], flat(unknowns, "unknown"))


def evaluate_eligibility(
    elig: Eligibility, profile: Mapping[str, Any], resolver: InstitutionResolver | None = None
) -> EligibilityOutcome:
    """Three-valued result of all mandatory conditions plus matched preferences.

    Conditions the source has not structured count as *unknown*, so such a record can never
    return ``pass``. A record with no conditions at all is unknown too.
    """
    results = [_eval(n, profile, resolver) for n in elig.mandatory]
    extra: list[Leaf] = [
        Leaf(u.path, "unstructured", u.text, "unknown", reason_kind="source_unknown",
             evidence_ids=u.evidence_ids, detail="condition not yet structured")
        for u in elig.unstructured
    ]
    if not elig.mandatory and not elig.unstructured:
        extra.append(Leaf("/mandatory", "no_rules", "No structured eligibility rules are recorded",
                          "unknown", reason_kind="source_unknown"))
    falses = [r for r in results if r.value is False]
    unknowns = [r for r in results if r.value is None]
    passed = [leaf for r in results if r.value is True for leaf in r.passed]
    if falses:
        value: bool | None = False
        failed = [leaf for r in falses for leaf in r.failed]
        unknown: list[Leaf] = []
        passed = []
    elif unknowns or extra:
        value = None
        failed = []
        unknown = [leaf for r in unknowns for leaf in r.unknown] + extra
    else:
        value, failed, unknown = True, [], []

    matches = []
    for pref in elig.preferences:
        leaf = eval_predicate(pref, profile, resolver)
        if leaf.outcome == "pass":
            matches.append({"preference": leaf.description, "path": pref.path,
                            "evidence_ids": list(pref.evidence_ids)})
    return EligibilityOutcome(value, passed, failed, unknown, matches)
