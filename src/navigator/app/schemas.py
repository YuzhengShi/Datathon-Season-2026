from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

Community = Literal["First Nations", "Inuit", "Métis"]
Province = Literal[
    "British Columbia",
    "Alberta",
    "Saskatchewan",
    "Manitoba",
    "Ontario",
    "Quebec",
    "New Brunswick",
    "Nova Scotia",
    "Prince Edward Island",
    "Newfoundland and Labrador",
    "Yukon",
    "Northwest Territories",
    "Nunavut",
]
Goal = Literal["postsecondary", "training"]


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SearchFilters(Contract):
    q: str = Field(default="", max_length=150)
    communities: list[Community] = Field(default_factory=list, max_length=3)
    provinces: list[Province] = Field(default_factory=list, max_length=13)
    types: list[Literal["Scholarship", "Program"]] = Field(default_factory=list, max_length=2)
    goals: list[Goal] = Field(default_factory=list, max_length=2)
    scope: Literal["all", "national", "regional", "unspecified"] = "all"
    amount_band: Literal["all", "listed", "high", "unknown", "under5000"] = "all"
    amount_kind: Literal["all", "fixed", "range", "maximum", "variable", "pooled_total", "unspecified"] = "all"
    education_levels: list[Literal["high_school", "college", "undergraduate", "graduate", "vocational"]] = Field(
        default_factory=list, max_length=5
    )
    fields_of_study: list[Literal["business", "stem", "health", "arts", "trades"]] = Field(
        default_factory=list, max_length=5
    )
    study_modes: list[Literal["full_time", "part_time"]] = Field(default_factory=list, max_length=2)
    expenses: list[Literal["tuition", "living", "travel", "books"]] = Field(default_factory=list, max_length=4)
    renewable: Literal["all", "yes", "no", "unknown"] = "all"
    deadline_kind: Literal["all", "date", "annual_rule", "rolling", "local_administrator", "unspecified"] = "all"
    providers: list[str] = Field(default_factory=list, max_length=20)
    include_unknown: bool = True
    sort: Literal["recommended", "amount", "alphabetical"] = "recommended"

    @field_validator("providers")
    @classmethod
    def bounded_provider_names(cls, values: list[str]) -> list[str]:
        if any(len(x) > 150 for x in values):
            raise ValueError("Provider name is too long")
        return list(dict.fromkeys(values))


class AppProfile(Contract):
    communities: list[Community] = Field(default_factory=list, max_length=3)
    residence_province: Province | None = None
    institution_province: Province | None = None
    goal: Goal | None = None
    education_level: Literal["high_school", "college", "undergraduate", "graduate", "vocational"] | None = None
    study_mode: Literal["full_time", "part_time"] | None = None
    institution_id: str | None = Field(default=None, max_length=60)
    first_nations_registered: bool | None = None
    metis_citizen: bool | None = None
    inuit_beneficiary: bool | None = None


class SearchRequest(Contract):
    filters: SearchFilters = Field(default_factory=SearchFilters)
    limit: int = Field(default=24, ge=1, le=100)
    offset: int = Field(default=0, ge=0, le=10000)


class AppMatchRequest(Contract):
    filters: SearchFilters = Field(default_factory=SearchFilters)
    profile: AppProfile = Field(default_factory=AppProfile)
    limit: int = Field(default=12, ge=1, le=24)


class HistoryMessage(Contract):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=1800)


class ConversationRequest(Contract):
    mode: Literal["search", "match", "analysis"]
    message: str = Field(min_length=1, max_length=1800)
    history: list[HistoryMessage] = Field(default_factory=list, max_length=10)
    filters: SearchFilters = Field(default_factory=SearchFilters)
    profile: AppProfile = Field(default_factory=AppProfile)


class DetailArgs(Contract):
    opportunity_id: str = Field(min_length=1, max_length=100)


class StatisticsArgs(Contract):
    filters: SearchFilters


class EmptyArgs(Contract):
    pass


class Recommendation(Contract):
    opportunity_id: str
    reason_codes: list[Literal["community", "location", "study_plans", "amount", "provider_confirmation"]]


class AssistantDraft(Contract):
    intent_summary: str = Field(max_length=180)
    question: str | None
    recommendations: list[Recommendation] = Field(max_length=12)
