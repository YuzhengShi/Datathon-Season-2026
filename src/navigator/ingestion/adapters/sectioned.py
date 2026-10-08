"""One page, many awards (UBC-style) and one-page-per-award (listing + detail) extraction.

The adapter is deliberately conservative. It captures: title, a short summary, explicit
``Month D, YYYY`` deadlines that sit in a sentence with a deadline cue (timezone stays unknown),
and every eligibility-looking paragraph as an *unstructured condition* with a verified quote.
It never structures eligibility, never guesses an amount, and never invents a cycle. A record
therefore always asks for provider confirmation; a section with nothing verifiable stays
``pending`` + ``draft``.
"""

from __future__ import annotations

import re

from navigator.core.ids import make_opportunity_id, slugify
from navigator.ingestion.adapters.base import Adapter, AdapterResult, ParseContext
from navigator.ingestion.adapters.common import (
    DEADLINE_CUE,
    ELIGIBILITY_CUE,
    base_record,
    blocks_of,
    empty_amount,
    explicit_dates,
    first_sentence,
)
from navigator.ingestion.builder import Q, SnapshotView, attach_evidence, finalize
from navigator.ingestion.sources import SourceConfig
from navigator.ingestion.text import ExtractedDocument
from navigator.core.timeutil import format_utc

_SKIP_HEADINGS = re.compile(r"^(on this page|contents|table of contents|related|more information|share|menu|search|"
                            r"contact us|footer|navigation)$", re.I)
_NUMBER_AT_END = re.compile(r"\s*[(\[#]\s*(?:award\s*)?(?:no\.?\s*)?(\d{3,7})\s*[)\]]?\s*$", re.I)
_DONOR = re.compile(r"^(?:donor|sponsored by|funded by|presented by|in memory of)\s*:?\s*(.{3,120})$", re.I)
MAX_UNSTRUCTURED = 8


def _record_for(section_title: str, native_key: str, paragraphs: list, snap: SnapshotView, source: SourceConfig,
                snaps: dict[str, SnapshotView], fetched_at: str, official_url: str) -> dict:
    deadlines, unstructured = [], []
    donor = None
    for block in paragraphs:
        text = block.text
        if m := _DONOR.match(text):
            donor = m.group(1).strip().rstrip(".")
        if DEADLINE_CUE.search(text):
            for day, raw in explicit_dates(text):
                deadlines.append({
                    "kind": "date", "date": day.isoformat(), "raw_text": raw, "precision": "day",
                    "evidence_ids": [Q(raw, paragraph_index=block.index)]})
        elif ELIGIBILITY_CUE.search(text) and len(unstructured) < MAX_UNSTRUCTURED:
            quote = first_sentence(text, 300)
            unstructured.append({"text": quote, "evidence_ids": [Q(quote, paragraph_index=block.index)]})
    summary = first_sentence(paragraphs[0].text) if paragraphs else section_title
    cycle = {"cycle_key": "unspecified", "label_raw": "not stated", "starts_on": None, "ends_on": None,
             "deadlines": deadlines, "amount": empty_amount(),
             "eligibility": {"mandatory": [], "preferences": [], "unstructured": unstructured, "rules_version": None}}
    provider = {"id": source.provider_id, "name": source.provider_name, "donor_name": donor}
    record = base_record(
        rid=make_opportunity_id(source.provider_id, native_key), key=f"{source.source_id}#{native_key}",
        title=section_title, otype="award", provider=provider, official_url=official_url, summary=summary,
        application={"url": None, "route_type": "unknown", "instructions": None, "contact_url": None,
                     "group_id": None, "evidence_ids": []},
        cycles=[cycle], documents=[], fetched_at=fetched_at)
    record = attach_evidence(record, snaps, snap.key)
    if not record["evidence"]:  # nothing verifiable beyond a title: keep it out of public results
        record["review_status"], record["publication_status"] = "pending", "draft"
    return finalize(record)


