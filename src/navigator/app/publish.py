"""Publish the canonical dataset (data/awards.jsonl) into the application read model.

Transform rules are honest by design: a fact the source does not state stays null or
"unspecified", never zero or inferred. Community scope falls back to all three
Indigenous communities only because every record in this dataset serves Indigenous
students; when the source names a narrower scope, the narrower scope wins.

Region follows the same rule. A record is regional when its eligibility rules name a school or a
province, regional or national when the federal directory lists it that way, and otherwise its region
is NOT STATED (``province`` is null): never "national" just because nothing restricts it.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import date, datetime
from pathlib import Path

import yaml

from .config import REPO_ROOT, Settings
from .db import Opportunity, engine_for, import_demo, upgrade
from .services import REGIONS

DEFAULT_DATASET = REPO_ROOT / "data" / "awards.jsonl"
DEMO_DATASET = REPO_ROOT / "dist" / "data" / "demo-opportunities.json"
INSTITUTIONS = REPO_ROOT / "data" / "reference" / "institutions.yaml"
FRONTEND_DATASET = REPO_ROOT / "dist" / "data" / "opportunities.json"

NATIONAL = "all"  # the province value of a record that applies across Canada
COMMUNITY_NAMES = {"first_nations": "First Nations", "inuit": "Inuit", "metis": "Métis"}
EDUCATION_MAP = {"masters": "graduate", "doctoral": "graduate", "phd": "graduate"}
MONTHS = {
    "January": "Jan",
    "February": "Feb",
    "March": "Mar",
    "April": "Apr",
    "May": "May",
    "June": "Jun",
    "July": "Jul",
    "August": "Aug",
    "September": "Sep",
    "October": "Oct",
    "November": "Nov",
    "December": "Dec",
}
_DIRECTORY_REGION = re.compile(r"Province/territory:\s*([^.]+)\.")
_DIRECTORY_GROUP = re.compile(r"Indigenous group:\s*([^.]+)\.")
_TRAINING_TITLE = re.compile(r"\b(skills?|training|trades?|apprentice\w*)\b", re.IGNORECASE)


def stable_id(raw: str, limit: int = 100) -> str:
    """Deterministic id: long source ids keep a hash suffix so links never drift."""
    if len(raw) <= limit:
        return raw
    return f"{raw[: limit - 11]}-{hashlib.sha1(raw.encode()).hexdigest()[:10]}"


def load_institutions(path: Path = INSTITUTIONS) -> dict[str, dict]:
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    return {item["id"]: item for item in payload["institutions"]}


def _eligibility_nodes(record: dict) -> list[dict]:
    nodes: list[dict] = []
    for cycle in record.get("cycles", []):
        eligibility = cycle.get("eligibility") or {}
        nodes.extend(eligibility.get("mandatory", []))
    return nodes


def _find_predicate(nodes: list[dict], field: str) -> dict | None:
    return next((n for n in nodes if n.get("type") == "predicate" and n.get("field") == field), None)


def _community(nodes: list[dict]) -> list[str]:
    identity = _find_predicate(nodes, "indigenous_identity")
    if identity:
        return [COMMUNITY_NAMES[v] for v in identity.get("value", []) if v in COMMUNITY_NAMES]
    if _find_predicate(nodes, "first_nations_registered"):
        return ["First Nations"]
    if _find_predicate(nodes, "metis_citizen"):
        return ["Métis"]
    if _find_predicate(nodes, "inuit_beneficiary"):
        return ["Inuit"]
    return list(COMMUNITY_NAMES.values())


def _community_of(record: dict, nodes: list[dict]) -> list[str]:
    """Eligibility rules first; for a directory entry without them, the directory's own group column; otherwise every
    community (nothing recorded restricts it)."""
    fields = ("indigenous_identity", "first_nations_registered", "metis_citizen", "inuit_beneficiary")
    if any(_find_predicate(nodes, field) for field in fields):
        return _community(nodes)
    return _directory_community(record) or _community(nodes)


def _directory_community(record: dict) -> list[str] | None:
    """The communities the federal directory names for its own entries ("Indigenous group: M\u00e9tis; First Nations.").

    "All Indigenous People" is all three. A group this code does not know makes the whole answer unknown (None), not a guess.
    Like the region, it feeds the filters and the statistics, never the eligibility check."""
    if record.get("extraction_method") != "deterministic_adapter":
        return None
    match = _DIRECTORY_GROUP.search(record.get("summary") or "")
    if not match:
        return None
    names = {"first nations": "First Nations", "inuit": "Inuit", "m\u00e9tis": "M\u00e9tis", "metis": "M\u00e9tis"}
    found: list[str] = []
    for part in match.group(1).split(";"):
        part = part.strip().casefold()
        if part == "all indigenous people":
            return list(COMMUNITY_NAMES.values())
        if part not in names:
            return None
        found.append(names[part])
    return [c for c in COMMUNITY_NAMES.values() if c in found] or None


def _directory_region(record: dict) -> str | None:
    """The region the federal directory lists for its own entries ("Province/territory: British Columbia.").

    Only entries built by the deterministic directory adapter carry this line. It is the directory's
    statement, not an eligibility rule, so it feeds coverage and statistics but never the eligibility check.
    "National" and "Any Location" both say the award is not tied to a place, so both count as across Canada. Anything else
    that is not one province or territory is left unstated rather than guessed.
    """
    if record.get("extraction_method") != "deterministic_adapter":
        return None
    match = _DIRECTORY_REGION.search(record.get("summary") or "")
    if not match:
        return None
    listed = match.group(1).strip()
    if listed.casefold() in ("national", "any location"):
        return NATIONAL
    return listed if listed in REGIONS.values() else None


def _region(record: dict, nodes: list[dict], institutions: dict) -> tuple[str | None, str]:
    """(province, basis): a province name, "all" (stated nationwide) or None (the source does not say)."""
    institution = _find_predicate(nodes, "institution_id")
    if institution and institution.get("value") in institutions:
        code = institutions[institution["value"]].get("province")
        if code:
            return REGIONS.get(code, code), "rule"
    for field in ("residence_province", "institution_province"):
        predicate = _find_predicate(nodes, field)
        value = predicate.get("value") if predicate else None
        if isinstance(value, str) and value:
            return REGIONS.get(value, value), "rule"
    listed = _directory_region(record)
    if listed:
        return listed, "directory"
    return None, "not_stated"


def _location_label(province: str | None) -> str:
    if province is None:
        return "Region not stated"
    return "Across Canada" if province == NATIONAL else province


def _goals(record: dict) -> list[str]:
    """Every record funds post-secondary study (that is what this dataset is); "training" is added only when the
    record's own title names skills, training or trades. Nothing is guessed from the body text."""
    title = record.get("title") or ""
    # "Research Training Awards" fund graduate research, not skills or trades training.
    training = _TRAINING_TITLE.search(title) and not re.search(r"\bresearch\b", title, re.I)
    return ["postsecondary", "training"] if training else ["postsecondary"]


