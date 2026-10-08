"""Response models. Deeply nested, source-shaped structures (rules, deadlines, amounts, evidence)
are typed as free-form objects here and documented in docs/DATA_MODEL.md."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from navigator.schemas.types import Availability, DataMode, EligibilityResult, MatchStatus


class ErrorBody(BaseModel):
    code: str = Field(description="Stable machine-readable code, e.g. http_404 or validation_error")
    message: str
    details: list[dict[str, Any]] | None = None


class ErrorResponse(BaseModel):
    error: ErrorBody
    data_mode: DataMode


class DatabaseState(BaseModel):
    connected: bool


class MigrationState(BaseModel):
    current: str | None
    expected: str
    up_to_date: bool


class HealthResponse(BaseModel):
    status: str = Field(description="ok | degraded")
    data_mode: DataMode
    version: str
    database: DatabaseState
    migrations: MigrationState


class ProviderRef(BaseModel):
    id: str
    name: str
    donor_name: str | None = None


class ApplicationRoute(BaseModel):
    route_type: str
    url: str | None = None
    contact_url: str | None = None
    instructions: str | None = None


class CurrentCycle(BaseModel):
    cycle_key: str
    availability_status: Availability
    next_deadline_utc: str | None = None
    amount: dict[str, Any]
    application_group_id: str | None = None


class ApplicabilityInfo(BaseModel):
    province: str | None = Field(None, description="applies | not_applicable | unknown (null when not filtered)")
    education_level: str | None = None


class OpportunitySummary(BaseModel):
    id: str
    title: str
    opportunity_type: str
    provider: ProviderRef
    official_url: str
    summary: str
    application_route: ApplicationRoute
    current_cycle: CurrentCycle
    applicability: ApplicabilityInfo
    review_status: str
    last_verified_at: str | None = None
    freshness_flags: list[str]


class OpportunityList(BaseModel):
    data_mode: DataMode
    as_of: str
    total: int
    limit: int
    offset: int
    count: int
    filters: dict[str, Any]
    results: list[OpportunitySummary]


class SiblingRef(BaseModel):
    id: str
    title: str


class OpportunityDetail(BaseModel):
    data_mode: DataMode
    as_of: str
    opportunity: dict[str, Any]
    current_cycle_key: str | None = None
    cycles: list[dict[str, Any]]
    shared_application_with: list[SiblingRef]
    next_steps: list[str]
    verification: dict[str, Any]


class AvailabilityInfo(BaseModel):
    reason: str
    next_deadline_utc: str | None = None


class MatchItem(BaseModel):
    opportunity_id: str
    title: str
    opportunity_type: str
    cycle_key: str
    eligibility_result: EligibilityResult
    match_status: MatchStatus
    passed_rules: list[dict[str, Any]]
    failed_rules: list[dict[str, Any]]
    unknown_rules: list[dict[str, Any]]
    missing_profile_fields: list[str]
    clarification_questions: list[str]
    source_uncertainties: list[str]
    preference_matches: list[dict[str, Any]]
    funder_side_conditions: list[dict[str, Any]] = Field(
        description="Conditions on the organisation that receives the funds. They do NOT decide the student's eligibility.")
    evidence_refs: list[dict[str, Any]]
    amount: dict[str, Any]
    deadlines: list[dict[str, Any]]
    availability_status: Availability
    availability: AvailabilityInfo
    official_url: str
    application_route: ApplicationRoute
    application_group_id: str | None = None
    next_action: str
    review_status: str
    last_verified_at: str | None = None
    freshness_flags: list[str]


class MatchGroup(BaseModel):
    group_id: str | None = Field(None, description="null for an opportunity that is not part of a shared application")
    label: str | None = None
    cycle_key: str
    application_url: str | None = None
    members: list[MatchItem]
    member_status_counts: dict[str, int]
    notice: str | None = None


class MatchResponse(BaseModel):
    data_mode: DataMode
    as_of: str
    group_by_application: bool
    limit: int
    offset: int
    total: int = Field(description="Number of opportunity-cycle results after filtering")
    total_groups: int | None = Field(None, description="Set when group_by_application is true (pagination is by group)")
    excluded_closed_count: int
    results: list[MatchItem] | None = None
    groups: list[MatchGroup] | None = None
    disclaimer: str
