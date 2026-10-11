import unicodedata
from collections import Counter
from datetime import UTC, datetime
from decimal import Decimal

from .schemas import Profile, SearchFilters

REGIONS = {
    "BC": "British Columbia",
    "AB": "Alberta",
    "SK": "Saskatchewan",
    "MB": "Manitoba",
    "ON": "Ontario",
    "QC": "Quebec",
    "NB": "New Brunswick",
    "NS": "Nova Scotia",
    "PE": "Prince Edward Island",
    "NL": "Newfoundland and Labrador",
    "YT": "Yukon",
    "NT": "Northwest Territories",
    "NU": "Nunavut",
}


def normalize(value) -> str:
    return "".join(
        c
        for c in unicodedata.normalize("NFD", str(value)).casefold()
        if not unicodedata.combining(c)
    )


def matches(item: dict, filters: SearchFilters) -> bool:
    f = filters.model_dump()
    searchable = " ".join(
        str(item.get(key, ""))
        for key in ("title", "fullTitle", "provider", "summary", "location", "type", "community")
    )
    if f["q"] and normalize(f["q"]).strip() not in normalize(searchable):
        return False
    for filter_key, record_key in [
        ("communities", "community"),
        ("types", "type"),
        ("goals", "goals"),
    ]:
        actual = item.get(record_key)
        if not isinstance(actual, list):
            actual = [actual] if actual else []
        if f[filter_key] and not set(f[filter_key]).intersection(actual):
            return False
    province = item.get("province")
    if f["provinces"] and province != "all" and province not in f["provinces"]:
        if province or not f["include_unknown"]:
            return False
    if f["scope"] == "national" and province != "all":
        return False
    if f["scope"] == "regional" and (not province or province == "all"):
        return False
    amount = Decimal(str(item["amount"])) if item.get("amount") is not None else None
    band = f["amount_band"]
    if band == "listed" and amount is None:
        return False
    if band == "unknown" and amount is not None:
        return False
    if band == "high" and (amount is None or amount <= 5000):
        return False
    if band == "under5000" and (amount is None or amount > 5000):
        return False
    details = item.get("amount_details", {})
    if f["amount_kind"] != "all" and details.get("kind", "unspecified") != f["amount_kind"]:
        return False
    for key in ("education_levels", "fields_of_study", "study_modes", "expenses"):
        actual = item.get(key)
        if f[key] and (
            not actual
            and not f["include_unknown"]
            or actual
            and not set(f[key]).intersection(actual)
        ):
            return False
    if f["renewable"] != "all":
        actual = details.get("renewable")
        expected = {"yes": True, "no": False, "unknown": None}[f["renewable"]]
        if actual != expected and (actual is not None or not f["include_unknown"]):
            return False
        if expected is None and actual is not None:
            return False
    if f["deadline_kind"] != "all":
        actual = item.get("deadline_kind", "unspecified")
        if actual != f["deadline_kind"] and (actual != "unspecified" or not f["include_unknown"]):
            return False
    if f["providers"] and item["provider"] not in f["providers"]:
        return False
    return True


def filtered(records: list[dict], filters: SearchFilters) -> list[dict]:
    rows = [x for x in records if matches(x, filters)]
    if filters.sort == "amount":
        rows.sort(
            key=lambda x: (
                -Decimal(str(x["amount"])) if x.get("amount") is not None else Decimal("Infinity"),
                x["id"],
            )
        )
    elif filters.sort == "alphabetical":
        rows.sort(key=lambda x: (normalize(x["title"]), x["id"]))
    else:
        rows.sort(key=lambda x: (x.get("display_order", 100), x["id"]))
    return rows


def evaluate_rule(node: dict, profile: dict) -> dict:
    """Evidence-check tool, called by the LLM; not an independent questionnaire workflow."""
    kind = node.get("type")
    if kind == "unknown":
        return {"result": "unknown", "missing": [], "source_unknown": True}
    if kind in {"all", "any"}:
        children = node.get("children", [])
        if not children:
            raise ValueError("Empty conditions cannot establish eligibility")
        results = [evaluate_rule(child, profile) for child in children]
        values = [x["result"] for x in results]
        if kind == "all":
            value = (
                "fail"
                if "fail" in values
                else "pass"
                if all(x == "pass" for x in values)
                else "unknown"
            )
        else:
            value = (
                "pass"
                if "pass" in values
                else "fail"
                if all(x == "fail" for x in values)
                else "unknown"
            )
        return {
            "result": value,
            "missing": sorted({f for r in results for f in r["missing"]})
            if value == "unknown"
            else [],
            "source_unknown": value == "unknown" and any(r["source_unknown"] for r in results),
        }
    if kind != "predicate" or node.get("field") not in Profile.model_fields:
        raise ValueError("Unsupported rule")
    actual = profile.get(node["field"])
    if actual is None or actual == []:
        return {"result": "unknown", "missing": [node["field"]], "source_unknown": False}
    expected = node.get("value")
    if node.get("op") == "eq":
        passed = actual == expected
    elif node.get("op") == "in" and isinstance(expected, list):
        passed = actual in expected
    elif node.get("op") == "overlaps" and isinstance(actual, list) and isinstance(expected, list):
        passed = bool(set(actual).intersection(expected))
    else:
        raise ValueError("Unsupported rule operator")
    return {"result": "pass" if passed else "fail", "missing": [], "source_unknown": False}