class SectionedAwardsAdapter(Adapter):
    """UBC-style page: each heading of ``award_levels`` starts one award section."""

    name = "ubc_sections"
    version = "0.1.0"
    award_levels = (2, 3)

    def parse(self, snaps: list[SnapshotView], source: SourceConfig, ctx: ParseContext) -> AdapterResult:
        result = AdapterResult()
        by_key = {s.key: s for s in snaps}
        fetched_at = format_utc(ctx.now)
        for snap in snaps:
            if snap.media_type != "text/html":
                continue
            blocks = blocks_of(snap)
            counts = {lv: sum(1 for b in blocks if b.level == lv and not _SKIP_HEADINGS.match(b.text))
                      for lv in self.award_levels}
            # award headings repeat at one level; a lone category heading above them (e.g. "Awards") is not an award
            level = max((lv for lv in counts if counts[lv]), key=lambda lv: (counts[lv], lv), default=None)
            if level is None:
                result.pending.append({"item": snap.url, "reason": "no award headings of the expected level found; "
                                       "page structure unknown, nothing guessed"})
                continue
            sections, current = [], None
            for block in blocks:
                if block.level and block.level <= level:
                    current = [block, []] if block.level == level and not _SKIP_HEADINGS.match(block.text) else None
                    if current:
                        sections.append(current)
                elif current is not None and block.level == 0 and block.text.strip():
                    current[1].append(block)
            seen: dict[str, int] = {}
            for heading, paragraphs in sections:
                if not paragraphs:
                    result.pending.append({"item": f"{snap.url} :: {heading.text}", "reason": "heading without body text"})
                    continue
                m = _NUMBER_AT_END.search(heading.text)
                title = heading.text[: m.start()].strip() if m else heading.text
                native = m.group(1) if m else slugify(title)
                seen[native] = seen.get(native, 0) + 1
                if seen[native] > 1:  # same title twice on one page: keep both, distinguishable and stable
                    native = f"{native}-{seen[native]}"
                result.candidates.append(_record_for(title, native, paragraphs, snap, source, by_key, fetched_at, snap.url))
        result.stats = {"sections_found": len(result.candidates) + len(result.pending), "records": len(result.candidates)}
        return result


class ListingDetailAdapter(SectionedAwardsAdapter):
    """Listing page (depth 0) linking to detail pages (depth 1); each detail page is one award."""

    name = "indspire_funding"

    def select_links(self, doc: ExtractedDocument, url: str, source: SourceConfig, depth: int) -> list[str]:
        if depth > 0:
            return []
        base = url.split("#")[0].rstrip("/")
        out: list[str] = []
        for link in doc.links:
            href = link.href.split("#")[0]
            if href.rstrip("/") != base and href not in out and link.text:
                out.append(href)
        return out

    def parse(self, snaps: list[SnapshotView], source: SourceConfig, ctx: ParseContext) -> AdapterResult:
        result = AdapterResult()
        by_key = {s.key: s for s in snaps}
        fetched_at = format_utc(ctx.now)
        details = [s for s in snaps if s.media_type == "text/html" and s.url.rstrip("/") != source.url.rstrip("/")]
        for snap in details:
            blocks = blocks_of(snap)
            heads = [b for b in blocks if b.level in (1, 2) and not _SKIP_HEADINGS.match(b.text)]
            body = [b for b in blocks if b.level == 0 and b.text.strip()]
            if not heads or not body:
                result.pending.append({"item": snap.url, "reason": "detail page without a recognisable title/body"})
                continue
            title = heads[0].text
            native = slugify(snap.url.rstrip("/").rsplit("/", 1)[-1] or title)
            result.candidates.append(_record_for(title, native, body, snap, source, by_key, fetched_at, snap.url))
        listing = [s for s in snaps if s.url.rstrip("/") == source.url.rstrip("/")]
        result.stats = {"listing_pages": len(listing), "detail_pages": len(details), "records": len(result.candidates)}
        if listing and not details:
            result.pending.append({"item": source.url, "reason": "listing fetched but no detail pages were fetched "
                                   "(page budget or access); nothing inferred from the listing alone"})
        return result
