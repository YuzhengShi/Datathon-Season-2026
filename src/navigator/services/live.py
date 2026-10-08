"""Live pipeline: bounded fetch -> source adapters -> verification -> import -> reports.

Nothing here invents data. Whatever the network or a page refuses to give stays in the manifest
as a failure or a pending item, the exit code says so, and demo records can never fill a gap.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

from navigator.config import Runtime
from navigator.ingestion.adapters import registry
from navigator.ingestion.adapters.base import ParseContext
from navigator.ingestion.builder import SnapshotView
from navigator.ingestion.fetch_stage import FetchIndex, FetchStageResult, run_fetch_stage, snapshot_view
from navigator.ingestion.fetcher import Fetcher, FetchPolicy
from navigator.ingestion.extractors import select_adapters
from navigator.ingestion.fsutil import write_json, write_jsonl
from navigator.ingestion.manifest import RunManifest
from navigator.ingestion.snapshots import SnapshotStore
from navigator.ingestion.sources import SourceConfig, load_sources
from navigator.ingestion.validation import ValidationContext
from navigator.services.pipeline import (
    EXIT_DATA,
    EXIT_EXTERNAL,
    EXIT_OK,
    import_and_publish,
    make_run_id,
    verify_records,
    write_rejected_quarantine,
    write_reports,
)

TARGET_MIN = 20


def build_fetcher(rt: Runtime, transport: Any = None) -> Fetcher:
    """Real HTTP by default; tests inject a scripted transport (no DNS check in that case)."""
    policy = FetchPolicy(user_agent=rt.user_agent, timeout=rt.fetch_timeout, max_bytes=rt.fetch_max_bytes,
                         retries=rt.fetch_retries, min_interval=rt.fetch_min_interval)
    if transport is not None:
        return Fetcher(transport, policy)
    from navigator.ingestion.http_transport import HttpxTransport, system_resolver

    return Fetcher(HttpxTransport(), policy, resolver=system_resolver)


def load_curated(data_dir: Path) -> dict[str, dict]:
    """``data/curated/*.yaml|json``: evidence-quoted mappings keyed by ``source_id``."""
    out: dict[str, dict] = {}
    folder = data_dir / "curated"
    for path in sorted(folder.glob("*")) if folder.is_dir() else []:
        if path.suffix in {".yaml", ".yml", ".json"}:
            spec = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            if isinstance(spec, dict) and spec.get("source_id"):
                out[spec["source_id"]] = spec
    return out


@dataclass
class ParsedOutput:
    candidates: list[dict] = field(default_factory=list)
    pending: list[dict] = field(default_factory=list)
    discovery_stats: dict[str, dict] = field(default_factory=dict)


def snapshots_from_index(index: FetchIndex, store: SnapshotStore, sources: list[SourceConfig]) -> dict[str, list[SnapshotView]]:
    """Rebuild snapshot views from the fetch index (no network): start page first, then by URL."""
    out: dict[str, list[SnapshotView]] = {}
    for source in sources:
        entries = sorted((e for e in index.entries.values() if e["source_id"] == source.source_id and e.get("status") == "ok"),
                         key=lambda e: (e.get("depth", 0), e["final_url"]))
        out[source.source_id] = [snapshot_view(e, source, store, key=f"{source.source_id}:{i}") for i, e in enumerate(entries)]
    return out


def stage_parse(rt: Runtime, sources: list[SourceConfig], snapshots: dict[str, list[SnapshotView]], store: SnapshotStore,
                now: datetime, manifest: RunManifest | None = None) -> ParsedOutput:
    adapters = select_adapters(rt.extraction_mode, registry())
    curated = load_curated(rt.data_dir)
    ctx = ParseContext(now=now, curated=curated, read_raw=lambda snap: store.read_raw(snap.raw_path))
    out = ParsedOutput()
    discovery_dir = rt.artifact_root / "discovery"
    for source in sources:
        adapter, snaps = adapters.get(source.parser), snapshots.get(source.source_id, [])
        if adapter is None:
            out.pending.append({"item": source.source_id, "reason": f"no adapter {source.parser!r} available in "
                                f"extraction mode {rt.extraction_mode!r}"})
            continue
        if not snaps:
            out.pending.append({"item": source.source_id, "reason": "no snapshot available (not fetched, or every fetch failed)"})
            continue
        result = adapter.parse(snaps, source, ctx)
        out.candidates.extend(result.candidates)
        out.pending.extend({"item": p["item"], "reason": p["reason"], "source_id": source.source_id} for p in result.pending)
        if result.discovery:
            write_jsonl(discovery_dir / f"{source.source_id}.jsonl", result.discovery)
        if result.stats:
            write_json(discovery_dir / f"{source.source_id}.summary.json", {**result.stats, "adapter": adapter.name,
                                                                         "adapter_version": adapter.version})
            out.discovery_stats[source.source_id] = result.stats
        if manifest:
            manifest.source_status(source.source_id, parsed_records=len(result.candidates), discovery_entries=len(result.discovery))
    for item in out.pending:
        if manifest:
            manifest.pending(str(item["item"]), item["reason"])
    return out


def _source_summary(sources: list[SourceConfig], fetched: FetchStageResult | None, index: FetchIndex,
                    skipped: list[SourceConfig]) -> dict:
    details, ok, failed = [], 0, 0
    for s in sources:
        has_ok = any(e["source_id"] == s.source_id and e.get("status") == "ok" for e in index.entries.values())
        stats = (fetched.per_source.get(s.source_id) if fetched else None) or {}
        state = "ok" if has_ok else ("failed" if stats.get("failed") or stats.get("blocked") or index.failures else "no_data")
        ok += state == "ok"
        failed += state != "ok"
        details.append({"source_id": s.source_id, "status": state, "access_status": s.access_status,
                        **{k: stats.get(k, 0) for k in ("attempted", "succeeded", "failed", "blocked", "skipped", "not_modified")}})
    return {"attempted": len(sources), "succeeded": ok, "failed": failed, "skipped": len(skipped), "details": details}


def run_fetch_only(rt: Runtime, *, now: datetime, max_pages: int, resume: bool, refresh: bool,
                   fetcher: Fetcher | None = None, only: set[str] | None = None) -> dict:
    """``fetch`` command: snapshots + index + audit trail, nothing parsed or imported."""
    select_adapters(rt.extraction_mode, {})
    root = rt.artifact_root
    sources = [s for s in load_sources(rt.sources_config) if not only or s.source_id in only]
    active = [s for s in sources if s.access_status != "restricted"]
    run_id = make_run_id("fetch", now)
    manifest = RunManifest(root / "runs" / f"{run_id}.json", run_id, "fetch", rt.mode,
                           {"max_pages": max_pages, "resume": resume, "refresh": refresh}, now)
    store, index = SnapshotStore(root), FetchIndex(root / "discovery" / "fetch_index.json")
    fetched = run_fetch_stage(active, fetcher or build_fetcher(rt), store, index, registry(), run_id=run_id, now=now,
                              audit_path=root / "discovery" / "fetch_audit.jsonl", max_pages=max_pages,
                              resume=resume, refresh=refresh, manifest=manifest)
    for url in fetched.unvisited:
        manifest.pending(url, "not fetched: page budget reached")
    summary = _source_summary(active, fetched, index, [s for s in sources if s not in active])
    manifest.step_done("fetch", pages=fetched.pages_fetched)
    bad = summary["failed"] > 0 or bool(fetched.unvisited)
    manifest.finish("partial" if bad else "ok", now)
    return {"run_id": run_id, "data_mode": rt.mode, "sources": summary, "pages_fetched": fetched.pages_fetched,
            "unvisited": len(fetched.unvisited), "robots": fetched.robots,
            "exit_code": EXIT_EXTERNAL if bad or summary["succeeded"] == 0 else EXIT_OK}


def run_extract_only(rt: Runtime, *, now: datetime, limit: int | None = None) -> dict:
    """``extract`` command: run adapters over stored snapshots (no network), verify, write candidates."""
    select_adapters(rt.extraction_mode, {})
    root = rt.artifact_root
    sources = load_sources(rt.sources_config)
    store, index = SnapshotStore(root), FetchIndex(root / "discovery" / "fetch_index.json")
    if not index.entries:
        return {"data_mode": rt.mode, "exit_code": EXIT_EXTERNAL, "error": "no fetched snapshots: run `fetch` first"}
    run_id = make_run_id("extract", now)
    manifest = RunManifest(root / "runs" / f"{run_id}.json", run_id, "extract", rt.mode, {"limit": limit}, now)
    parsed = stage_parse(rt, sources, snapshots_from_index(index, store, sources), store, now, manifest)
    ctx = ValidationContext(artifact_root=root, expected_mode=rt.mode, now=now,
                            known_source_ids=frozenset(s.source_id for s in sources))
    outcome = verify_records(parsed.candidates, ctx, now)
    verified = sorted(outcome.verified, key=lambda r: r["id"])[: limit or None]
    write_jsonl(root / "candidates" / "awards.jsonl", verified)
    if outcome.rejected:
        write_rejected_quarantine(root, run_id, outcome.rejected)
        manifest.failure("verification", f"{len(outcome.rejected)} candidate(s) failed validation")
    manifest.step_done("extract", candidates=len(verified), rejected=len(outcome.rejected), pending=len(parsed.pending))
    manifest.finish("failed" if outcome.rejected else "ok", now)
    return {"run_id": run_id, "data_mode": rt.mode, "candidates": len(verified), "rejected": len(outcome.rejected),
            "pending": len(parsed.pending), "exit_code": EXIT_DATA if outcome.rejected else EXIT_OK}


def run_live_pipeline(repo: Any, rt: Runtime, *, now: datetime, limit: int, max_pages: int, resume: bool,
                      refresh: bool, dry_run: bool = False, allow_partial: bool = False,
                      fetcher: Fetcher | None = None) -> dict:
    if rt.mode != "live":
        raise ValueError("run_live_pipeline requires a live runtime")
    select_adapters(rt.extraction_mode, {})  # raises ExtractorUnavailable for llm before anything is fetched
    root = rt.artifact_root
    root.mkdir(parents=True, exist_ok=True)
    all_sources = load_sources(rt.sources_config)
    sources = [s for s in all_sources if s.access_status != "restricted"]
    skipped = [s for s in all_sources if s.access_status == "restricted"]
    run_id = make_run_id("live-pipeline", now)
    manifest = RunManifest(root / "runs" / f"{run_id}.json", run_id, "pipeline", "live",
                           {"limit": limit, "max_pages": max_pages, "resume": resume, "refresh": refresh,
                            "dry_run": dry_run, "allow_partial": allow_partial}, now)
    for s in skipped:
        manifest.pending(s.source_id, "terms marked restricted: not fetched")
    for s in sources:
        if s.access_status == "unreviewed":
            manifest.note(f"{s.source_id}: site terms NOT reviewed by a person; robots.txt is checked at fetch time but "
                          "robots allowing a path does not mean the terms allow reuse")

    store, index = SnapshotStore(root), FetchIndex(root / "discovery" / "fetch_index.json")
    fetched = run_fetch_stage(sources, fetcher or build_fetcher(rt), store, index, registry(), run_id=run_id, now=now,
                              audit_path=root / "discovery" / "fetch_audit.jsonl", max_pages=max_pages,
                              resume=resume, refresh=refresh, manifest=manifest)
    for url in fetched.unvisited:
        manifest.pending(url, "not fetched: page budget reached")
    manifest.step_done("fetch", pages=fetched.pages_fetched, unvisited=len(fetched.unvisited))

    parsed = stage_parse(rt, sources, snapshots_from_index(index, store, sources), store, now, manifest)
    manifest.step_done("parse", candidates=len(parsed.candidates), pending=len(parsed.pending))

    ctx = ValidationContext(artifact_root=root, expected_mode="live", now=now,
                            known_source_ids=frozenset(s.source_id for s in sources))
    outcome = verify_records(parsed.candidates, ctx, now)
    if outcome.rejected:
        quarantine = write_rejected_quarantine(root, run_id, outcome.rejected)
        if quarantine is not None:
            manifest.artifact("quarantine", quarantine, root)
        manifest.failure("verification", f"{len(outcome.rejected)} candidate(s) failed validation")
    verified = sorted(outcome.verified, key=lambda r: r["id"])[:limit]
    candidates = root / "candidates" / "awards.jsonl"
    write_jsonl(candidates, verified)
    manifest.step_done("candidates", records=len(verified), rejected=len(outcome.rejected))
    manifest.artifact("candidates", candidates, root)

    summary = _source_summary(sources, fetched, index, skipped)
    isc = parsed.discovery_stats.get("isc_bursaries_index", {})
    run_context: dict[str, Any] = {
        "sources": summary,
        "discovery": {"entries_observed": isc.get("entries_observed"), "declared_count": isc.get("declared_count"),
                      "coverage": isc.get("coverage"), "pagination_complete": isc.get("pagination_complete"),
                      "note": "discovery entries are NOT verified awards"},
        "failures": manifest.data["failures"], "pending_verification": manifest.data["pending_verification"],
        "ocr_required": [e["final_url"] for e in index.entries.values() if e.get("extraction_status") == "ocr_required"],
    }

    if not dry_run:
        repo.ensure_sources([s.to_row() for s in all_sources])
        ok_entries = [e for e in index.entries.values() if e.get("status") == "ok"]
        if hasattr(repo, "ensure_snapshot_rows"):
            repo.ensure_snapshot_rows(ok_entries)
        audit = root / "discovery" / "fetch_audit.jsonl"
        rows = [json.loads(line) for line in audit.read_text(encoding="utf-8").splitlines()] if audit.is_file() else []
        if hasattr(repo, "record_fetches"):
            repo.record_fetches([r for r in rows if r.get("run_id") == run_id], run_id=run_id, mode="live")

    result = import_and_publish(repo, rt, candidates=candidates, run_id=run_id, as_of=now, manifest=manifest,
                                run_context=run_context, dry_run=dry_run, allow_partial=allow_partial,
                                known_source_ids=frozenset(s.source_id for s in sources), write_empty_export=False)
    real = [r for r in repo.list_records(published_only=True, is_demo=False) if r["opportunity_type"] != "award_collection"]
    real_count = len(real) if not dry_run else sum(1 for r in verified if r["publication_status"] == "published")
    if not dry_run and result["exit_code"] == 0:
        write_reports(repo, rt, as_of=now, now=now, run_context=run_context,
                      parameters={"run_id": run_id, "limit": limit, "max_pages": max_pages})
        repo.record_run({"run_id": run_id, "kind": "pipeline", "mode": "live", "status": "ok", "context": run_context,
                         "finished_at": now.strftime("%Y-%m-%dT%H:%M:%SZ")})
        manifest.step_done("report", records=len(real))

    external = summary["failed"] > 0 or bool(fetched.unvisited) or real_count < TARGET_MIN
    if outcome.rejected or result["exit_code"] != 0:
        code, status = EXIT_DATA, "failed"
    elif external:
        code, status = EXIT_EXTERNAL, "partial"
    else:
        code, status = EXIT_OK, "ok"
    manifest.count(real_opportunities=real_count, target_minimum=TARGET_MIN, shortfall=max(0, TARGET_MIN - real_count))
    manifest.finish(status, now)
    result.update({"run_id": run_id, "data_mode": "live", "status": status, "exit_code": code, "sources": summary,
                   "real_opportunities": real_count,
                   "target": {"minimum": TARGET_MIN, "shortfall": max(0, TARGET_MIN - real_count)},
                   "rejected_candidates": len(outcome.rejected), "pending_items": len(parsed.pending),
                   "artifact_root": root.as_posix()})
    return result
