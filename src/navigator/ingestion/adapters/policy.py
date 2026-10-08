"""Pages that explain *how* applying works (Indspire Apply Now) or give context only.

They yield no opportunity records. Policy-looking sentences are captured with their locators so a
curated mapping can attach them as evidence to individual awards; linking policy to awards (shared
application groups, cycles) is never inferred here.
"""

from __future__ import annotations

import re

from navigator.core.evidence import normalize_text
from navigator.ingestion.adapters.base import Adapter, AdapterResult, ParseContext
from navigator.ingestion.adapters.common import blocks_of
from navigator.ingestion.builder import SnapshotView
from navigator.ingestion.sources import SourceConfig

_POLICY_CUE = re.compile(
    r"\b(deadline|one application|single application|apply once|shared|application form|"
    r"documents?|transcript|intake|cycle|submit|eligib)\b",
    re.I,
)


class PolicyAdapter(Adapter):
    name = "indspire_policy"

    def parse(self, snaps: list[SnapshotView], source: SourceConfig, ctx: ParseContext) -> AdapterResult:
        result = AdapterResult()
        facts = []
        for snap in snaps:
            if snap.media_type != "text/html":
                continue
            heading = None
            for block in blocks_of(snap):
                if block.level:
                    heading = block.text
                elif _POLICY_CUE.search(block.text):
                    facts.append(
                        {
                            "snapshot_id": snap.snapshot_id,
                            "url": snap.url,
                            "heading": heading,
                            "paragraph_index": block.index,
                            "quote": normalize_text(block.text)[:400],
                        }
                    )
        result.stats = {"policy_facts": facts, "count": len(facts)}
        result.pending.append(
            {
                "item": source.source_id,
                "reason": "policy facts captured for curated linking; "
                "applying them to individual awards (shared forms, cycles) is not inferred",
            }
        )
        return result


class ContextOnlyAdapter(Adapter):
    name = "context_only"

    def parse(self, snaps: list[SnapshotView], source: SourceConfig, ctx: ParseContext) -> AdapterResult:
        result = AdapterResult()
        result.stats = {"snapshots": len(snaps), "note": "context page; no opportunities extracted"}
        return result
