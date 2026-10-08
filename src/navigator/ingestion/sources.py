"""Source configuration (``sources.yaml``): the only place a fetchable URL scope is defined."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

from navigator.core.urlpolicy import AllowRule, check_url

TERMS_STATUSES = ("unreviewed", "reviewed_ok", "restricted")


class SourceConfigError(ValueError):
    pass


@dataclass(frozen=True)
class SourceConfig:
    source_id: str
    name: str
    url: str
    provider_id: str
    provider_name: str
    role: str
    parser: str
    language: str
    allowed_domains: tuple[str, ...]
    allowed_paths: tuple[str, ...]
    access_status: str
    terms_url: str | None = None
    notes: str | None = None

    def rules(self) -> list[AllowRule]:
        return [AllowRule(self.allowed_domains, self.allowed_paths)]

    def to_row(self) -> dict:
        return {"source_id": self.source_id, "url": self.url, "provider_id": self.provider_id,
                "provider_name": self.provider_name, "role": self.role, "parser": self.parser,
                "language": self.language, "access_status": self.access_status}


def load_sources(path: Path) -> list[SourceConfig]:
    if not path.is_file():
        raise SourceConfigError(f"source configuration not found: {path}")
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    out: list[SourceConfig] = []
    seen: set[str] = set()
    for raw in data.get("sources", []):
        try:
            source = SourceConfig(
                source_id=raw["source_id"], name=raw["name"], url=raw["url"],
                provider_id=raw["provider"]["id"], provider_name=raw["provider"]["name"],
                role=raw["role"], parser=raw["parser"], language=raw.get("language", "en"),
                allowed_domains=tuple(raw["allowed_domains"]), allowed_paths=tuple(raw["allowed_paths"]),
                access_status=raw.get("access_status", "unreviewed"),
                terms_url=raw.get("terms_url"), notes=raw.get("notes"),
            )
        except KeyError as exc:
            raise SourceConfigError(f"source entry is missing {exc}: {raw!r}") from exc
        if source.source_id in seen:
            raise SourceConfigError(f"duplicate source_id {source.source_id!r}")
        seen.add(source.source_id)
        if source.access_status not in TERMS_STATUSES:
            raise SourceConfigError(f"{source.source_id}: access_status must be one of {TERMS_STATUSES}")
        decision = check_url(source.url, source.rules())
        if not decision.ok:
            raise SourceConfigError(f"{source.source_id}: start URL violates its own allowlist ({decision.reason})")
        out.append(source)
    return out