def _number(raw: object) -> float | None:
    try:
        return float(raw)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def _source_modified(record: dict) -> str | None:
    """The newest "last modified" date that the record's own source pages state (a federal directory page says when it
    was last changed), as YYYY-MM-DD; null when no source states one. It shows how current a source is, nothing more."""
    dates = [ref.get("source_modified_at") for ref in record.get("source_refs", []) if ref.get("source_modified_at")]
    return max(dates)[:10] if dates else None


def _source_kind(record: dict) -> str:
    """``directory_listing`` when every source of the record is the federal directory, else ``official_page``.

    The same rule as the core's ``services.query.source_kind``: a directory entry is never presented as the
    provider's own page.
    """
    roles = {ref.get("role") for ref in record.get("source_refs", [])}
    return "directory_listing" if roles and roles <= {"discovery_index"} else "official_page"


def _rule_node(node: dict, institutions: dict) -> dict:
    if node.get("type") == "unknown":
        return {"type": "unknown"}
    if node.get("type") != "predicate":
        return {"type": "unknown"}
    field, op, value = node.get("field"), node.get("op"), node.get("value")
    if field == "indigenous_identity":
        return {
            "type": "predicate",
            "field": "communities",
            "op": "overlaps",
            "value": _community([node]),
        }
    if field in ("residence_province", "institution_province"):
        return {
            "type": "predicate",
            "field": field,
            "op": op,
            "value": REGIONS.get(value, value) if isinstance(value, str) else value,
        }
    if field == "study_status":
        return {"type": "predicate", "field": "study_mode", "op": op, "value": value}
    if field == "education_level":
        if isinstance(value, list):
            value = [EDUCATION_MAP.get(v, v) for v in value]
        else:
            value = EDUCATION_MAP.get(value, value)
        return {"type": "predicate", "field": "education_level", "op": op, "value": value}
    if field in (
        "institution_id",
        "first_nations_registered",
        "metis_citizen",
        "inuit_beneficiary",
        "goal",
    ):
        return {"type": "predicate", "field": field, "op": op, "value": value}
    return {"type": "unknown"}


