"""Text and link extraction from HTML and text-based PDF snapshots.

The text artefact layout is a contract with :mod:`navigator.core.evidence`:
blocks separated by a blank line, headings written as ``#``-prefixed blocks, PDF pages
separated by a form feed. A PDF without a text layer is reported as ``ocr_required``; it is
never silently treated as parsed.
"""

from __future__ import annotations

import io
import re
from dataclasses import dataclass, field
from urllib.parse import urljoin

from bs4 import BeautifulSoup, NavigableString, Tag
from bs4.dammit import UnicodeDammit

from navigator.core.evidence import BLOCK_SEPARATOR, PAGE_SEPARATOR

EXTRACTOR_NAME = "navigator-text"
EXTRACTOR_VERSION = "1.0.0"

_WS = re.compile(r"\s+")
_HEADINGS = {f"h{i}": i for i in range(1, 7)}
_SKIP = {"script", "style", "noscript", "template", "svg", "iframe", "form", "button", "select"}
_BOILERPLATE = {"nav", "header", "footer", "aside"}
_INLINE = {
    "a",
    "span",
    "strong",
    "em",
    "b",
    "i",
    "u",
    "sup",
    "sub",
    "abbr",
    "code",
    "small",
    "mark",
    "cite",
    "q",
    "time",
    "label",
    "font",
    "br",
    "wbr",
    "s",
    "del",
    "ins",
    "bdi",
    "data",
    "dfn",
}
_TEXT_BLOCKS = {"p", "pre", "blockquote", "dt", "dd", "caption", "figcaption", "summary"}
_CONTAINERS = {
    "div",
    "section",
    "article",
    "ul",
    "ol",
    "dl",
    "table",
    "tbody",
    "thead",
    "tfoot",
    "details",
    "main",
    "body",
    "html",
    "figure",
    "fieldset",
    "address",
    "center",
}


@dataclass
class Block:
    kind: str  # heading | paragraph | list_item | table_row
    text: str
    level: int = 0
    page: int | None = None


@dataclass
class Link:
    href: str
    text: str
    heading: str | None = None


@dataclass
class ExtractedDocument:
    media_type: str
    status: str  # ok | empty | ocr_required | encrypted | unreadable
    blocks: list[Block] = field(default_factory=list)
    links: list[Link] = field(default_factory=list)
    title: str | None = None
    page_count: int | None = None
    pages_without_text: list[int] = field(default_factory=list)
    meta: dict = field(default_factory=dict)
    note: str | None = None

    @property
    def text(self) -> str:
        return render_text(self.blocks)


def _clean(text: str) -> str:
    return _WS.sub(" ", text).strip()


_BLOCKISH = {
    "br",
    "hr",
    "p",
    "div",
    "li",
    "ul",
    "ol",
    "tr",
    "td",
    "th",
    "table",
    "dd",
    "dt",
    "dl",
    "section",
    "article",
    "blockquote",
    "caption",
    *_HEADINGS,
}


def _inline_text(tag: Tag) -> str:
    """Text of ``tag`` with inline markup glued ("here" + "." -> "here.") and block breaks spaced."""
    parts: list[str] = []

    def rec(node: Tag) -> None:
        for child in node.children:
            if isinstance(child, NavigableString):
                if child.__class__.__name__ not in {"Comment", "Doctype", "CData", "ProcessingInstruction"}:
                    parts.append(str(child))
            elif isinstance(child, Tag) and child.name not in _SKIP:
                if child.name in _BLOCKISH:
                    parts.append(" ")
                    rec(child)
                    parts.append(" ")
                else:
                    rec(child)

    rec(tag)
    return _clean("".join(parts))


def render_text(blocks: list[Block]) -> str:
    """Serialise blocks to the artefact format (page breaks only when blocks carry pages)."""
    if not any(b.page for b in blocks):
        return BLOCK_SEPARATOR.join(_render_block(b) for b in blocks)
    pages: dict[int, list[str]] = {}
    for b in blocks:
        pages.setdefault(b.page or 1, []).append(_render_block(b))
    last = max(pages)
    return PAGE_SEPARATOR.join(BLOCK_SEPARATOR.join(pages.get(n, [])) for n in range(1, last + 1))


def _render_block(block: Block) -> str:
    return ("#" * block.level + " " + block.text) if block.kind == "heading" else block.text


# ------------------------------------------------------------------------------- HTML


def _pick_main(soup: BeautifulSoup) -> Tag:
    main = soup.find("main") or soup.find(attrs={"role": "main"}) or soup.find(id="wb-cont")
    return main or soup.body or soup


def _is_boilerplate(tag: Tag) -> bool:
    if tag.name in _BOILERPLATE:
        return True
    role = (tag.get("role") or "").lower()
    return role in {"navigation", "banner", "contentinfo", "complementary", "search"}


