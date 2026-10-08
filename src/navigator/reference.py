"""Reference data: the explicit institution alias map used to resolve free-text school names."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml

from navigator.core.evidence import normalize_text


@dataclass
class InstitutionDirectory:
    names: dict[str, set[str]] = field(default_factory=dict)  # normalised name -> {institution ids}
    records: dict[str, dict] = field(default_factory=dict)

    def resolve(self, name: str) -> str | None:
        """Institution id for an exact (normalised) name/alias, else ``None`` (never fuzzy)."""
        ids = self.names.get(normalize_text(name).casefold(), set())
        return next(iter(ids)) if len(ids) == 1 else None


def load_institutions(path: Path) -> InstitutionDirectory:
    directory = InstitutionDirectory()
    if not path.is_file():
        return directory
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    for item in data.get("institutions", []):
        directory.records[item["id"]] = item
        for name in [item["name"], item["id"], *item.get("aliases", [])]:
            directory.names.setdefault(normalize_text(name).casefold(), set()).add(item["id"])
    return directory
