"""The student profile accepted by ``POST /match``.

It is used inside one request only: never stored, never logged, never echoed back, never sent to an
extraction model. There is deliberately no field for a name, address, e-mail, SIN, status-card or
membership number, student number, income, or any application document.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from navigator.core.timeutil import parse_as_of
from navigator.schemas.types import EducationLevel, Identity, Province, StudyStatus


class Profile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    indigenous_identity: list[Identity] | None = Field(
        None, description="Self-reported; one or more. Absent = unknown. [] = none of these.", max_length=3)
    first_nations_registered: bool | None = Field(
        None, description="Self-reported registration (yes/no). Never send a card or registry number.")
    metis_citizen: bool | None = Field(None, description="Self-reported citizenship/membership; no number.")
    metis_org: str | None = Field(None, max_length=120, description="Which Métis government/organisation.")
    inuit_beneficiary: bool | None = Field(None, description="Self-reported beneficiary status; no number.")
    inuit_org: str | None = Field(None, max_length=120, description="Which Inuit organisation/region.")
    residence_province: Province | None = Field(None, description="Where you live (not where you study).")
    home_community: str | None = Field(None, max_length=120, description="Home community (separate from residence).")
    home_region: str | None = Field(None, max_length=120)
    institution_id: str | None = Field(None, max_length=80, description="Controlled institution id, if known.")
    institution_name: str | None = Field(None, max_length=200, description="Used only if it matches the explicit alias map.")
    institution_province: Province | None = Field(None, description="Province/territory of the school.")
    campus: str | None = Field(None, max_length=120)
    education_level: EducationLevel | None = None
    program_field: str | None = Field(None, max_length=120)
    study_status: StudyStatus | None = None
    year_of_study: int | None = Field(None, ge=1, le=12)
    gpa: Decimal | None = Field(None, ge=0, le=1000, description="Compared only when gpa_scale equals the rule's scale.")
    gpa_scale: Decimal | None = Field(None, gt=0, le=1000)

    def to_engine(self) -> dict[str, Any]:
        """Plain dict for the rule engine (unknown fields are simply absent)."""
        data = self.model_dump(exclude_none=True)
        for key in ("gpa", "gpa_scale"):
            if key in data:
                data[key] = format(data[key], "f")
        return data


class MatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    profile: Profile
    as_of: str | None = Field(None, max_length=40, description="Reference time (ISO date or datetime). A bare date means 12:00 UTC. Default: now.")
    cycle_key: str | None = Field(None, pattern=r"^[a-z0-9][a-z0-9_.-]{0,59}$", description="Match this cycle instead of the most relevant one.")
    group_by_application: bool = Field(False, description="Aggregate results by shared application form (each member still matched separately).")
    include_closed: bool = Field(False, description="Include cycles whose application window has closed.")
    limit: int = Field(20, ge=1, le=100)
    offset: int = Field(0, ge=0)

    @field_validator("as_of")
    @classmethod
    def _check_as_of(cls, value: str | None) -> str | None:
        if value is not None:
            try:
                parse_as_of(value)
            except (ValueError, TypeError):
                raise ValueError("as_of must be an ISO date or datetime") from None
        return value
