"""Bounded, resumable crawl of the configured sources (depth <= 2, default 50 pages per run).

* Raw files are content-addressed and never overwritten; a failed fetch never replaces a good
  snapshot (failures live in the index under ``failures``).
* ``resume`` skips URLs that already have a verified snapshot; ``refresh`` re-checks them with
  conditional requests (304 reuses the existing snapshot).
* Only the extraction step re-runs when the extractor version changes, never the downloads.
* The index and audit trail are rewritten atomically after every page, so a dropped session
  can continue exactly where it stopped.
"""

from __future__ import annotations

from collections import deque
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from navigator.core.timeutil import format_utc
from navigator.core.urlpolicy import UnsafeUrlError, canonicalize_url
from navigator.ingestion.adapters.base import Adapter
from navigator.ingestion.builder import SnapshotView
from navigator.ingestion.fetcher import Fetcher
from navigator.ingestion.fsutil import atomic_write_text, read_json, write_json
from navigator.ingestion.manifest import RunManifest
from navigator.ingestion.snapshots import SnapshotStore
from navigator.ingestion.sources import SourceConfig
from navigator.ingestion.text import EXTRACTOR_NAME, EXTRACTOR_VERSION, ExtractedDocument, extract

import json


class FetchIndex:
    """``discovery/fetch_index.json``: canonical URL -> snapshot, plus remembered failures."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.entries: dict[str, dict] = {}
        self.failures: dict[str, dict] = {}
        if path.is_file():
            data = read_json(path)
            self.entries, self.failures = data.get("entries", {}), data.get("failures", {})

    def save(self) -> None:
        write_json(self.path, {"version": 1, "entries": self.entries, "failures": self.failures})


def append_audit(path: Path, row: dict) -> None:
    lines = path.read_text(encoding="utf-8") if path.is_file() else ""
    atomic_write_text(path, lines + json.dumps(row, sort_keys=True, ensure_ascii=False) + "\n")


@dataclass
class FetchStageResult:
    per_source: dict[str, dict] = field(default_factory=dict)
    snapshots: dict[str, list[SnapshotView]] = field(default_factory=dict)
    pages_fetched: int = 0
    unvisited: list[str] = field(default_factory=list)
    robots: dict[str, str] = field(default_factory=dict)


def snapshot_view(entry: dict, source: SourceConfig, store: SnapshotStore, key: str) -> SnapshotView:
    return SnapshotView(
        key=key,
        source_id=source.source_id,
        url=entry["final_url"],
        media_type=entry["media_type"],
        snapshot_id=entry["snapshot_id"],
        raw_sha256=entry["raw_sha256"],
        raw_path=entry["raw_path"],
        text_sha256=entry["text_sha256"],
        text_path=entry["text_path"],
        fetched_at=entry["fetched_at"],
        text=store.read_text(entry["text_path"]),
        role=source.role,
        source_modified_at=entry.get("source_modified_at"),
    )


def _store_extraction(store: SnapshotStore, entry: dict, doc: ExtractedDocument, raw_sha: str) -> None:
    stored = store.save_text(raw_sha, doc.text, EXTRACTOR_NAME, EXTRACTOR_VERSION)
    entry.update(
        text_path=stored.text_path,
        text_sha256=stored.text_sha256,
        extractor=EXTRACTOR_NAME,
        extractor_version=EXTRACTOR_VERSION,
        extraction_status=doc.status,
        source_modified_at=(doc.meta.get("date_modified") and f"{doc.meta['date_modified'][:10]}T00:00:00Z")
        if doc.meta.get("date_modified") and len(doc.meta["date_modified"]) >= 10
        else None,
    )


def run_fetch_stage(
    sources: list[SourceConfig],
    fetcher: Fetcher,
    store: SnapshotStore,
    index: FetchIndex,
    adapters: Mapping[str, Adapter],
    *,
    run_id: str,
    now: datetime,
    audit_path: Path,
    max_pages: int = 50,
    max_depth: int = 2,
    resume: bool = False,
    refresh: bool = False,
    manifest: RunManifest | None = None,
) -> FetchStageResult:
    result = FetchStageResult()
    stamp = format_utc(now)
    for source in sources:
        stats = {
            "attempted": 0,
            "succeeded": 0,
            "failed": 0,
            "blocked": 0,
            "skipped": 0,
            "not_modified": 0,
            "failures": [],
        }
        result.per_source[source.source_id] = stats
        result.snapshots[source.source_id] = []
        adapter = adapters.get(source.parser)
        queue: deque[tuple[str, int]] = deque([(source.url, 0)])
        seen: set[str] = set()
        while queue:
            url, depth = queue.popleft()
            try:
                canon = canonicalize_url(url)
            except UnsafeUrlError:
                continue
            if canon in seen:
                continue
            seen.add(canon)
            entry = index.entries.get(canon)
            have_file = bool(entry and store.verify_raw(entry["raw_path"], entry["raw_sha256"]))

            if entry and have_file and resume and not refresh:
                stats["skipped"] += 1
                if entry.get("extractor_version") != EXTRACTOR_VERSION:  # re-extract only; no download
                    raw = store.read_raw(entry["raw_path"])
                    _store_extraction(
                        store, entry, extract(raw, entry["media_type"], entry["final_url"]), entry["raw_sha256"]
                    )
                    index.save()
            else:
                if result.pages_fetched >= max_pages:
                    result.unvisited.append(url)
                    stats["skipped"] += 1
                    continue
                result.pages_fetched += 1
                stats["attempted"] += 1
                outcome = fetcher.fetch(
                    url,
                    source.rules(),
                    etag=entry.get("etag") if entry else None,
                    last_modified=entry.get("last_modified") if entry else None,
                    have_snapshot=have_file and refresh,
                )
                if outcome.robots_status:
                    result.robots[(url.split("/")[2])] = outcome.robots_status
                row = {
                    **outcome.audit(),
                    "run_id": run_id,
                    "source_id": source.source_id,
                    "requested_at": stamp,
                    "depth": depth,
                }
                if outcome.outcome == "ok" and outcome.body is not None:
                    media = outcome.media_type or "application/octet-stream"
                    raw = store.save_raw(outcome.body, media)
                    doc = extract(outcome.body, media, outcome.final_url)
                    new_entry = {
                        "status": "ok",
                        "source_id": source.source_id,
                        "snapshot_id": raw.snapshot_id,
                        "raw_sha256": raw.raw_sha256,
                        "raw_path": raw.raw_path,
                        "media_type": media,
                        "final_url": canonicalize_url(outcome.final_url or url),
                        "etag": outcome.etag,
                        "last_modified": outcome.last_modified,
                        "fetched_at": stamp,
                        "http_status": outcome.status,
                        "depth": depth,
                    }
                    _store_extraction(store, new_entry, doc, raw.raw_sha256)
                    index.entries[canon] = new_entry
                    index.failures.pop(canon, None)
                    entry = new_entry
                    row["snapshot_id"] = raw.snapshot_id
                    stats["succeeded"] += 1
                elif outcome.outcome == "not_modified" and entry and have_file:
                    entry["fetched_at"] = stamp
                    row["snapshot_id"] = entry["snapshot_id"]
                    stats["not_modified"] += 1
                else:
                    kind = "blocked" if outcome.outcome == "blocked" else "failed"
                    stats[kind] += 1
                    stats["failures"].append({"url": url, "reason": outcome.reason})
                    index.failures[canon] = {"reason": outcome.reason, "at": stamp, "run_id": run_id}
                    if manifest:
                        manifest.failure(f"{source.source_id}:{url}", str(outcome.reason))
                    append_audit(audit_path, row)
                    index.save()
                    continue
                append_audit(audit_path, row)
                index.save()

            assert entry is not None
            view = snapshot_view(
                entry, source, store, key=f"{source.source_id}:{len(result.snapshots[source.source_id])}"
            )
            result.snapshots[source.source_id].append(view)
            if adapter and depth < max_depth:
                doc = extract(store.read_raw(entry["raw_path"]), entry["media_type"], entry["final_url"])
                for link in adapter.select_links(doc, entry["final_url"], source, depth):
                    queue.append((link, depth + 1))
        if manifest:
            manifest.source_status(
                source.source_id,
                **{k: v for k, v in stats.items() if k != "failures"},
                access_status=source.access_status,
            )
            manifest.save()
    return result
