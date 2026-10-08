"""Strict, transactional, idempotent import of validated records into a repository."""

from __future__ import annotations

from collections.abc import Sequence
from contextlib import AbstractContextManager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from navigator.ingestion.fsutil import write_jsonl
from navigator.ingestion.planner import ImportPlan, PlanItem, plan_import
from navigator.ingestion.validation import FileValidation


class Repository(Protocol):
    """Persistence port. ``SqlRepository`` is the production adapter."""

    def load_existing(self, ids: Sequence[str]) -> dict[str, tuple[dict, int]]: ...

    def transaction(self) -> AbstractContextManager[Any]: ...

    def apply_item(self, item: PlanItem, run_id: str, now_iso: str) -> None: ...

    def record_run(self, run: dict) -> None: ...

    def list_records(self, *, published_only: bool, is_demo: bool, with_meta: bool = False) -> list[dict]: ...


@dataclass
class ImportReport:
    mode: str
    run_id: str
    dry_run: bool
    allow_partial: bool
    status: str  # ok | rejected | partial | failed
    counts: dict[str, int]
    items: list[dict] = field(default_factory=list)
    validation: dict = field(default_factory=dict)
    error: str | None = None

    @property
    def exit_code(self) -> int:
        return 0 if self.status == "ok" else 1

    def to_dict(self) -> dict:
        return {"mode": self.mode, "run_id": self.run_id, "dry_run": self.dry_run,
                "allow_partial": self.allow_partial, "status": self.status, "counts": self.counts,
                "exit_code": self.exit_code, "validation": self.validation, "error": self.error,
                "items": self.items}


def write_quarantine(root: Path, run_id: str, validation: FileValidation, *, subdir: str = "quarantine") -> Path | None:
    """One JSONL row per error finding: line, id (if parsable), field, error type, summary, run id.

    Rows hold candidate-record excerpts only (public source data); student profiles never reach here.
    """
    rows = []
    for result in validation.results:
        for issue in result.issues:
            if issue.is_error:
                rows.append({"run_id": run_id, "line_no": result.line_no, "opportunity_id": result.record_id,
                             "field": issue.path, "error_type": issue.code, "summary": issue.message,
                             "excerpt": result.excerpt})
    for issue in validation.file_issues:
        if issue.is_error:
            rows.append({"run_id": run_id, "line_no": None, "opportunity_id": None, "field": issue.path,
                         "error_type": issue.code, "summary": issue.message, "excerpt": ""})
    if not rows:
        return None
    path = root / subdir / f"{run_id}.jsonl"
    write_jsonl(path, rows)
    return path


def import_records(
    repo: Repository,
    validation: FileValidation,
    *,
    mode: str,
    run_id: str,
    now_iso: str,
    dry_run: bool = False,
    allow_partial: bool = False,
) -> ImportReport:
    """Validate-then-write. Default is all-or-nothing; ``allow_partial`` commits per record.

    ``dry_run`` performs the real planning (evidence is already checked by the validator,
    conflicts and diffs are computed) but writes nothing.
    """
    records = validation.valid_records()
    invalid = validation.invalid_count + (1 if any(i.is_error for i in validation.file_issues) else 0)
    base = {"mode": mode, "run_id": run_id, "dry_run": dry_run, "allow_partial": allow_partial,
            "validation": validation.summary()}
    empty = {"created": 0, "updated": 0, "unchanged": 0, "rejected": 0, "pending_review": 0}

    if invalid and not allow_partial:
        return ImportReport(status="rejected", counts={**empty, "rejected": invalid},
                            error="validation failed; nothing was written", **base)

    existing = repo.load_existing([r["id"] for r in records])
    plan: ImportPlan = plan_import(records, existing, expected_mode=mode)
    counts = plan.counts()
    counts["rejected"] += invalid
    items = [i.summary() for i in plan.items]

    if plan.has_rejections and not allow_partial:
        return ImportReport(status="rejected", counts=counts, items=items,
                            error="the plan contains rejected records; nothing was written", **base)
    if dry_run:
        status = "ok" if counts["rejected"] == 0 else "partial"
        return ImportReport(status=status, counts=counts, items=items, **base)

    writable = plan.writable()
    if not allow_partial:
        try:
            with repo.transaction():
                for item in writable:
                    repo.apply_item(item, run_id, now_iso)
        except Exception as exc:  # noqa: BLE001 - any failure must roll everything back
            return ImportReport(status="failed", counts={**empty, "rejected": len(records)}, items=items,
                                error=f"{type(exc).__name__}: {exc}; transaction rolled back", **base)
    else:
        for item in writable:
            try:
                with repo.transaction():
                    repo.apply_item(item, run_id, now_iso)
            except Exception as exc:  # noqa: BLE001
                counts[item.action if item.action in counts else "created"] -= 1
                counts["rejected"] += 1
                item.action = "rejected"
                item.reasons = [f"db_error: {type(exc).__name__}: {exc}"]
        items = [i.summary() for i in plan.items]
    status = "ok" if counts["rejected"] == 0 else "partial"
    repo.record_run({"run_id": run_id, "kind": "import", "mode": mode, "status": status, "counts": counts,
                     "finished_at": now_iso})
    return ImportReport(status=status, counts=counts, items=items, **base)


def export_public(repo: Repository, path: Path, *, mode: str) -> dict:
    """Write the canonical JSONL export of publishable records of ``mode`` (demo never mixes with live)."""
    records = sorted(repo.list_records(published_only=True, is_demo=(mode == "demo")), key=lambda r: r["id"])
    count = write_jsonl(path, records)
    return {"path": path.as_posix(), "records": count, "empty": count == 0, "data_mode": mode}