class DataService:
    def __init__(self, repository):
        self.repository = repository

    def search(self, filters: SearchFilters, limit=24, offset=0):
        rows = filtered(self.repository.all(), filters)
        return {
            "data_mode": self.repository.mode,
            "filters": filters.model_dump(),
            "total": len(rows),
            "limit": limit,
            "offset": offset,
            "records": rows[offset : offset + limit],
        }

    def detail(self, opportunity_id: str):
        return next((x for x in self.repository.all() if x["id"] == opportunity_id), None)

    def match(self, filters: SearchFilters, profile: Profile, limit=12):
        results = self.search(filters, limit)
        matches_out = []
        for item in results["records"]:
            rule = item.get("eligibility_rule", {"type": "unknown"})
            evaluation = evaluate_rule(rule, profile.model_dump())
            status = (
                "potential_fit"
                if evaluation["result"] == "pass"
                else "not_eligible"
                if evaluation["result"] == "fail"
                else "needs_provider_confirmation"
                if evaluation["source_unknown"]
                else "needs_information"
            )
            matches_out.append(
                {
                    "opportunity_id": item["id"],
                    "match_status": status,
                    "eligibility_result": evaluation["result"],
                    "missing_profile_fields": evaluation["missing"],
                    "evidence_refs": item.get("evidence_refs", []),
                    "availability_status": item.get("availability_status", "unknown"),
                    "next_action": "Confirm current requirements with the provider"
                    if evaluation["source_unknown"]
                    else "Review the evidence and application route",
                }
            )
        return {**results, "matches": matches_out}

    def facets(self):
        rows = self.repository.all()
        return {
            "data_mode": self.repository.mode,
            "regions": REGIONS,
            "providers": sorted({x["provider"] for x in rows}),
            "communities": ["First Nations", "Inuit", "Métis"],
            "types": ["Scholarship", "Program"],
            "unknown_policy": "Unknown source details are retained when include_unknown is true",
        }

    def statistics(self, filters: SearchFilters):
        rows = filtered(self.repository.all(), filters)
        national = [x for x in rows if x.get("province") == "all"]
        regions = [
            {
                "code": code,
                "name": name,
                "regional_count": sum(x.get("province") == name for x in rows),
                "national_count": len(national),
                "reach_count": sum(x.get("province") in (name, "all") for x in rows),
            }
            for code, name in REGIONS.items()
        ]
        amounts = [x for x in rows if x.get("amount") is not None]
        maximum = max((Decimal(str(x["amount"])) for x in amounts), default=None)
        return {
            "data_mode": self.repository.mode,
            "generated_at": datetime.now(UTC).isoformat(),
            "dataset_version": "frontend-examples-v5"
            if self.repository.mode == "demo"
            else "live-read-model",
            "filters": filters.model_dump(),
            "total": len(rows),
            "national_count": len(national),
            "regional_count": len(rows) - len(national),
            "regions": regions,
            "by_type": dict(Counter(x["type"] for x in rows)),
            "by_community": {
                c: sum(c in x["community"] for x in rows)
                for c in ["First Nations", "Inuit", "Métis"]
            },
            "amounts": {
                "listed": len(amounts),
                "unknown": len(rows) - len(amounts),
                "highest_example_figure": str(maximum) if maximum is not None else None,
                "sum": None,
                "sum_note": "No funding-pool total: maxima and unknown amounts cannot be added as allocated money",
            },
            "amount_bands": {
                "up_to_5000": sum(Decimal(str(x["amount"])) <= 5000 for x in amounts),
                "above_5000": sum(Decimal(str(x["amount"])) > 5000 for x in amounts),
                "unknown": len(rows) - len(amounts),
            },
            "by_deadline_kind": dict(Counter(x.get("deadline_kind", "unspecified") for x in rows)),
            "amount_rows": [
                {
                    "id": x["id"],
                    "title": x["title"],
                    "provider": x["provider"],
                    "location": x["location"],
                    "amount": str(x["amount"]) if x.get("amount") is not None else None,
                    "amount_details": x.get("amount_details", {}),
                    "last_verified_at": x.get("last_verified_at"),
                }
                for x in rows
            ],
            "quality": {
                "verified_records": sum(bool(x.get("last_verified_at")) for x in rows),
                "unknown_education_level": sum(not x.get("education_levels") for x in rows),
            },
            "notes": [
                "Illustrative records, not Canada's live scholarship market"
                if self.repository.mode == "demo"
                else "Coverage depends on the imported, published dataset",
                "Region counts describe program coverage, not provider headquarters",
                "National reach and overlapping communities are not additive unique totals",
                "Unknown amounts are not zero; caps are not guaranteed awards",
            ],
        }