def _eligibility_rule(nodes: list[dict], institutions: dict) -> dict:
    children = [_rule_node(n, institutions) for n in nodes]
    children = [c for c in children if c]
    if not children:
        return {"type": "unknown"}
    if all(c.get("type") == "unknown" for c in children):
        return {"type": "unknown"}
    return {"type": "all", "children": children}


def _timing(cycle: dict) -> str:
    deadlines = cycle.get("deadlines", [])
    kinds = {d.get("kind") for d in deadlines}
    if "date" in kinds:
        parts = sorted(filter(None, (d.get("date") for d in deadlines if d.get("kind") == "date")))
        formatted = []
        for raw in parts:
            try:
                day = datetime.fromisoformat(raw)
                formatted.append(f"{day.strftime('%b')} {day.day}, {day.year}")
            except (ValueError, TypeError):
                formatted.append(raw)
        return "Apply by " + " or ".join(formatted)
    if "annual_rule" in kinds:
        labels = []
        for d in deadlines:
            if d.get("kind") != "annual_rule":
                continue
            text = (d.get("raw_text") or "").strip()
            for month, short in MONTHS.items():
                text = text.replace(month, short)
            labels.append(text)
        deduped = list(dict.fromkeys(labels))
        return "Due every year — " + " · ".join(deduped)
    if "rolling" in kinds:
        return "Rolling intake"
    if "local_administrator" in kinds:
        return "Dates set by the administrator"
    return "Confirm the next deadline"


def _availability(cycle: dict, today: date) -> str:
    for d in cycle.get("deadlines", []):
        if d.get("kind") == "date" and d.get("date"):
            try:
                return "open" if date.fromisoformat(d["date"]) >= today else "closed"
            except (ValueError, TypeError):
                return "unknown"
        if d.get("kind") == "rolling":
            return "open"
        if d.get("kind") == "annual_rule":
            return "annual"
    return "unknown"


def _note(record: dict, rule: dict) -> str:
    verified = (record.get("last_verified_at") or "")[:10]
    if record.get("extraction_method") == "curated":
        base = f"Quote-checked on the provider's own page (verified {verified})."
    else:
        base = "From the federal Indigenous Bursaries directory entry; directory pages can be years old."
    children = rule.get("children", []) if isinstance(rule, dict) else []
    has_unknown = rule.get("type") == "unknown" or any(c.get("type") == "unknown" for c in children)
    if has_unknown:
        base += " The source does not state full eligibility rules in text — confirm with the provider."
    return base


def transform(record: dict, institutions: dict, order: int, today: date | None = None) -> dict:
    today = today or date.today()
    nodes = _eligibility_nodes(record)
    rule = _eligibility_rule(nodes, institutions)
    province, region_basis = _region(record, nodes, institutions)
    cycle = (record.get("cycles") or [{}])[0]
    amount = cycle.get("amount") or {}
    amount_value = None
    if amount.get("kind") in ("fixed", "maximum"):
        raw = amount.get("fixed") if amount.get("kind") == "fixed" else amount.get("maximum")
        try:
            amount_value = float(raw)
        except (TypeError, ValueError):
            amount_value = None
    low, high = _number(amount.get("minimum")), _number(amount.get("maximum"))
    spread = amount.get("kind") == "range" and low is not None and high is not None
    deadlines = cycle.get("deadlines", [])
    kind = deadlines[0].get("kind", "unspecified") if deadlines else "unspecified"
    education = _find_predicate(nodes, "education_level")
    levels = education.get("value") if education else None
    if isinstance(levels, str):
        levels = [levels]
    study = _find_predicate(nodes, "study_status")
    return {
        "id": stable_id(record["id"]),
        "source_id": record["id"],
        "title": record["title"],
        "fullTitle": record["title"],
        "provider": record["provider"]["name"],
        "summary": record.get("summary") or "",
        "type": "Program" if record.get("opportunity_type") == "funding_channel" else "Scholarship",
        "community": _community_of(record, nodes),
        "province": province,
        "region_basis": region_basis,
        "location": _location_label(province),
        "source_kind": _source_kind(record),
        "source_modified_at": _source_modified(record),
        "amount": amount_value,
        "amount_details": {
            "kind": amount.get("kind", "unspecified"),
            "currency": amount.get("currency"),
            "unit": amount.get("unit", "unspecified"),
            "renewable": amount.get("renewable"),
            "minimum": low if spread else None,  # a stated range is shown as a range, never as one figure
            "maximum": high if spread else None,
            "source_text": amount.get("raw_text"),
        },
        "deadline_kind": kind,
        "timing": _timing(cycle),
        "goals": _goals(record),
        "education_levels": [EDUCATION_MAP.get(v, v) for v in (levels or [])],
        "fields_of_study": [],
        "study_modes": [study.get("value")] if study and study.get("op") == "eq" and study.get("value") else [],
        "expenses": [],
        "url": record.get("official_url"),
        "application_route": (record.get("application") or {}).get("route_type", "unknown"),
        "eligibility_rule": rule,
        "evidence_refs": [
            {
                "id": e["id"],
                "field_path": e.get("field_path"),
                "quote": e.get("quote"),
                "source_id": e.get("source_id"),
                "source_url": e.get("source_url"),
            }
            for e in record.get("evidence", [])
        ],
        "availability_status": _availability(cycle, today),
        "last_verified_at": record.get("last_verified_at"),
        "note": _note(record, rule),
        "display_order": order,
        "is_demo": False,
    }


