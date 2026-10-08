"""A small shared structure for validation findings."""

from __future__ import annotations

from dataclasses import dataclass


def pointer_escape(token: str | int) -> str:
    """Escape one JSON Pointer reference token (RFC 6901)."""
    return str(token).replace("~", "~0").replace("/", "~1")


def pointer_join(base: str, *tokens: str | int) -> str:
    """Append reference tokens to a JSON Pointer."""
    out = base
    for token in tokens:
        out += "/" + pointer_escape(token)
    return out


@dataclass(frozen=True)
class Issue:
    """One validation finding. ``path`` is a JSON Pointer into the record ("" = whole record)."""

    path: str
    code: str
    message: str
    severity: str = "error"  # "error" | "warning"

    def to_dict(self) -> dict[str, str]:
        return {
            "path": self.path,
            "code": self.code,
            "message": self.message,
            "severity": self.severity,
        }

    @property
    def is_error(self) -> bool:
        return self.severity == "error"


def has_errors(issues: list[Issue]) -> bool:
    return any(i.is_error for i in issues)
