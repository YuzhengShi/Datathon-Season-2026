"""Money semantics: decimal-string amounts, never floats, never "unknown == 0"."""

from __future__ import annotations

import re
from decimal import Decimal
from typing import Any

from navigator.core.issues import Issue, pointer_join

AMOUNT_KINDS = ("fixed", "range", "variable", "maximum", "pooled_total", "unspecified")
AMOUNT_UNITS = ("per_student", "per_year", "per_term", "program_total", "unspecified")
NUMERIC_FIELDS = ("fixed", "minimum", "maximum", "pooled_total")

DECIMAL_PATTERN = re.compile(r"^(0|[1-9][0-9]*)(\.[0-9]+)?$")


def to_decimal(value: Any) -> Decimal:
    """Parse a non-negative decimal from ``str``/``int``/``Decimal``; floats are rejected."""
    if isinstance(value, bool) or isinstance(value, float):
        raise TypeError("amounts must be decimal strings, not floats or booleans")
    if isinstance(value, int):
        parsed = Decimal(value)
    elif isinstance(value, Decimal):
        parsed = value
    elif isinstance(value, str):
        text = value.strip()
        if not DECIMAL_PATTERN.match(text):
            raise ValueError(f"not a non-negative decimal string: {value!r}")
        parsed = Decimal(text)
    else:
        raise TypeError(f"unsupported amount type {type(value).__name__}")
    if not parsed.is_finite() or parsed < 0:
        raise ValueError("amount must be finite and non-negative")
    return parsed


def canonical_decimal(value: Any) -> str:
    """Stable text form: ``'5000.00'`` -> ``'5000'`` (used by fingerprints and exports)."""
    return format(to_decimal(value).normalize(), "f")


def validate_amount(amount: dict, path: str) -> list[Issue]:
    """Semantic checks that JSON Schema cannot express (kind <-> fields, bounds, unit)."""
    issues: list[Issue] = []
    kind = amount.get("kind")
    present = {f for f in NUMERIC_FIELDS if amount.get(f) is not None}
    parsed: dict[str, Decimal] = {}
    for name in present:
        try:
            parsed[name] = to_decimal(amount[name])
        except (TypeError, ValueError) as exc:
            issues.append(Issue(pointer_join(path, name), "amount.bad_decimal", str(exc)))
    if issues:
        return issues

    required: dict[str, set[str]] = {
        "fixed": {"fixed"},
        "range": {"minimum", "maximum"},
        "maximum": {"maximum"},
        "pooled_total": {"pooled_total"},
        "variable": set(),
        "unspecified": set(),
    }
    if kind in required:
        for name in sorted(required[kind] - present):
            issues.append(
                Issue(pointer_join(path, name), "amount.missing_field", f"kind={kind} needs {name}")
            )
        for name in sorted(present - required[kind]):
            issues.append(
                Issue(
                    pointer_join(path, name),
                    "amount.unexpected_field",
                    f"kind={kind} must not carry {name}",
                )
            )
    if kind == "range" and {"minimum", "maximum"} <= parsed.keys():
        if parsed["minimum"] > parsed["maximum"]:
            issues.append(Issue(path, "amount.range_inverted", "minimum is greater than maximum"))
    if kind == "pooled_total" and amount.get("unit") in {"per_student", "per_term"}:
        issues.append(
            Issue(
                pointer_join(path, "unit"),
                "amount.pooled_total_unit",
                "a pooled total is shared by all recipients; unit cannot be per_student/per_term",
            )
        )
    if present and not amount.get("currency"):
        issues.append(
            Issue(
                pointer_join(path, "currency"),
                "amount.currency_required",
                "a numeric amount needs an explicit currency",
            )
        )
    if kind != "unspecified" and not str(amount.get("raw_text") or "").strip():
        issues.append(
            Issue(pointer_join(path, "raw_text"), "amount.raw_text_required", "keep source wording")
        )
    return issues


_INTERPRETATION = {
    "fixed": "Stated award value as written by the provider.",
    "range": "Stated range; the provider decides the actual amount.",
    "maximum": "A maximum only. It is not a guaranteed or expected amount.",
    "pooled_total": "Combined total for all recipients. It is not an amount any one student gets.",
    "variable": "The amount varies; see the provider.",
    "unspecified": "No amount is stated in the source. This is unknown, not zero.",
}


def describe_amount(amount: dict) -> dict:
    """API-facing view: the stored amount plus an explicit reading guide."""
    kind = amount.get("kind", "unspecified")
    return {
        **amount,
        "interpretation": _INTERPRETATION.get(kind, _INTERPRETATION["unspecified"]),
        "is_per_recipient_figure": kind in {"fixed", "range"},
        "personal_benefit_estimated": False,
    }

