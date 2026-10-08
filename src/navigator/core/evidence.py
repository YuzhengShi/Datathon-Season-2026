"""Field-level evidence: a quote only counts if it really exists in a hashed snapshot.

Normalisation algorithm ``v1`` (applied to both the quote and the extracted text before any
comparison; recorded here so it is a stable contract):

1. Unicode NFKC.
2. Delete zero-width characters (U+200B-U+200D, U+2060, U+FEFF) and soft hyphens (U+00AD).
3. Map typographic quotes to ``'`` / ``"`` and all dash variants (U+2010-U+2015, U+2212) to ``-``.
4. Collapse every run of Unicode whitespace to one ASCII space and strip the ends.
5. Comparison is case-sensitive.

Text artefact layout (written by ``navigator.ingestion.text``): blocks are separated by a blank
line (``"\\n\\n"``), headings are blocks starting with ``#``, PDF pages are separated by a form
feed (``"\\f"``). ``pdf_page`` is 1-based; ``paragraph_index`` is the 0-based block index inside
the page (PDF) or the whole text (HTML); ``text_start``/``text_end`` are offsets into the
*normalised* scope (page, paragraph or whole text, whichever the locator narrows to).
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from navigator.core.issues import Issue

NORMALIZATION_VERSION = "v1"
MAX_QUOTE_CHARS = 500
BLOCK_SEPARATOR = "\n\n"
PAGE_SEPARATOR = "\f"

_ZERO_WIDTH = re.compile("[\u200b\u200c\u200d\u2060\ufeff\u00ad]")
_WHITESPACE = re.compile(r"\s+")
_PUNCTUATION = str.maketrans(
    {
        "\u2018": "'",
        "\u2019": "'",
        "\u201a": "'",
        "\u201b": "'",
        "\u201c": '"',
        "\u201d": '"',
        "\u201e": '"',
        "\u201f": '"',
        "\u2010": "-",
        "\u2011": "-",
        "\u2012": "-",
        "\u2013": "-",
        "\u2014": "-",
        "\u2015": "-",
        "\u2212": "-",
    }
)


class PathEscapeError(ValueError):
    """A stored path points outside the artifact root."""


class QuoteNotFoundError(ValueError):
    """The requested quote is not present in the text."""


def normalize_text(text: str) -> str:
    text = unicodedata.normalize("NFKC", text)
    text = _ZERO_WIDTH.sub("", text)
    text = text.translate(_PUNCTUATION)
    return _WHITESPACE.sub(" ", text).strip()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def safe_join(root: Path, relative: str) -> Path:
    """Resolve ``relative`` under ``root`` or raise :class:`PathEscapeError`."""
    if not relative or "\x00" in relative:
        raise PathEscapeError("empty or NUL-containing path")
    if re.match(r"^[A-Za-z]:", relative) or relative.startswith(("/", "\\")):
        raise PathEscapeError(f"absolute path not allowed: {relative!r}")
    posix = PurePosixPath(relative.replace("\\", "/"))
    if ".." in posix.parts:
        raise PathEscapeError(f"path traversal not allowed: {relative!r}")
    base = root.resolve()
    candidate = (base / Path(*posix.parts)).resolve()
    if candidate != base and base not in candidate.parents:
        raise PathEscapeError(f"path escapes artifact root: {relative!r}")
    return candidate


def split_pages(text: str) -> list[str]:
    return text.split(PAGE_SEPARATOR)


def split_blocks(text: str) -> list[str]:
    return text.split(BLOCK_SEPARATOR)


def is_heading_block(block: str) -> bool:
    return block.startswith("#")


def heading_text(block: str) -> str:
    return block.lstrip("#").strip()


def nearest_heading(blocks: list[str], index: int) -> str | None:
    """Heading text at or above ``index`` (a heading block is its own heading)."""
    for i in range(min(index, len(blocks) - 1), -1, -1):
        if is_heading_block(blocks[i]):
            return heading_text(blocks[i])
    return None


def locate_quote(
    text: str,
    quote: str,
    *,
    pdf_page: int | None = None,
    paragraph_index: int | None = None,
) -> dict:
    """Build a locator for ``quote`` (first match unless narrowed by page/paragraph hints)."""
    nq = normalize_text(quote)
    if not nq:
        raise QuoteNotFoundError("empty quote")
    pages = split_pages(text)
    page_numbers = [pdf_page] if pdf_page else (range(1, len(pages) + 1) if len(pages) > 1 else [0])
    for page_no in page_numbers:
        page_text = pages[page_no - 1] if page_no else text
        blocks = split_blocks(page_text)
        indices = [paragraph_index] if paragraph_index is not None else range(len(blocks))
        for idx in indices:
            if idx is None or idx >= len(blocks):
                continue
            norm_block = normalize_text(blocks[idx])
            pos = norm_block.find(nq)
            if pos >= 0:
                locator: dict = {"paragraph_index": idx, "text_start": pos, "text_end": pos + len(nq)}
                heading = nearest_heading(blocks, idx)
                if heading is not None:
                    locator["heading"] = heading
                if page_no:
                    locator["pdf_page"] = page_no
                return locator
    raise QuoteNotFoundError(f"quote not found in text: {quote[:80]!r}")


@dataclass(frozen=True)
class LoadedText:
    text: str
    raw_sha256: str
    text_sha256: str


def _load_snapshot(ref: dict, root: Path, path: str, cache: dict) -> tuple[LoadedText | None, list[Issue]]:
    key = (ref.get("raw_path"), ref.get("text_path"))
    if key in cache:
        return cache[key]
    issues: list[Issue] = []
    loaded: LoadedText | None = None
    try:
        raw_file = safe_join(root, str(ref.get("raw_path") or ""))
        text_file = safe_join(root, str(ref.get("text_path") or ""))
    except PathEscapeError as exc:
        issues.append(Issue(path, "evidence.path_escape", str(exc)))
        cache[key] = (None, issues)
        return cache[key]
    if not raw_file.is_file():
        issues.append(Issue(path, "evidence.raw_missing", f"raw snapshot not found: {ref['raw_path']}"))
    if not text_file.is_file():
        issues.append(Issue(path, "evidence.text_missing", f"text file not found: {ref['text_path']}"))
    if not issues:
        try:
            text = text_file.read_bytes().decode("utf-8")
        except UnicodeDecodeError:
            issues.append(Issue(path, "evidence.text_not_utf8", "extracted text is not UTF-8"))
        else:
            loaded = LoadedText(text, sha256_file(raw_file), sha256_file(text_file))
    cache[key] = (loaded, issues)
    return cache[key]


def verify_source_ref(ref: dict, root: Path, path: str, cache: dict) -> list[Issue]:
    """Check that a ``source_ref``'s files exist under ``root`` and match their declared hashes."""
    loaded, issues = _load_snapshot(ref, root, path, cache)
    if loaded is None:
        return list(issues)
    out = list(issues)
    for field, actual in (("raw_sha256", loaded.raw_sha256), ("text_sha256", loaded.text_sha256)):
        if ref.get(field) != actual:
            out.append(
                Issue(
                    f"{path}/{field}",
                    f"source_ref.{field.split('_')[0]}_hash_mismatch",
                    "recomputed hash does not match the declared hash",
                )
            )
    return out


