"""Records from ISC directory detail pages (``https://www.sac-isc.gc.ca/eng/<id>/<id>``).

A detail page is an official Government of Canada listing of ONE award: name, provider, value, field of study,
province, number of awards, free-text eligibility and a link to the provider. It states NO deadline and no
application steps, and the pages seen were last modified years ago. A record built from it therefore says exactly
that, keeps the eligibility text unstructured (nothing is inferred) and sends the student to the provider.
"""

from __future__ import annotations

import dataclasses
import re

from navigator.core.ids import slugify
from navigator.ingestion.adapters.curated import curated_record
from navigator.ingestion.builder import SnapshotView
from navigator.ingestion.sources import SourceConfig

LABELS = (
    "Name",
    "Provider Name",
    "Value",
    "Field of Study",
    "Province/Territory",
    "Awards Available",
    "Other Eligibility Criteria",
    "Web Link",
    "Date modified",
)
_LABEL = re.compile(r"^(" + "|".join(re.escape(label) for label in LABELS) + r"):[ \t]*(.*)$", re.S)
_NUMBER = r"\$\s?(\d[\d,]*(?:\.\d{1,2})?)"


def parse_detail_fields(text: str) -> dict[str, str]:
    """Label -> value, whether the page text puts a value after its label or in the next paragraph.

    The first occurrence wins: "Province/Territory" appears again under "Contact Information".
    """
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    found: dict[str, str] = {}
    i = 0
    while i < len(paragraphs):
        match = _LABEL.match(paragraphs[i])
        if match:
            label, value = match.group(1), match.group(2).strip()
            if not value and i + 1 < len(paragraphs) and not _LABEL.match(paragraphs[i + 1]):
                if not paragraphs[i + 1].endswith(":"):
                    value = paragraphs[i + 1]
                    i += 1
            found.setdefault(label, value)
        i += 1
    return found


def amount_from_value(value: str | None) -> dict:
    """A curated-style amount from the directory's free "Value" text; anything unclear stays unspecified."""
    if not value:
        return {"kind": "unspecified", "currency": None, "unit": "unspecified", "raw_text": "not stated"}
    clean = value.replace("\u00a0", " ").strip()
    numbers = [n.replace(",", "") for n in re.findall(_NUMBER, clean)]
    lower = clean.lower()
    known = {"currency": "CAD", "unit": "unspecified", "raw_text": clean, "quotes": [clean]}
    if len(numbers) == 1 and re.fullmatch(_NUMBER, clean):
        return {"kind": "fixed", "fixed": numbers[0], **known}
    if len(numbers) == 1 and lower.startswith("up to"):
        return {"kind": "maximum", "maximum": numbers[0], **known}
    if (
        len(numbers) == 2
        and re.search(r"\s(?:-|\u2013|to)\s", clean)
        and re.fullmatch(rf"{_NUMBER}\s*\S+\s*{_NUMBER}", clean)
    ):
        low, high = sorted(numbers, key=float)
        return {"kind": "range", "minimum": low, "maximum": high, **known}
    return {"kind": "unspecified", "currency": None, "unit": "unspecified", "raw_text": clean, "quotes": [clean]}


def quote_prefix(text: str, limit: int = 300) -> str:
    """A real prefix of ``text`` (so it is a verbatim quote), cut at a sentence or word boundary."""
    text = text.strip()
    if len(text) <= limit:
        return text
    cut = text[:limit]
    end = max(cut.rfind(". "), cut.rfind("; "))
    if end > 80:
        return cut[: end + 1].strip()
    return cut[: cut.rfind(" ")].strip() if " " in cut else cut


def isc_detail_record(snap: SnapshotView, source: SourceConfig, now_iso: str) -> dict:
    fields = parse_detail_fields(snap.text)
    name, provider = fields.get("Name"), fields.get("Provider Name")
    if not name or not provider:
        raise ValueError("the page has no 'Name' and 'Provider Name' fields")
    web = fields.get("Web Link", "")
    web = web if web.startswith(("http://", "https://")) else ""
    criteria = fields.get("Other Eligibility Criteria", "")
    modified = fields.get("Date modified", "")
    facts = [f"Provider: {provider}."]
    if fields.get("Field of Study"):
        facts.append(f"Field of study: {fields['Field of Study']}.")
    if fields.get("Province/Territory"):
        facts.append(f"Province/territory: {fields['Province/Territory']}.")
    if fields.get("Awards Available"):
        facts.append(f"Awards available: {fields['Awards Available']}.")
    when = f" (page last modified {modified})" if modified else ""
    summary = (
        f"Listed in the Indigenous Services Canada bursaries directory{when}. {' '.join(facts)} "
        "The directory states no deadline or application steps: confirm everything on the provider's website."
    )
    entry = {
        "key": "isc-" + slugify(f"{name} {provider}", 70),
        "title": name,
        "opportunity_type": "award",
        "method": "deterministic_adapter",
        "official_url": snap.url,
        "snapshot": snap.url,
        "summary": summary,
        "application": {
            "route_type": "unknown",
            "url": web or None,
            "instructions": "The directory gives no application steps or deadline; use the provider's website or contact.",
            "quotes": [web] if web else [],
        },
        "cycles": [
            {
                "cycle_key": "unspecified",
                "label_raw": "not stated in the directory",
                "deadlines": [{"kind": "unspecified", "raw_text": "not stated in the directory"}],
                "amount": amount_from_value(fields.get("Value")),
                "eligibility": {
                    "mandatory": [],
                    "preferences": [],
                    "unstructured": [{"text": criteria[:1500], "quotes": [quote_prefix(criteria)]}] if criteria else [],
                },
            }
        ],
    }
    awarding = dataclasses.replace(source, provider_id=slugify(provider, 40) or "unknown", provider_name=provider)
    return curated_record(entry, [snap], awarding, now_iso)
