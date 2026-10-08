"""Command line: ``python -m navigator.cli <command>``.

Exit codes: 0 success; 1 data / validation / test failure; 2 bad arguments or configuration;
3 an external source was unavailable or the live run did not reach its target (a *partial* run).
Finding items that still need verification is normal and not an error; see README "Exit codes".

NOTE: this module intentionally has no ``from __future__ import annotations`` so Typer can read the
real annotation objects.
"""

import dataclasses
import json
import re
from enum import Enum
from pathlib import Path
from typing import NoReturn, Optional

import typer

from navigator import __version__
from navigator.config import ConfigError, Runtime, load_runtime
from navigator.core.timeutil import format_utc, parse_as_of
from navigator.db import make_engine, make_session_factory, migration_state, upgrade_database
from navigator.demo.dataset import DEMO_SOURCES
from navigator.ingestion.extractors import ExtractorUnavailable
from navigator.ingestion.fsutil import write_json
from navigator.ingestion.importer import export_public, import_records, write_quarantine
from navigator.ingestion.sources import SourceConfigError, load_sources
from navigator.ingestion.validation import ValidationContext, validate_jsonl
from navigator.models.repository import SqlRepository
from navigator.services import live as live_service
from navigator.services.pipeline import (
    EXIT_CONFIG,
    EXIT_DATA,
    make_run_id,
    run_demo_pipeline,
    write_reports,
)

app = typer.Typer(name="navigator", help="Indigenous Student Funding Navigator - data pipeline and API.",
                  no_args_is_help=True, add_completion=False, pretty_exceptions_enable=False)
db_app = typer.Typer(help="Database commands.", no_args_is_help=True)
app.add_typer(db_app, name="db")


class Mode(str, Enum):
    live = "live"
    demo = "demo"


MODE_HELP = "live or demo. An explicit --mode beats DATA_MODE; demo uses its own database and artifact folder."


def _fail(message: str, code: int = EXIT_CONFIG) -> NoReturn:
    typer.echo(message, err=True)
    raise typer.Exit(code)


def _safe(exc: BaseException) -> str:
    """One-line error text with credentials masked (connection strings can contain passwords)."""
    line = (str(exc).splitlines() or [""])[0]
    masked = re.sub(r"://[^@/\s]+@", "://***@", line)
    return f"{type(exc).__name__}: {masked}"


def _runtime(mode: Optional[Mode]) -> Runtime:
    try:
        return load_runtime(mode.value if mode else None)
    except ConfigError as exc:
        _fail(f"configuration error: {exc}")


def _clock(as_of: Optional[str]):
    try:
        return parse_as_of(as_of)
    except (ValueError, TypeError):
        _fail("--as-of must be an ISO date (e.g. 2026-10-07) or datetime")


def _emit(payload: dict) -> None:
    typer.echo(json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False, default=str))


def _repo(rt: Runtime, *, require_migrated: bool = True) -> SqlRepository:
    engine = make_engine(rt.database_url)
    if require_migrated and not migration_state(engine)["up_to_date"]:
        _fail(f"the {rt.mode} database is not migrated: run `python -m navigator.cli db upgrade --mode {rt.mode}`")
    return SqlRepository(make_session_factory(engine))


def _source_rows(rt: Runtime) -> list[dict]:
    if rt.mode == "demo":
        return list(DEMO_SOURCES)
    try:
        return [s.to_row() for s in load_sources(rt.sources_config)]
    except SourceConfigError as exc:
        _fail(f"source configuration error: {exc}")


@db_app.command("upgrade")
def db_upgrade(mode: Optional[Mode] = typer.Option(None, "--mode", help=MODE_HELP),
               revision: str = typer.Option("head", "--revision", help="Alembic target revision.")) -> None:
    """Create/upgrade the schema with Alembic migrations (never create_all)."""
    rt = _runtime(mode)
    try:
        upgrade_database(rt.database_url, revision)
    except Exception as exc:  # noqa: BLE001 - report, with credentials masked
        _fail(f"migration failed: {_safe(exc)}", EXIT_DATA)
    state = migration_state(make_engine(rt.database_url))
    _emit({"data_mode": rt.mode, "migrations": state})
    raise typer.Exit(0 if state["up_to_date"] or revision != "head" else EXIT_DATA)


