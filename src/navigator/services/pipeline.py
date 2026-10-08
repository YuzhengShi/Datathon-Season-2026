"""Pipeline stages shared by demo and live runs: verify -> candidates -> validate -> import -> export -> report."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from navigator.config import Runtime
from navigator.core.issues import has_errors
from navigator.core.timeutil import format_utc
from navigator.demo.dataset import DEMO_SOURCES, build_demo_artifacts, build_demo_records
from navigator.ingestion.fsutil import write_json, write_jsonl
from navigator.ingestion.importer import Repository, export_public, import_records, write_quarantine
from navigator.ingestion.manifest import RunManifest
from navigator.ingestion.validation import (
    FileValidation,
    ValidationContext,
    validate_jsonl,
    validate_record,
)
from navigator.reports.freshness import build_freshness_report, render_markdown

EXIT_OK, EXIT_DATA, EXIT_CONFIG, EXIT_EXTERNAL = 0, 1, 2, 3


def make_run_id(kind: str, moment: datetime) -> str:
    return f"{kind}-{moment.strftime('%Y%m%dT%H%M%SZ')}"


def write_rejected_quarantine(root: Path, run_id: str, rejected: list[tuple[dict, list]]) -> Path | None:
    """Quarantine rows for candidates that failed verification before they reached a file."""
    rows = [
        {
            "run_id": run_id,
            "line_no": None,
            "opportunity_id": record.get("id"),
            "field": issue.path,
            "error_type": issue.code,
            "summary": issue.message,
            "excerpt": "",
        }
        for record, issues in rejected
        for issue in issues
        if issue.is_error
    ]
    if not rows:
        return None
    path = root / "quarantine" / f"{run_id}.jsonl"
    write_jsonl(path, rows)
    return path


@dataclass
class VerifyOutcome:
    verified: list[dict] = field(default_factory=list)
    rejected: list[tuple[dict, list]] = field(default_factory=list)


def verify_records(records: list[dict], ctx: ValidationContext, verified_at: datetime) -> VerifyOutcome:
    """Run the full validator per record; stamp ``last_verified_at`` only on records that pass.

    A successful fetch or file import never stamps this field: only passing validation does.
    """
    out = VerifyOutcome()
    for record in records:
        issues = validate_record(record, ctx)
        if has_errors(issues):
            out.rejected.append((record, issues))
            continue
        stamped = dict(record)
        if record["review_status"] in {"machine_checked", "human_reviewed"}:
            stamped["last_verified_at"] = format_utc(verified_at)
        out.verified.append(stamped)
    return out


def validate_file(
    path: Path,
    rt: Runtime,
    *,
    now: datetime | None,
    verify_files: bool = True,
    known_source_ids: frozenset[str] | None = None,
) -> FileValidation:
    ctx = ValidationContext(
        artifact_root=rt.artifact_root,
        expected_mode=rt.mode,
        now=now,
        verify_files=verify_files,
        known_source_ids=known_source_ids,
    )
    return validate_jsonl(path, ctx)


def write_reports(
    repo: Repository,
    rt: Runtime,
    *,
    as_of: datetime,
    now: datetime,
    run_context: dict[str, Any],
    parameters: dict[str, Any],
) -> dict:
    records = repo.list_records(published_only=False, is_demo=(rt.mode == "demo"), with_meta=True)
    report = build_freshness_report(
        records,
        mode=rt.mode,
        as_of=as_of,
        generated_at=now,
        freshness_days=rt.freshness_days,
        run_context=run_context,
        parameters=parameters,
    )
    write_json(rt.artifact_root / "reports" / "freshness.json", report)
    (rt.artifact_root / "reports" / "freshness.md").write_text(render_markdown(report), encoding="utf-8")
    return report


def import_and_publish(
    repo: Repository,
    rt: Runtime,
    *,
    candidates: Path,
    run_id: str,
    as_of: datetime,
    manifest: RunManifest,
    run_context: dict,
    dry_run: bool = False,
    allow_partial: bool = False,
    known_source_ids: frozenset[str] | None = None,
    write_empty_export: bool = True,
) -> dict:
    """Validate the candidates file, import, export and report. Returns a result summary."""
    validation = validate_file(candidates, rt, now=as_of, known_source_ids=known_source_ids)
    write_json(rt.artifact_root / "reports" / "validation.json", validation.summary())
    quarantine = write_quarantine(rt.artifact_root, run_id, validation)
    manifest.step_done("validate", **{k: validation.summary()[k] for k in ("records", "valid", "invalid")})
    if quarantine is not None:
        manifest.artifact("quarantine", quarantine, rt.artifact_root)
        manifest.failure("validation", f"{validation.invalid_count} record(s) quarantined")
    run_context["quarantined"] = validation.invalid_count
    run_context["evidence_failures"] = sum(
        1 for r in validation.results for i in r.issues if i.is_error and i.code.startswith("evidence.")
    )

    report = import_records(
        repo,
        validation,
        mode=rt.mode,
        run_id=run_id,
        now_iso=format_utc(as_of),
        dry_run=dry_run,
        allow_partial=allow_partial,
        superseding=_superseded_ids(rt),
    )
    write_json(rt.artifact_root / "reports" / ("import-dry-run.json" if dry_run else "import.json"), report.to_dict())
    manifest.step_done("import", status=report.status, **report.counts)
    manifest.count(**{f"import_{k}": v for k, v in report.counts.items()})
    run_context["import"] = report.counts
    result: dict[str, Any] = {"import": report.to_dict(), "exit_code": report.exit_code}
    if dry_run or report.status in {"rejected", "failed"}:
        return result

    public = repo.list_records(published_only=True, is_demo=(rt.mode == "demo"))
    if (
        not public and not write_empty_export
    ):  # no real data: do not create a canonical file that suggests there is some
        result["export"] = {"path": None, "records": 0, "empty": True, "written": False, "data_mode": rt.mode}
        manifest.step_done("export", records=0, written=False)
        return result
    export = export_public(repo, rt.artifact_root / "awards.jsonl", mode=rt.mode)
    manifest.step_done("export", records=export["records"])
    manifest.artifact("export", rt.artifact_root / "awards.jsonl", rt.artifact_root)
    result["export"] = export
    return result


def run_demo_pipeline(repo: Repository, rt: Runtime, *, as_of: datetime, dry_run: bool = False) -> dict:
    """Synthetic snapshots -> candidates -> validation -> import -> export -> reports (no network/LLM)."""
    if rt.mode != "demo":
        raise ValueError("run_demo_pipeline requires a demo runtime")
    root = rt.artifact_root
    run_id = make_run_id("demo-pipeline", as_of)
    manifest = RunManifest(
        root / "runs" / f"{run_id}.json",
        run_id,
        "pipeline",
        "demo",
        {"as_of": format_utc(as_of), "dry_run": dry_run},
        as_of,
    )

    art = build_demo_artifacts(root, as_of)
    manifest.step_done("synthetic_snapshots", snapshots=len(art.snaps))
    for key, snap in art.snaps.items():
        manifest.source_status(
            snap.source_id,
            status="ok" if art.extraction_status[key] == "ok" else art.extraction_status[key],
            snapshot_id=snap.snapshot_id,
            synthetic=True,
        )
    ocr = [art.snaps[k].url for k, st in art.extraction_status.items() if st == "ocr_required"]
    for url in ocr:
        manifest.pending(url, "scanned PDF has no text layer: ocr_required (OCR is not performed)")

    records = build_demo_records(art)
    ctx = ValidationContext(artifact_root=root, expected_mode="demo", now=as_of)
    outcome = verify_records(records, ctx, as_of)
    candidates = root / "candidates" / "awards.jsonl"
    write_jsonl(candidates, sorted(outcome.verified, key=lambda r: r["id"]))
    manifest.step_done("candidates", records=len(outcome.verified), rejected=len(outcome.rejected))
    manifest.artifact("candidates", candidates, root)
    if outcome.rejected:  # the synthetic dataset must be fully valid: anything else is a defect, not a data gap
        quarantine = write_rejected_quarantine(root, run_id, outcome.rejected)
        if quarantine is not None:
            manifest.artifact("quarantine", quarantine, root)
        manifest.failure("verification", f"{len(outcome.rejected)} candidate(s) failed validation")
        manifest.finish("failed", as_of)
        return {
            "run_id": run_id,
            "data_mode": "demo",
            "exit_code": EXIT_DATA,
            "artifact_root": root.as_posix(),
            "error": f"{len(outcome.rejected)} candidate(s) failed validation; nothing was imported",
            "rejected_ids": [r.get("id") for r, _ in outcome.rejected],
        }

    if not dry_run:
        repo.ensure_sources(DEMO_SOURCES)  # type: ignore[attr-defined]
    sources_total = len(art.snaps)
    run_context: dict[str, Any] = {
        "sources": {
            "attempted": sources_total,
            "succeeded": sources_total - len(ocr),
            "failed": 0,
            "skipped": 0,
            "details": [{"source_id": s.source_id, "status": art.extraction_status[k]} for k, s in art.snaps.items()],
        },
        "discovery": {
            "entries_observed": None,
            "coverage": None,
            "pagination_complete": None,
            "note": "demo run: no discovery index crawl",
        },
        "failures": [],
        "pending_verification": manifest.data["pending_verification"],
        "ocr_required": ocr,
    }
    result = import_and_publish(
        repo,
        rt,
        candidates=candidates,
        run_id=run_id,
        as_of=as_of,
        manifest=manifest,
        run_context=run_context,
        dry_run=dry_run,
        known_source_ids=frozenset(s["source_id"] for s in DEMO_SOURCES),
    )
    if not dry_run and result["exit_code"] == 0:
        report = write_reports(repo, rt, as_of=as_of, now=as_of, run_context=run_context, parameters={"run_id": run_id})
        manifest.step_done("report", records=report["opportunities"]["total"])
        manifest.artifact("freshness_json", root / "reports" / "freshness.json", root)
        manifest.artifact("freshness_md", root / "reports" / "freshness.md", root)
        result["report"] = report["opportunities"]
        repo.record_run(
            {
                "run_id": run_id,
                "kind": "pipeline",
                "mode": rt.mode,
                "status": "ok",
                "context": run_context,
                "finished_at": format_utc(as_of),
            }
        )
    manifest.finish("ok" if result["exit_code"] == 0 else "failed", as_of)
    result.update({"run_id": run_id, "data_mode": "demo", "artifact_root": root.as_posix()})
    return result


def _superseded_ids(rt: Runtime) -> frozenset[str]:
    """Ids this run replaced by a provider-page record (written by the extract step; empty when nothing was replaced)."""
    import json

    path = rt.artifact_root / "discovery" / "superseded_directory_records.json"
    if rt.mode != "live" or not path.is_file():
        return frozenset()
    try:
        return frozenset(item["id"] for item in json.loads(path.read_text(encoding="utf-8")))
    except (OSError, ValueError, KeyError, TypeError):
        return frozenset()