def load_records(path: Path = DEFAULT_DATASET) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def build_payload(records: list[dict], institutions: dict | None = None, today: date | None = None) -> dict:
    institutions = institutions if institutions is not None else load_institutions()
    today = today or date.today()
    tier = {"funding_channel": 0, "curated": 1, "deterministic_adapter": 2}
    ordered = sorted(
        enumerate(records),
        key=lambda pair: (
            tier.get(pair[1].get("opportunity_type"), 1),
            tier.get(pair[1].get("extraction_method"), 2),
            pair[1]["provider"]["name"],
            pair[1]["title"],
        ),
    )
    out = [transform(record, institutions, order * 10, today) for order, (_, record) in enumerate(ordered)]
    return {"data_mode": "live", "records": out}


def import_live(settings: Settings, payload: dict) -> dict:
    """Publish a built payload into the live read model. Idempotent; never touches demo."""
    if settings.data_mode != "live":
        raise ValueError("publishing the canonical dataset requires live mode")
    if payload.get("data_mode") != "live" or not all(not x.get("is_demo") for x in payload["records"]):
        raise ValueError("Live publish requires the live dataset with is_demo:false records")
    ids = [x["id"] for x in payload["records"]]
    if len(set(ids)) != len(ids):
        raise ValueError("Duplicate ids in dataset")
    from sqlalchemy.orm import Session

    engine = engine_for(settings)
    counts = {"created": 0, "updated": 0, "unchanged": 0}
    try:
        with Session(engine) as session, session.begin():
            for body in payload["records"]:
                existing = session.get(Opportunity, ("live", body["id"]))
                if existing and existing.body == body:
                    counts["unchanged"] += 1
                elif existing:
                    existing.title, existing.body = body["title"], body
                    counts["updated"] += 1
                else:
                    session.add(
                        Opportunity(
                            data_mode="live",
                            id=body["id"],
                            title=body["title"],
                            publication_status="published",
                            body=body,
                        )
                    )
                    counts["created"] += 1
    finally:
        engine.dispose()
    return counts


def publish(settings: Settings, dataset_path: Path = DEFAULT_DATASET, write_frontend: bool = True) -> dict:
    """Canonical dataset -> live read model (+ dist/data/opportunities.json for static hosting). Idempotent."""
    if settings.data_mode != "live":
        raise ValueError("publishing the canonical dataset requires live mode")
    payload = build_payload(load_records(Path(dataset_path)))
    if write_frontend:
        FRONTEND_DATASET.parent.mkdir(parents=True, exist_ok=True)
        FRONTEND_DATASET.write_text(json.dumps(payload, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    counts = import_live(settings, payload)
    return {"data_mode": "live", "records": len(payload["records"]), **counts}


def ensure_read_model(settings: Settings, dataset_path: Path | None = None) -> dict:
    """Make the read model of the selected mode current: migrate, then an idempotent import.

    Run when the app starts, so the page and the API are always built from the same records and the same mode.
    It never rewrites the static file in dist/ (that is ``navigator app publish``).
    """
    upgrade(settings)
    if settings.data_mode == "demo":
        return {"data_mode": "demo", **import_demo(settings, DEMO_DATASET)}
    path = Path(dataset_path or DEFAULT_DATASET)
    if not path.is_file():
        return {"data_mode": "live", "records": 0, "note": f"{path.name} not found; nothing was published"}
    return publish(settings, path, write_frontend=False)
