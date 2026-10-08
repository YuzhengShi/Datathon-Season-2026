"""Extraction modes (``EXTRACTION_MODE``).

* ``deterministic`` (default): every source-specific adapter, including the evidence-checked curated ones.
* ``curated``: only the curated adapters (records a person wrote, each fact tied to a quote).
* ``llm``: **not implemented in this build.** Selecting it is an error - it never silently falls back and there is
  no stub that "succeeds". An LLM extractor, when added, must only propose candidates from public source text,
  go through the same schema + evidence validation, stay ``pending`` + ``draft`` until reviewed, and never receive
  a student profile.

An extractor is simply an :class:`~navigator.ingestion.adapters.base.Adapter`: given a source's snapshots it
returns candidates, discovery entries and pending items.
"""

from __future__ import annotations

from navigator.ingestion.adapters.base import Adapter, AdapterResult, ParseContext
from navigator.ingestion.builder import SnapshotView
from navigator.ingestion.sources import SourceConfig

CURATED_ADAPTERS = ("curated_awards", "curated_channel")


class ExtractorUnavailable(RuntimeError):
    """The requested extraction mode cannot run (exit code 2 in the CLI)."""


class LLMExtractor(Adapter):
    name = "llm"

    def parse(self, snaps: list[SnapshotView], source: SourceConfig, ctx: ParseContext) -> AdapterResult:
        raise ExtractorUnavailable("LLM extraction is not implemented in this build; use EXTRACTION_MODE=deterministic or curated")


def select_adapters(mode: str, adapters: dict[str, Adapter]) -> dict[str, Adapter]:
    if mode == "deterministic":
        return adapters
    if mode == "curated":
        return {name: a for name, a in adapters.items() if name in CURATED_ADAPTERS}
    if mode == "llm":
        raise ExtractorUnavailable("EXTRACTION_MODE=llm: LLM extraction is not implemented in this build "
                                   "(no key or model is used anywhere; use deterministic or curated)")
    raise ExtractorUnavailable(f"unknown extraction mode {mode!r}")