def verify_evidence_item(
    evidence: dict,
    refs_by_snapshot: dict[str, dict],
    root: Path,
    path: str,
    cache: dict,
) -> list[Issue]:
    """Check one evidence object against the snapshot files under ``root``.

    ``cache`` memoises file reads and hashes for the whole validation run.
    """
    ref = refs_by_snapshot.get(evidence.get("snapshot_id"))
    if ref is None:
        return [
            Issue(
                f"{path}/snapshot_id",
                "evidence.snapshot_ref_missing",
                "evidence points at a snapshot that is not listed in source_refs",
            )
        ]
    issues: list[Issue] = []
    if evidence.get("source_id") != ref.get("source_id"):
        issues.append(Issue(f"{path}/source_id", "evidence.source_mismatch", "source_id differs from source_ref"))
    loaded, load_issues = _load_snapshot(ref, root, path, cache)
    issues.extend(load_issues)
    if loaded is None:
        return issues

    for field, actual in (("raw_sha256", loaded.raw_sha256), ("text_sha256", loaded.text_sha256)):
        if evidence.get(field) != actual:
            issues.append(
                Issue(
                    f"{path}/{field}",
                    f"evidence.{field.split('_')[0]}_hash_mismatch",
                    "recomputed hash does not match the evidence record",
                )
            )
        if ref.get(field) not in (None, actual):
            issues.append(
                Issue(
                    f"{path}/{field}",
                    f"evidence.{field.split('_')[0]}_hash_mismatch",
                    "recomputed hash does not match the source_ref record",
                )
            )

    quote = evidence.get("quote") or ""
    if len(quote) > MAX_QUOTE_CHARS:
        issues.append(Issue(f"{path}/quote", "evidence.quote_too_long", f"quote exceeds {MAX_QUOTE_CHARS} chars"))
    nq = normalize_text(quote)
    if not nq:
        issues.append(Issue(f"{path}/quote", "evidence.quote_empty", "quote is empty"))
        return issues

    locator = evidence.get("locator") or {}
    page = locator.get("pdf_page")
    para = locator.get("paragraph_index")
    scope = loaded.text
    page_blocks_source = scope
    if page is not None:
        pages = split_pages(loaded.text)
        if not isinstance(page, int) or page < 1 or page > len(pages):
            issues.append(Issue(f"{path}/locator/pdf_page", "evidence.page_out_of_range", f"no page {page}"))
            return issues
        scope = pages[page - 1]
        page_blocks_source = scope
    blocks = split_blocks(page_blocks_source)
    block_index = para
    if para is not None:
        if not isinstance(para, int) or para < 0 or para >= len(blocks):
            issues.append(
                Issue(
                    f"{path}/locator/paragraph_index",
                    "evidence.paragraph_out_of_range",
                    f"no paragraph {para}",
                )
            )
            return issues
        scope = blocks[para]
    normalized_scope = normalize_text(scope)

    if nq not in normalized_scope:
        everywhere = nq in normalize_text(loaded.text.replace(PAGE_SEPARATOR, " "))
        issues.append(
            Issue(
                f"{path}/quote",
                "evidence.quote_wrong_scope" if everywhere else "evidence.quote_not_found",
                "quote exists elsewhere in the text but not in the cited page/paragraph"
                if everywhere
                else "quote does not appear in the extracted text",
            )
        )
        return issues

    start, end = locator.get("text_start"), locator.get("text_end")
    if start is not None or end is not None:
        if not isinstance(start, int) or not isinstance(end, int) or normalized_scope[start:end] != nq:
            issues.append(
                Issue(
                    f"{path}/locator",
                    "evidence.offsets_mismatch",
                    "text_start/text_end do not select the quote in the normalised text",
                )
            )

    heading = locator.get("heading")
    if heading is not None:
        if block_index is None:
            block_index = next((i for i, b in enumerate(blocks) if nq in normalize_text(b)), len(blocks) - 1)
        actual = nearest_heading(blocks, block_index)
        if actual is None or normalize_text(actual) != normalize_text(str(heading)):
            issues.append(
                Issue(
                    f"{path}/locator/heading",
                    "evidence.heading_mismatch",
                    f"nearest heading is {actual!r}, locator says {heading!r}",
                )
            )
    return issues