@app.command()
def pipeline(
    mode: Optional[Mode] = typer.Option(None, "--mode", help=MODE_HELP),
    as_of: Optional[str] = typer.Option(None, "--as-of", help="Reproducible reference date/time (default: now)."),
    limit: int = typer.Option(30, "--limit", min=1, help="Live: maximum opportunities to import."),
    max_pages: int = typer.Option(50, "--max-pages", min=1, help="Live: page budget for this run."),
    resume: bool = typer.Option(False, "--resume", help="Live: skip pages that already have a snapshot."),
    refresh: bool = typer.Option(False, "--refresh", help="Live: re-check stored pages with conditional requests."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Plan and validate; write no database rows or exports."),
    allow_partial: bool = typer.Option(False, "--allow-partial", help="Commit valid records even if others are rejected."),
) -> None:
    """Run the whole chain. demo: synthetic and offline. live: official sources (bounded, polite)."""
    rt, now = _runtime(mode), _clock(as_of)
    if not dry_run:
        try:
            upgrade_database(rt.database_url)
        except Exception as exc:  # noqa: BLE001
            _fail(f"migration failed: {_safe(exc)}", EXIT_DATA)
    repo = _repo(rt)
    try:
        if rt.mode == "demo":
            result = run_demo_pipeline(repo, rt, as_of=now, dry_run=dry_run)
        else:
            result = live_service.run_live_pipeline(repo, rt, now=now, limit=limit, max_pages=max_pages, resume=resume,
                                                    refresh=refresh, dry_run=dry_run, allow_partial=allow_partial)
    except SourceConfigError as exc:
        _fail(f"source configuration error: {exc}")
    except ExtractorUnavailable as exc:
        _fail(f"extraction mode unavailable: {exc}")
    _emit({k: v for k, v in result.items() if k != "import"} | {"import_counts": result.get("import", {}).get("counts")})
    raise typer.Exit(result["exit_code"])


@app.command()
def fetch(
    mode: Optional[Mode] = typer.Option(None, "--mode", help=MODE_HELP),
    sources: Optional[Path] = typer.Option(None, "--sources", help="Source configuration (default: SOURCE_CONFIG)."),
    max_pages: int = typer.Option(50, "--max-pages", min=1),
    resume: bool = typer.Option(False, "--resume"),
    refresh: bool = typer.Option(False, "--refresh"),
    as_of: Optional[str] = typer.Option(None, "--as-of"),
) -> None:
    """Download official pages into content-addressed snapshots (live only)."""
    rt = _runtime(mode)
    if rt.mode != "live":
        _fail("fetch runs in live mode only: demo data is synthetic and needs no network")
    if sources is not None:
        rt = dataclasses.replace(rt, sources_config=sources)
    try:
        result = live_service.run_fetch_only(rt, now=_clock(as_of), max_pages=max_pages, resume=resume, refresh=refresh)
    except SourceConfigError as exc:
        _fail(f"source configuration error: {exc}")
    except ExtractorUnavailable as exc:
        _fail(f"extraction mode unavailable: {exc}")
    _emit(result)
    raise typer.Exit(result["exit_code"])


@app.command()
def extract(
    mode: Optional[Mode] = typer.Option(None, "--mode", help=MODE_HELP),
    resume: bool = typer.Option(False, "--resume", help="Accepted for symmetry: extraction always reuses stored snapshots."),
    as_of: Optional[str] = typer.Option(None, "--as-of"),
) -> None:
    """Run the source adapters over stored snapshots and write verified candidates (no network)."""
    rt = _runtime(mode)
    if rt.mode != "live":
        _fail("extract runs in live mode only; use `pipeline --mode demo` for the synthetic data")
    try:
        result = live_service.run_extract_only(rt, now=_clock(as_of))
    except SourceConfigError as exc:
        _fail(f"source configuration error: {exc}")
    except ExtractorUnavailable as exc:
        _fail(f"extraction mode unavailable: {exc}")
    _emit(result)
    raise typer.Exit(result["exit_code"])


@app.command()
def validate(
    input: Path = typer.Option(..., "--input", exists=True, dir_okay=False, help="Candidate/export JSONL file."),
    artifact_root: Path = typer.Option(..., "--artifact-root", file_okay=False, help="Folder holding raw/ and text/ snapshots."),
    mode: Optional[Mode] = typer.Option(None, "--mode", help=MODE_HELP),
    as_of: Optional[str] = typer.Option(None, "--as-of"),
) -> None:
    """Validate a JSONL file: schema, semantics, evidence, hashes. Bad records go to quarantine."""
    rt, now = _runtime(mode), _clock(as_of)
    known = frozenset(r["source_id"] for r in _source_rows(rt))
    report = validate_jsonl(input, ValidationContext(artifact_root=artifact_root, expected_mode=rt.mode, now=now,
                                                     known_source_ids=known))
    run_id = make_run_id("validate", now)
    write_json(artifact_root / "reports" / "validation.json", report.summary())
    quarantine = write_quarantine(artifact_root, run_id, report)
    first = [dict(i.to_dict(), line=r.line_no, id=r.record_id) for r in report.results for i in r.issues][:50]
    _emit({**report.summary(), "quarantine_file": quarantine.name if quarantine else None, "first_findings": first})
    raise typer.Exit(0 if report.ok else EXIT_DATA)


@app.command("import-data")
def import_data(
    input: Path = typer.Option(..., "--input", exists=True, dir_okay=False),
    artifact_root: Path = typer.Option(..., "--artifact-root", file_okay=False),
    mode: Optional[Mode] = typer.Option(None, "--mode", help=MODE_HELP),
    dry_run: bool = typer.Option(False, "--dry-run", help="Real validation, evidence and conflict checks; no writes."),
    allow_partial: bool = typer.Option(False, "--allow-partial", help="Per-record transactions; any rejection still exits 1."),
    as_of: Optional[str] = typer.Option(None, "--as-of"),
) -> None:
    """Strict, transactional, idempotent import. By default one bad record rejects the whole batch."""
    rt, now = _runtime(mode), _clock(as_of)
    repo = _repo(rt)
    rows = _source_rows(rt)
    validation = validate_jsonl(input, ValidationContext(artifact_root=artifact_root, expected_mode=rt.mode, now=now,
                                                         known_source_ids=frozenset(r["source_id"] for r in rows)))
    run_id = make_run_id("import", now)
    write_quarantine(artifact_root, run_id, validation)
    if not dry_run:
        repo.ensure_sources(rows)
    report = import_records(repo, validation, mode=rt.mode, run_id=run_id, now_iso=format_utc(now), dry_run=dry_run,
                            allow_partial=allow_partial)
    write_json(artifact_root / "reports" / ("import-dry-run.json" if dry_run else "import.json"), report.to_dict())
    _emit(report.to_dict())
    raise typer.Exit(report.exit_code)


@app.command()
def export(
    mode: Optional[Mode] = typer.Option(None, "--mode", help=MODE_HELP),
    output: Path = typer.Option(..., "--output", help="JSONL file to (atomically) write."),
) -> None:
    """Canonical JSONL export of published records of this mode (demo never mixes with live)."""
    rt = _runtime(mode)
    _emit(export_public(_repo(rt), output, mode=rt.mode))


@app.command()
def report(
    mode: Optional[Mode] = typer.Option(None, "--mode", help=MODE_HELP),
    as_of: Optional[str] = typer.Option(None, "--as-of"),
) -> None:
    """Write the data-freshness report (JSON + Markdown) for the current dataset."""
    rt, now = _runtime(mode), _clock(as_of)
    repo = _repo(rt)
    data = write_reports(repo, rt, as_of=now, now=parse_as_of(None), run_context=repo.latest_run_context(rt.mode),
                         parameters={"source": "cli"})
    _emit({"data_mode": rt.mode, "json": (rt.artifact_root / "reports" / "freshness.json").as_posix(),
           "markdown": (rt.artifact_root / "reports" / "freshness.md").as_posix(), "opportunities": data["opportunities"]})


@app.command()
def serve(
    mode: Optional[Mode] = typer.Option(None, "--mode", help=MODE_HELP),
    host: str = typer.Option("127.0.0.1", "--host"),
    port: int = typer.Option(8000, "--port", min=1, max=65535),
) -> None:
    """Start the read-only API (OpenAPI docs at /docs)."""
    import uvicorn

    from navigator.api.app import create_app

    rt = _runtime(mode)
    uvicorn.run(create_app(rt), host=host, port=port, log_level=rt.log_level.lower())


@app.command()
def version() -> None:
    """Print the package version."""
    typer.echo(__version__)


if __name__ == "__main__":
    app()