def _walk(container: Tag, blocks: list[Block]) -> None:
    buffer: list[str] = []

    def flush() -> None:
        text = _clean(" ".join(buffer))
        buffer.clear()
        if text:
            blocks.append(Block("paragraph", text))

    for child in container.children:
        if isinstance(child, NavigableString):
            if child.__class__.__name__ in {"Comment", "Doctype", "CData", "ProcessingInstruction"}:
                continue
            buffer.append(str(child))
            continue
        if not isinstance(child, Tag):
            continue
        name = child.name
        if name in _SKIP or _is_boilerplate(child):
            continue
        if name in _INLINE:
            buffer.append(_inline_text(child))
            continue
        flush()
        if name in _HEADINGS:
            text = _inline_text(child)
            if text:
                blocks.append(Block("heading", text, level=_HEADINGS[name]))
        elif name in _TEXT_BLOCKS:
            text = _inline_text(child)
            if text:
                blocks.append(Block("paragraph", text))
        elif name == "li":
            if child.find(["ul", "ol", "p", "div", "table"]):
                _walk(child, blocks)
            else:
                text = _inline_text(child)
                if text:
                    blocks.append(Block("list_item", text))
        elif name == "tr":
            cells = [_inline_text(c) for c in child.find_all(["th", "td"])]
            cells = [c for c in cells if c]
            if cells:
                blocks.append(Block("table_row", " | ".join(cells)))
        elif name in _CONTAINERS or name:
            _walk(child, blocks)
    flush()


def _decode(data: bytes) -> str:
    return UnicodeDammit(data, is_html=True).unicode_markup or data.decode("utf-8", "replace")


def _meta_date(soup: BeautifulSoup, names: tuple[str, ...]) -> str | None:
    for name in names:
        tag = soup.find("meta", attrs={"name": re.compile(f"^{re.escape(name)}$", re.I)})
        if tag and tag.get("content"):
            return str(tag["content"]).strip()
    return None


def extract_html(data: bytes, base_url: str | None = None) -> ExtractedDocument:
    soup = BeautifulSoup(_decode(data), "lxml")
    title = _inline_text(soup.title) if soup.title else None
    modified = None
    time_tag = soup.find("time", attrs={"property": "dateModified"})
    if time_tag:
        modified = _inline_text(time_tag) or time_tag.get("datetime")
    modified = modified or _meta_date(soup, ("dcterms.modified", "last-modified"))
    issued = _meta_date(soup, ("dcterms.issued", "dcterms.created"))

    main = _pick_main(soup)
    blocks: list[Block] = []
    _walk(main, blocks)

    links: list[Link] = []
    seen: set[tuple[str, str]] = set()
    heading: str | None = None
    for el in main.descendants:
        if not isinstance(el, Tag):
            continue
        if el.name in _HEADINGS:
            heading = _inline_text(el) or heading
        elif el.name == "a" and el.get("href"):
            href = str(el["href"]).strip()
            if href.startswith(("mailto:", "tel:", "javascript:", "#")):
                continue
            absolute = urljoin(base_url, href) if base_url else href
            text = _inline_text(el)
            if (absolute, text) not in seen:
                seen.add((absolute, text))
                links.append(Link(absolute, text, heading))

    status = "ok" if blocks else "empty"
    return ExtractedDocument(
        "text/html",
        status,
        blocks,
        links,
        title,
        meta={"date_modified": modified, "date_issued": issued},
    )


# -------------------------------------------------------------------------------- PDF


def extract_pdf(data: bytes) -> ExtractedDocument:
    from pypdf import PdfReader
    from pypdf.errors import PyPdfError

    try:
        reader = PdfReader(io.BytesIO(data))
        if reader.is_encrypted and not reader.decrypt(""):
            return ExtractedDocument("application/pdf", "encrypted", note="password-protected PDF")
        page_total = len(reader.pages)
        blocks: list[Block] = []
        empty_pages: list[int] = []
        for number, page in enumerate(reader.pages, start=1):
            raw = (page.extract_text() or "").replace("\r\n", "\n").replace("\r", "\n")
            paragraphs = [_clean(p) for p in re.split(r"\n\s*\n", raw)]
            paragraphs = [p for p in paragraphs if p]
            if not paragraphs:
                empty_pages.append(number)
            blocks.extend(Block("paragraph", p, page=number) for p in paragraphs)
        title = None
        if reader.metadata and reader.metadata.title:
            title = _clean(str(reader.metadata.title))
    except (PyPdfError, ValueError, OSError, KeyError) as exc:
        return ExtractedDocument("application/pdf", "unreadable", note=f"{type(exc).__name__}: {exc}")

    if not blocks:
        return ExtractedDocument(
            "application/pdf",
            "ocr_required",
            title=title,
            page_count=page_total,
            pages_without_text=empty_pages,
            note="no extractable text layer; OCR is not performed in this build",
        )
    if empty_pages:
        # keep page numbering stable: mark empty pages so a later OCR pass can fill them
        for n in empty_pages:
            blocks.append(Block("paragraph", "", page=n))
        blocks.sort(key=lambda b: b.page or 0)
    return ExtractedDocument(
        "application/pdf",
        "ok",
        blocks,
        [],
        title,
        page_total,
        empty_pages,
        note="some pages have no text layer (ocr_required for those pages)" if empty_pages else None,
    )


def extract(data: bytes, media_type: str, base_url: str | None = None) -> ExtractedDocument:
    lowered = (media_type or "").lower()
    if data[:5] == b"%PDF-" or "pdf" in lowered:
        return extract_pdf(data)
    if "html" in lowered or data.lstrip()[:15].lower().startswith((b"<!doctype html", b"<html")):
        return extract_html(data, base_url)
    return ExtractedDocument(
        lowered or "application/octet-stream", "unreadable", note=f"unsupported media type {media_type!r}"
    )
