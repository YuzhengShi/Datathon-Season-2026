"""A page saved by a PERSON in their own browser, brought into the evidence store with its provenance.

Some sites refuse automated clients (HTTP 403). This project never works around that: no changed User-Agent, no
retries, no headless browser. A person who can open the page in a browser may save it ("Webpage, HTML only" or PDF) and
import it here. The snapshot is content-addressed exactly like a fetched one, the fetch index says
``acquisition: manual_upload`` and who saved it and when, the audit log gets a ``manual_import`` row, and every
evidence check runs unchanged. Nothing here touches the network and the source's allowlist still applies.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from navigator.core.timeutil import format_utc
from navigator.core.urlpolicy import canonicalize_url, check_url
from navigator.ingestion.fetch_stage import FetchIndex, _store_extraction, append_audit
from navigator.ingestion.snapshots import SnapshotStore
from navigator.ingestion.sources import SourceConfig
from navigator.ingestion.text import extract

MAX_BYTES = 10 * 1024 * 1024
MEDIA_TYPES = {".html": "text/html", ".htm": "text/html", ".pdf": "application/pdf"}


class ManualImportError(ValueError):
    """The saved page cannot be imported (the message says why)."""


def import_manual_snapshot(
    source: SourceConfig,
    url: str,
    file_path: Path,
    *,
    saved_by: str,
    saved_at: datetime,
    store: SnapshotStore,
    index: FetchIndex,
    audit_path: Path,
    run_id: str = "manual-import",
) -> dict:
    saved_by = (saved_by or "").strip()
    if not saved_by:
        raise ManualImportError("say who saved the page (--saved-by): the provenance is part of the evidence")
    decision = check_url(url, source.rules())
    if not decision.ok:
        raise ManualImportError(f"{url} is outside the allowlist of source {source.source_id} ({decision.reason})")
    path = Path(file_path)
    media = MEDIA_TYPES.get(path.suffix.lower())
    if media is None:
        raise ManualImportError("only .html, .htm and .pdf files can be imported")
    if not path.is_file():
        raise ManualImportError(f"no such file: {path}")
    body = path.read_bytes()
    if not body:
        raise ManualImportError("the file is empty")
    if len(body) > MAX_BYTES:
        raise ManualImportError(f"the file is larger than {MAX_BYTES // (1024 * 1024)} MB")
    canon = canonicalize_url(url)
    raw = store.save_raw(body, media)
    doc = extract(body, media, canon)
    when = format_utc(saved_at)
    entry = {
        "status": "ok",
        "source_id": source.source_id,
        "snapshot_id": raw.snapshot_id,
        "raw_sha256": raw.raw_sha256,
        "raw_path": raw.raw_path,
        "media_type": media,
        "final_url": canon,
        "etag": None,
        "last_modified": None,
        "fetched_at": when,
        "http_status": None,
        "depth": 0,
        "acquisition": "manual_upload",
        "saved_by": saved_by,
    }
    _store_extraction(store, entry, doc, raw.raw_sha256)
    index.entries[canon] = entry
    index.failures.pop(canon, None)
    index.save()
    append_audit(
        audit_path,
        {
            "run_id": run_id,
            "source_id": source.source_id,
            "url": canon,
            "outcome": "manual_import",
            "reason": None,
            "http_status": None,
            "bytes": len(body),
            "requested_at": when,
            "depth": 0,
            "snapshot_id": raw.snapshot_id,
            "saved_by": saved_by,
        },
    )
    return {
        "source_id": source.source_id,
        "url": canon,
        "snapshot_id": raw.snapshot_id,
        "raw_sha256": raw.raw_sha256,
        "extraction_status": entry.get("extraction_status"),
        "acquisition": "manual_upload",
        "saved_by": saved_by,
        "saved_at": when,
    }
