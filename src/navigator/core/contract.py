"""The JSONL opportunity record contract, expressed once as JSON Schema.

``record_schema()`` is the single source of truth: the validator enforces it, ``docs/schemas``
exports it, and ``docs/DATA_MODEL.md`` documents it. Rules that JSON Schema cannot express
(kind <-> fields, evidence coverage, hashes, rule-tree shape) live in
``navigator.ingestion.validation``.

Null/absent semantics: an optional field that is absent or ``null`` means *unknown / not stated*.
``false`` and ``0`` are real values. An empty list means *nothing recorded*, never "no
restrictions". Unknown is never silently turned into a permissive default.
"""

from __future__ import annotations

from navigator import SCHEMA_VERSION

OPPORTUNITY_TYPES = ("award", "funding_channel", "award_collection")
ROUTE_TYPES = (
    "online_application",
    "institution_portal",
    "shared_application_form",
    "independent_application",
    "email_application",
    "mail_application",
    "contact_administrator",
    "unknown",
)
REVIEW_STATUSES = ("pending", "machine_checked", "human_reviewed", "rejected")
PUBLICATION_STATUSES = ("draft", "published", "archived")
EXTRACTION_METHODS = ("deterministic_adapter", "curated", "llm", "demo_synthetic")
DEADLINE_KINDS = ("date", "datetime", "annual_rule", "rolling", "local_administrator", "unspecified")
DEADLINE_PRECISIONS = ("day", "minute", "second", "month_day", "none")
AMOUNT_KINDS = ("fixed", "range", "variable", "maximum", "pooled_total", "unspecified")
AMOUNT_UNITS = ("per_student", "per_year", "per_term", "program_total", "unspecified")
DOCUMENT_TYPES = (
    "application_form",
    "transcript",
    "proof_of_enrolment",
    "proof_of_indigenous_identity",
    "reference_letter",
    "essay",
    "resume",
    "financial_need_statement",
    "community_support_letter",
    "other",
)
RULE_NODE_TYPES = ("all", "any", "predicate", "unknown")

_STR = {"type": "string"}
_STR_MIN = {"type": "string", "minLength": 1}
_NULLABLE_STR = {"type": ["string", "null"]}
_URL = {"type": "string", "format": "uri", "maxLength": 2000}
_NULLABLE_URL = {"type": ["string", "null"], "format": "uri", "maxLength": 2000}
_DATE = {"type": "string", "format": "date"}
_NULLABLE_DATE = {"type": ["string", "null"], "format": "date"}
_DATETIME = {"type": "string", "format": "date-time"}
_NULLABLE_DATETIME = {"type": ["string", "null"], "format": "date-time"}
_DECIMAL_STR = {"type": ["string", "null"], "pattern": r"^(0|[1-9][0-9]*)(\.[0-9]+)?$"}
_SHA = {"type": "string", "pattern": r"^[0-9a-f]{64}$"}
_EVIDENCE_IDS = {"type": "array", "items": _STR_MIN}


def _obj(properties: dict, required: list[str] | None = None) -> dict:
    return {
        "type": "object",
        "properties": properties,
        "required": required or [],
        "additionalProperties": False,
    }


