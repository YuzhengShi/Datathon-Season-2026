"""Adapter contract. An adapter understands ONE source's page structure; it never guesses."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from navigator.ingestion.builder import SnapshotView
from navigator.ingestion.sources import SourceConfig
from navigator.ingestion.text import ExtractedDocument


@dataclass
class ParseContext:
    now: datetime
    curated: dict[str, Any] = field(default_factory=dict)  # curated mapping, keyed by source_id
    read_raw: Callable[[SnapshotView], bytes] | None = None  # raw bytes of a snapshot (for table-structure parsing)


@dataclass
class AdapterResult:
    candidates: list[dict] = field(default_factory=list)  # opportunity records (validated later)
    discovery: list[dict] = field(default_factory=list)  # directory entries: NOT verified awards
    pending: list[dict] = field(default_factory=list)  # {"item", "reason"}: unknown structure, never guessed
    stats: dict[str, Any] = field(default_factory=dict)


class Adapter:
    name = "base"
    version = "0.1.0"

    def select_links(self, doc: ExtractedDocument, url: str, source: SourceConfig, depth: int) -> list[str]:
        """Links worth following from ``url`` (default: none)."""
        return []

    def parse(self, snaps: list[SnapshotView], source: SourceConfig, ctx: ParseContext) -> AdapterResult:
        raise NotImplementedError
