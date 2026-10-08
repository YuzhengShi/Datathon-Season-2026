"""ISC Indigenous Bursaries Search Tool: a *discovery index*, never a source of verified awards.

Entries are recorded under ``data/discovery`` with the declared count, observed rows, coverage and
pagination status; they do not become opportunities. Table columns are read from the raw HTML
because empty cells would otherwise shift columns in the plain-text artefact.
"""

from __future__ import annotations

import hashlib
import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from navigator.core.urlpolicy import canonicalize_url
from navigator.ingestion.adapters.base import Adapter, AdapterResult, ParseContext
from navigator.ingestion.builder import SnapshotView
from navigator.ingestion.sources import SourceConfig
from navigator.ingestion.text import ExtractedDocument

from navigator.core.timeutil import format_utc
from navigator.ingestion.adapters.isc_detail import isc_detail_record

COLUMNS = ("name", "province", "institution", "field_of_study", "indigenous_group")
_COUNT = re.compile(r"There (?:are|is)\s+([\d,]+)\s+bursar", re.I)
_NEXT = re.compile(r"^(next|suivant|more|load more|page\s*\d+|›|»)$", re.I)


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def parse_index_table(html: bytes, base_url: str) -> dict:
    """Entries + count/pagination facts from one index page (pure function, easy to test)."""
    soup = BeautifulSoup(html, "lxml")
    page_text = _norm(soup.get_text(" "))
    declared = int(m.group(1).replace(",", "")) if (m := _COUNT.search(page_text)) else None
    entries, pending = [], []
    for table in soup.find_all("table"):
        headers = [_norm(th.get_text(" ")).lower() for th in table.find_all("th")]
        if not (headers and headers[0].startswith("name") and any("province" in h for h in headers)):
            continue
        for ordinal, tr in enumerate(table.find_all("tr")):
            cells = tr.find_all("td")
            if not cells:
                continue
            if len(cells) != len(COLUMNS):
                pending.append({"item": f"row {ordinal}", "reason": f"unexpected column count {len(cells)}"})
                continue
            values = [_norm(c.get_text(" ")) for c in cells]
            link = cells[0].find("a", href=True)
            detail = canonicalize_url(urljoin(base_url, link["href"])) if link else None
            entry = dict(zip(COLUMNS, values, strict=True))
            fingerprint = hashlib.sha1("|".join([*values, str(ordinal)]).encode("utf-8")).hexdigest()[:16]
            entry.update(
                entry_id=detail or f"isc-row-{fingerprint}",
                detail_url=detail,
                row_ordinal=ordinal,
                status="discovery_only_not_verified",
            )
            entries.append(entry)
    pagination = [
        a for a in soup.find_all("a", href=True) if _NEXT.match(_norm(a.get_text(" "))) or a.get("rel") == ["next"]
    ]
    coverage = (len(entries) / declared) if declared else None
    return {
        "entries": entries,
        "pending": pending,
        "stats": {
            "declared_count": declared,
            "entries_observed": len(entries),
            "coverage": round(coverage, 4) if coverage is not None else None,
            "pagination_links": len(pagination),
            "pagination_complete": bool(entries)
            and not pagination
            and declared is not None
            and len(entries) == declared,
            "update_in_progress_notice": "update in progress" in page_text.lower(),
            "note": "Historical audit saw 538 entries on 2026-10-05; that is an observation, not a target.",
        },
    }


class IscIndexAdapter(Adapter):
    name = "isc_index"

    def select_links(self, doc: ExtractedDocument, url: str, source: SourceConfig, depth: int) -> list[str]:
        if depth > 0:
            return []
        # Detail pages of the rows whose province is British Columbia or National (the other provinces are not what
        # a UBC student needs first); the source's page budget bounds how many are followed. The index links use
        # http:// although the site is https-only, and an unreadable robots.txt over http means "do not fetch".
        wanted: set[str] = set()
        for block in doc.blocks:
            for line in (getattr(block, "text", "") or "").splitlines():
                cells = [" ".join(cell.split()) for cell in line.split(" | ")]
                if len(cells) >= 2 and cells[1] in ("British Columbia", "National"):
                    wanted.add(cells[0])
        return [
            link.href.replace("http://www.sac-isc.gc.ca/", "https://www.sac-isc.gc.ca/", 1)
            for link in doc.links
            if " ".join((link.text or "").split()) in wanted and "/eng/" in link.href and link.href != url
        ]

    def parse(self, snaps: list[SnapshotView], source: SourceConfig, ctx: ParseContext) -> AdapterResult:
        result = AdapterResult()
        index = next(
            (s for s in snaps if s.url.split("?")[0].rstrip("/") == source.url.split("?")[0].rstrip("/")), None
        )
        if index is None or ctx.read_raw is None:
            result.pending.append({"item": source.url, "reason": "index page snapshot not available"})
            return result
        parsed = parse_index_table(ctx.read_raw(index), index.url)
        result.discovery, result.pending, result.stats = parsed["entries"], parsed["pending"], parsed["stats"]
        if not parsed["entries"]:
            result.pending.append(
                {"item": source.url, "reason": "no bursary table found; structure unknown, nothing guessed"}
            )
        result.stats["detail_pages_fetched"] = len(snaps) - 1
        now_iso = format_utc(ctx.now)
        for snap in snaps:
            if snap is index:
                continue
            try:
                result.candidates.append(isc_detail_record(snap, source, now_iso))
            except (KeyError, ValueError) as exc:
                result.pending.append({"item": snap.url, "reason": f"directory detail page not understood: {exc}"})
        return result