def record_schema() -> dict:
    """Return the JSON Schema (draft 2020-12) of one JSONL line."""
    defs = {
        "evidence_ids": _EVIDENCE_IDS,
        "rule_node": {
            "description": (
                "Eligibility AST node. all/any need >=1 child; predicate needs field/op/value; "
                "unknown needs reason. Deep checks: navigator.matching.rules."
            ),
            "type": "object",
            "properties": {
                "type": {"enum": list(RULE_NODE_TYPES)},
                "children": {"type": "array", "items": {"$ref": "#/$defs/rule_node"}},
                "field": _STR,
                "op": {"enum": ["eq", "in", "overlaps", "gte", "lte"]},
                "value": {
                    "anyOf": [
                        {"type": "string"},
                        {"type": "number"},
                        {"type": "boolean"},
                        {"type": "array", "items": {"type": ["string", "number", "boolean"]}},
                    ]
                },
                "scale": _DECIMAL_STR,
                "reason": _STR,
                "label": _STR,
                "evidence_ids": _EVIDENCE_IDS,
            },
            "required": ["type"],
            "additionalProperties": False,
        },
        "amount": _obj(
            {
                "kind": {"enum": list(AMOUNT_KINDS)},
                "currency": {"type": ["string", "null"], "pattern": r"^[A-Z]{3}$"},
                "fixed": _DECIMAL_STR,
                "minimum": _DECIMAL_STR,
                "maximum": _DECIMAL_STR,
                "pooled_total": _DECIMAL_STR,
                "unit": {"enum": list(AMOUNT_UNITS)},
                "renewable": {"type": ["boolean", "null"]},
                "raw_text": _STR,
                "evidence_ids": _EVIDENCE_IDS,
            },
            ["kind", "currency", "unit", "renewable", "raw_text", "evidence_ids"],
        ),
        "deadline": _obj(
            {
                "kind": {"enum": list(DEADLINE_KINDS)},
                "date": _NULLABLE_DATE,
                "local_time": {"type": ["string", "null"], "pattern": r"^\d{2}:\d{2}(:\d{2})?$"},
                "timezone": _NULLABLE_STR,
                "deadline_at_utc": _NULLABLE_DATETIME,
                "annual_month": {"type": ["integer", "null"], "minimum": 1, "maximum": 12},
                "annual_day": {"type": ["integer", "null"], "minimum": 1, "maximum": 31},
                "raw_text": _STR,
                "precision": {"enum": list(DEADLINE_PRECISIONS)},
                "derived_from": {
                    "type": ["object", "null"],
                    "properties": {"method": _STR_MIN, "note": _STR},
                    "required": ["method"],
                    "additionalProperties": False,
                },
                "evidence_ids": _EVIDENCE_IDS,
            },
            ["kind", "raw_text", "precision", "evidence_ids"],
        ),
        "eligibility": _obj(
            {
                "mandatory": {"type": "array", "items": {"$ref": "#/$defs/rule_node"}},
                "preferences": {"type": "array", "items": {"$ref": "#/$defs/rule_node"}},
                "unstructured": {
                    "type": "array",
                    "items": _obj({"text": _STR_MIN, "evidence_ids": _EVIDENCE_IDS}, ["text", "evidence_ids"]),
                },
                "funder_conditions": {
                    "description": "Conditions on the organisation/government that RECEIVES the funds; never student conditions.",
                    "type": "array",
                    "items": _obj({"text": _STR_MIN, "evidence_ids": _EVIDENCE_IDS}, ["text", "evidence_ids"]),
                },
                "rules_version": _NULLABLE_STR,
            },
            ["mandatory", "preferences", "unstructured"],
        ),
        "cycle": _obj(
            {
                "cycle_key": {"type": "string", "pattern": r"^[a-z0-9][a-z0-9_.-]{0,59}$"},
                "label_raw": _STR,
                "starts_on": _NULLABLE_DATE,
                "ends_on": _NULLABLE_DATE,
                "deadlines": {"type": "array", "items": {"$ref": "#/$defs/deadline"}},
                "amount": {"$ref": "#/$defs/amount"},
                "eligibility": {"$ref": "#/$defs/eligibility"},
                "window_evidence_ids": _EVIDENCE_IDS,
                "application_group_id": _NULLABLE_STR,
                "group_evidence_ids": _EVIDENCE_IDS,
            },
            ["cycle_key", "label_raw", "deadlines", "amount", "eligibility"],
        ),
        "evidence": _obj(
            {
                "id": _STR_MIN,
                "field_path": {
                    "description": "JSON Pointer into the record; the token under /cycles is the cycle_key",
                    "type": "string",
                    "pattern": r"^(/[^/]+)*$",
                },
                "source_id": _STR_MIN,
                "snapshot_id": _STR_MIN,
                "source_url": _URL,
                "quote": _STR_MIN,
                "locator": _obj(
                    {
                        "heading": _STR,
                        "paragraph_index": {"type": "integer", "minimum": 0},
                        "pdf_page": {"type": "integer", "minimum": 1},
                        "text_start": {"type": "integer", "minimum": 0},
                        "text_end": {"type": "integer", "minimum": 0},
                    }
                ),
                "raw_sha256": _SHA,
                "text_sha256": _SHA,
            },
            [
                "id",
                "field_path",
                "source_id",
                "snapshot_id",
                "source_url",
                "quote",
                "locator",
                "raw_sha256",
                "text_sha256",
            ],
        ),
        "source_ref": _obj(
            {
                "source_id": _STR_MIN,
                "snapshot_id": _STR_MIN,
                "url": _URL,
                "raw_path": _STR_MIN,
                "text_path": _STR_MIN,
                "raw_sha256": _SHA,
                "text_sha256": _SHA,
                "media_type": _STR_MIN,
                "fetched_at": _DATETIME,
                "role": _NULLABLE_STR,
                "source_published_at": _NULLABLE_DATETIME,
                "source_modified_at": _NULLABLE_DATETIME,
            },
            [
                "source_id",
                "snapshot_id",
                "url",
                "raw_path",
                "text_path",
                "raw_sha256",
                "text_sha256",
                "media_type",
                "fetched_at",
            ],
        ),
        "required_document": _obj(
            {
                "type": {"enum": list(DOCUMENT_TYPES)},
                "label": _STR,
                "required": {"type": ["boolean", "null"]},
                "evidence_ids": _EVIDENCE_IDS,
            },
            ["type", "evidence_ids"],
        ),
    }
    properties = {
        "schema_version": {"const": SCHEMA_VERSION},
        "id": {"type": "string", "pattern": r"^[a-z0-9][a-z0-9_.:/-]{0,199}$"},
        "source_record_key": _STR_MIN,
        "title": _STR_MIN,
        "opportunity_type": {"enum": list(OPPORTUNITY_TYPES)},
        "provider": _obj({"id": _STR_MIN, "name": _STR_MIN, "donor_name": _NULLABLE_STR}, ["id", "name"]),
        "official_url": _URL,
        "application": _obj(
            {
                "url": _NULLABLE_URL,
                "route_type": {"enum": list(ROUTE_TYPES)},
                "instructions": _NULLABLE_STR,
                "contact_url": _NULLABLE_URL,
                "group_id": _NULLABLE_STR,
                "group_label": _NULLABLE_STR,
                "evidence_ids": _EVIDENCE_IDS,
            },
            ["route_type", "evidence_ids"],
        ),
        "summary": _STR,
        "cycles": {"type": "array", "minItems": 1, "items": {"$ref": "#/$defs/cycle"}},
        "required_documents": {"type": "array", "items": {"$ref": "#/$defs/required_document"}},
        "evidence": {"type": "array", "items": {"$ref": "#/$defs/evidence"}},
        "source_refs": {"type": "array", "minItems": 1, "items": {"$ref": "#/$defs/source_ref"}},
        "review_status": {"enum": list(REVIEW_STATUSES)},
        "review": {
            "type": ["object", "null"],
            "properties": {"reviewer": _STR_MIN, "reviewed_at": _DATETIME, "note": _NULLABLE_STR},
            "required": ["reviewer", "reviewed_at"],
            "additionalProperties": False,
        },
        "publication_status": {"enum": list(PUBLICATION_STATUSES)},
        "extraction_method": {"enum": list(EXTRACTION_METHODS)},
        "conflicts": {
            "description": "Statements in official sources that contradict each other. Both are kept; the record stays pending.",
            "type": "array",
            "items": _obj(
                {
                    "field_path": {"type": "string", "pattern": r"^(/[^/]+)*$"},
                    "summary": _STR_MIN,
                    "evidence_ids": {"type": "array", "items": _STR_MIN, "minItems": 2},
                },
                ["field_path", "summary", "evidence_ids"],
            ),
        },
        "last_fetched_at": _DATETIME,
        "last_verified_at": _NULLABLE_DATETIME,
        "content_fingerprint": {"type": "string", "pattern": r"^sha256:[0-9a-f]{64}$"},
        "is_demo": {"type": "boolean"},
    }
    required = [
        "schema_version",
        "id",
        "source_record_key",
        "title",
        "opportunity_type",
        "provider",
        "official_url",
        "application",
        "summary",
        "cycles",
        "required_documents",
        "evidence",
        "source_refs",
        "review_status",
        "publication_status",
        "extraction_method",
        "last_fetched_at",
        "content_fingerprint",
        "is_demo",
    ]
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "https://example.invalid/navigator/opportunity-record-1.0.schema.json",
        "title": "Indigenous Student Funding Navigator - opportunity record (one JSONL line)",
        "type": "object",
        "properties": properties,
        "required": required,
        "additionalProperties": False,
        "$defs": defs,
    }
