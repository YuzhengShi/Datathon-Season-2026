"""A small JSON Schema (2020-12 subset) validator.

Supports exactly what ``navigator.core.contract`` uses: ``$ref`` to ``#/$defs/*``, ``type``
(including type lists), ``const``, ``enum``, ``properties``, ``required``,
``additionalProperties`` (boolean), ``items``, ``minItems``/``maxItems``,
``minLength``/``maxLength``, ``pattern``, ``minimum``/``maximum``, ``anyOf`` and the string
formats ``date``, ``date-time`` and ``uri`` (http/https only).

It exists so the candidate-record contract has one source of truth (the exported JSON Schema)
and can be enforced with precise JSON-Pointer error paths, without a third-party dependency.
``tests/test_contract.py`` cross-checks it against the ``jsonschema`` package when installed.
"""

from __future__ import annotations

import re
from datetime import date, datetime
from typing import Any
from urllib.parse import urlsplit

from navigator.core.issues import Issue, pointer_join

_TYPE_CHECKS = {
    "object": lambda v: isinstance(v, dict),
    "array": lambda v: isinstance(v, list),
    "string": lambda v: isinstance(v, str),
    "boolean": lambda v: isinstance(v, bool),
    "null": lambda v: v is None,
    "integer": lambda v: isinstance(v, int) and not isinstance(v, bool),
    "number": lambda v: isinstance(v, (int, float)) and not isinstance(v, bool),
}


def _format_ok(fmt: str, value: str) -> bool:
    try:
        if fmt == "date":
            return bool(re.fullmatch(r"\d{4}-\d{2}-\d{2}", value)) and bool(date.fromisoformat(value))
        if fmt == "date-time":
            if not re.search(r"(Z|[+-]\d{2}:\d{2})$", value):
                return False
            return bool(datetime.fromisoformat(value.replace("Z", "+00:00")))
        if fmt == "uri":
            parts = urlsplit(value)
            return parts.scheme in {"http", "https"} and bool(parts.netloc)
    except ValueError:
        return False
    return True


def _type_name(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    return type(value).__name__


def validate(instance: Any, schema: dict, root: dict | None = None, path: str = "") -> list[Issue]:
    """Return every violation of ``schema`` by ``instance`` (empty list = valid)."""
    root = root or schema
    if "$ref" in schema:
        target: Any = root
        for token in schema["$ref"].removeprefix("#/").split("/"):
            target = target[token]
        return validate(instance, target, root, path)

    issues: list[Issue] = []
    if "anyOf" in schema:
        branches = [validate(instance, sub, root, path) for sub in schema["anyOf"]]
        if not any(not b for b in branches):
            issues.append(Issue(path, "schema.any_of", "value matches none of the allowed shapes"))
        return issues

    expected = schema.get("type")
    if expected is not None:
        names = expected if isinstance(expected, list) else [expected]
        if not any(_TYPE_CHECKS[n](instance) for n in names):
            issues.append(
                Issue(
                    path,
                    "schema.type",
                    f"expected {' or '.join(names)}, got {_type_name(instance)}",
                )
            )
            return issues

    if "const" in schema and instance != schema["const"]:
        issues.append(Issue(path, "schema.const", f"must equal {schema['const']!r}"))
    if "enum" in schema and instance not in schema["enum"]:
        issues.append(Issue(path, "schema.enum", f"must be one of {schema['enum']}"))

    if isinstance(instance, str):
        if len(instance) < schema.get("minLength", 0):
            issues.append(Issue(path, "schema.min_length", f"shorter than {schema['minLength']}"))
        if len(instance) > schema.get("maxLength", 10**9):
            issues.append(Issue(path, "schema.max_length", f"longer than {schema['maxLength']}"))
        if "pattern" in schema and not re.search(schema["pattern"], instance):
            issues.append(Issue(path, "schema.pattern", f"does not match {schema['pattern']}"))
        if "format" in schema and not _format_ok(schema["format"], instance):
            issues.append(Issue(path, "schema.format", f"not a valid {schema['format']}"))

    if isinstance(instance, (int, float)) and not isinstance(instance, bool):
        if "minimum" in schema and instance < schema["minimum"]:
            issues.append(Issue(path, "schema.minimum", f"below {schema['minimum']}"))
        if "maximum" in schema and instance > schema["maximum"]:
            issues.append(Issue(path, "schema.maximum", f"above {schema['maximum']}"))

    if isinstance(instance, list):
        if len(instance) < schema.get("minItems", 0):
            issues.append(Issue(path, "schema.min_items", f"needs at least {schema['minItems']}"))
        if len(instance) > schema.get("maxItems", 10**9):
            issues.append(Issue(path, "schema.max_items", f"allows at most {schema['maxItems']}"))
        if "items" in schema:
            for index, item in enumerate(instance):
                issues.extend(validate(item, schema["items"], root, pointer_join(path, index)))

    if isinstance(instance, dict):
        properties = schema.get("properties", {})
        for name in schema.get("required", []):
            if name not in instance:
                issues.append(
                    Issue(pointer_join(path, name), "schema.required", f"missing required field {name!r}")
                )
        if schema.get("additionalProperties") is False:
            for name in instance:
                if name not in properties:
                    issues.append(
                        Issue(
                            pointer_join(path, name),
                            "schema.additional_property",
                            f"unknown field {name!r}",
                        )
                    )
        for name, sub in properties.items():
            if name in instance:
                issues.extend(validate(instance[name], sub, root, pointer_join(path, name)))
    return issues
