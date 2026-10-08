"""HTTP routes. Handlers are plain ``def`` (run in FastAPI's thread pool) because the database layer is synchronous."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response

from navigator import __version__
from navigator.config import Runtime
from navigator.core.timeutil import parse_as_of
from navigator.db import migration_state
from navigator.matching.engine import MatchOptions, match_records
from navigator.models.repository import SqlRepository
from navigator.reports.freshness import build_freshness_report
from navigator.schemas.api import (
    ErrorResponse,
    HealthResponse,
    MatchResponse,
    OpportunityDetail,
    OpportunityList,
)
from navigator.schemas.profile import MatchRequest
from navigator.schemas.types import EducationLevel, OpportunityType, Province
from navigator.services.query import list_opportunities, opportunity_detail

router = APIRouter()
_ERRORS: dict[int | str, dict[str, Any]] = {404: {"model": ErrorResponse}, 422: {"model": ErrorResponse}}


def get_runtime(request: Request) -> Runtime:
    return request.app.state.runtime


def get_repo(request: Request) -> SqlRepository:
    """A fresh repository per request: it carries per-call transaction state."""
    return SqlRepository(request.app.state.session_factory)


def reference_time(value: str | None):
    try:
        return parse_as_of(value)
    except (ValueError, TypeError):
        raise HTTPException(status_code=422, detail="as_of must be an ISO date or datetime") from None


@router.get("/health", response_model=HealthResponse, tags=["system"], summary="Service, database and migration status")
def health(request: Request, response: Response, rt: Runtime = Depends(get_runtime)) -> dict:
    state = migration_state(request.app.state.engine)
    if not state["connected"]:
        response.status_code = 503
    return {
        "status": "ok" if state["connected"] and state["up_to_date"] else "degraded",
        "data_mode": rt.mode, "version": __version__, "database": {"connected": state["connected"]},
        "migrations": {"current": state["current"], "expected": state["expected"], "up_to_date": state["up_to_date"]},
    }


@router.get("/opportunities", response_model=OpportunityList, tags=["opportunities"], responses=_ERRORS,
            summary="Search published opportunities (collections hidden by default)")
def opportunities(
    rt: Runtime = Depends(get_runtime),
    repo: SqlRepository = Depends(get_repo),
    q: str | None = Query(None, max_length=100, description="Words that must all appear in title, summary or provider (accent/case-insensitive)."),
    province: Province | None = Query(None, description="Keep records that can apply in this province/territory; records with no recorded geographic rule are kept with applicability=unknown."),
    education_level: EducationLevel | None = Query(None, description="Same semantics as province."),
    opportunity_type: OpportunityType | None = Query(None, description="award_collection records appear only when requested explicitly."),
    include_closed: bool = Query(False, description="Include opportunities whose current cycle is closed."),
    exclude_unknown_applicability: bool = Query(False, description="Drop records whose applicability to the filter is unknown."),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    as_of: str | None = Query(None, max_length=40, description="Reference time for availability (default: now)."),
) -> dict:
    records = repo.list_records(published_only=True, is_demo=(rt.mode == "demo"))
    return list_opportunities(
        records, as_of=reference_time(as_of), freshness_days=rt.freshness_days, data_mode=rt.mode, q=q,
        province=province, education_level=education_level, opportunity_type=opportunity_type,
        include_closed=include_closed, exclude_unknown_applicability=exclude_unknown_applicability,
        limit=limit, offset=offset)


@router.get("/opportunities/{opportunity_id:path}", response_model=OpportunityDetail, tags=["opportunities"],
            responses=_ERRORS, summary="One opportunity with cycles, evidence, verification state and next steps")
def opportunity(opportunity_id: str, rt: Runtime = Depends(get_runtime), repo: SqlRepository = Depends(get_repo),
                as_of: str | None = Query(None, max_length=40)) -> dict:
    record = repo.get_record(opportunity_id, published_only=True)
    if record is None or record["is_demo"] != (rt.mode == "demo"):
        raise HTTPException(status_code=404, detail="opportunity not found")
    others = repo.list_records(published_only=True, is_demo=(rt.mode == "demo"))
    return opportunity_detail(record, others, as_of=reference_time(as_of), freshness_days=rt.freshness_days,
                              data_mode=rt.mode)


@router.post("/match", response_model=MatchResponse, tags=["matching"], responses=_ERRORS,
             summary="Explainable rule-based eligibility check (not a prediction)")
def match(body: MatchRequest, request: Request, rt: Runtime = Depends(get_runtime),
          repo: SqlRepository = Depends(get_repo)) -> dict:
    """The profile exists only for this call: it is not stored, logged, or returned."""
    records = repo.list_records(published_only=True, is_demo=(rt.mode == "demo"))
    options = MatchOptions(
        as_of=parse_as_of(body.as_of), cycle_key=body.cycle_key, group_by_application=body.group_by_application,
        include_closed=body.include_closed, limit=body.limit, offset=body.offset, freshness_days=rt.freshness_days)
    return match_records(records, body.profile.to_engine(), options, request.app.state.institutions.resolve,
                         data_mode=rt.mode)


@router.get("/reports/freshness", response_model=dict[str, Any], tags=["reports"], responses=_ERRORS,
            summary="Data freshness report for the current dataset (no file paths exposed)")
def freshness(rt: Runtime = Depends(get_runtime), repo: SqlRepository = Depends(get_repo),
              as_of: str | None = Query(None, max_length=40)) -> dict:
    moment = reference_time(as_of)
    records = repo.list_records(published_only=False, is_demo=(rt.mode == "demo"), with_meta=True)
    return build_freshness_report(records, mode=rt.mode, as_of=moment, generated_at=parse_as_of(None),
                                  freshness_days=rt.freshness_days, run_context=repo.latest_run_context(rt.mode),
                                  parameters={"source": "api"})
