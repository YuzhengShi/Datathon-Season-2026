"""Helpers shared by the source adapters: reading the text artefact as blocks, finding explicit dates."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date

from navigator import SCHEMA_VERSION
from navigator.core.evidence import heading_text, is_heading_block, normalize_text
from navigator.ingestion.builder import SnapshotView

MONTHS = {m: i for i, m in enumerate(
    ["january", "february", "march", "april", "may", "june", "july", "august", "september", "october",
     "november", "december"], start=1)}
DATE_RE = re.compile(r"\b(" + "|".join(m.capitalize() for m in MONTHS) + r")\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(\d{4})\b")
DEADLINE_CUE = re.compile(r"\b(deadline|due|closes?|closing|apply by|no later than|submitted by|submit by)\b", re.I)
ELIGIBILITY_CUE = re.compile(
    r"\b(eligib|must\b|required?\b|requirements?\b|open to|applicants?\b|enrolled|citizens?\b|member of|"
    r"residents?\b|self-identif|minimum|gpa|average of|indigenous|first nations|m[ée]tis|inuit)", re.I)


@dataclass(frozen=True)
class Block:
    index: int
    text: str
    level: int  # 0 = paragraph, 1-6 = heading level


def blocks_of(snap: SnapshotView) -> list[Block]:
    """Blocks of the (single-page HTML) text artefact; ``index`` equals the evidence ``paragraph_index``."""
    out = []
    for i, raw in enumerate(snap.text.split("\n\n")):
        if is_heading_block(raw):
            level = len(raw) - len(raw.lstrip("#"))
            out.append(Block(i, heading_text(raw), level))
        else:
            out.append(Block(i, raw, 0))
    return out


def first_sentence(text: str, limit: int = 240) -> str:
    sentence = re.split(r"(?<=[.!?])\s+", normalize_text(text), maxsplit=1)[0]
    return sentence if len(sentence) <= limit else sentence[: limit - 1].rstrip() + "…"


def explicit_dates(text: str) -> list[tuple[date, str]]:
    """(date, matched text) for every ``Month D, YYYY`` in ``text`` - only dates that carry a year."""
    found = []
    for m in DATE_RE.finditer(text):
        try:
            found.append((date(int(m.group(3)), MONTHS[m.group(1).lower()], int(m.group(2))), m.group(0)))
        except ValueError:
            continue
    return found


def empty_amount() -> dict:
    return {"kind": "unspecified", "currency": None, "unit": "unspecified", "renewable": None,
            "raw_text": "", "evidence_ids": []}


def base_record(*, rid: str, key: str, title: str, otype: str, provider: dict, official_url: str, summary: str,
                application: dict, cycles: list, documents: list, fetched_at: str, method: str = "deterministic_adapter",
                demo: bool = False) -> dict:
    return {
        "schema_version": SCHEMA_VERSION, "id": rid, "source_record_key": key, "title": title,
        "opportunity_type": otype, "provider": provider, "official_url": official_url, "application": application,
        "summary": summary, "cycles": cycles, "required_documents": documents, "evidence": [], "source_refs": [],
        "review_status": "machine_checked", "publication_status": "published", "extraction_method": method,
        "last_fetched_at": fetched_at, "last_verified_at": None, "content_fingerprint": "sha256:" + "0" * 64,
        "is_demo": demo,
    }
