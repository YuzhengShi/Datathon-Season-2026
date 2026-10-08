"""Closed vocabularies shared by the API schemas (pydantic-free so tests can check them anywhere)."""

from __future__ import annotations

from typing import Literal

Province = Literal["AB", "BC", "MB", "NB", "NL", "NS", "NT", "NU", "ON", "PE", "QC", "SK", "YT"]
Identity = Literal["first_nations", "inuit", "metis"]
EducationLevel = Literal["high_school", "trades_vocational", "college", "undergraduate", "masters", "doctoral"]
StudyStatus = Literal["full_time", "part_time"]
OpportunityType = Literal["award", "funding_channel", "award_collection"]
EligibilityResult = Literal["pass", "fail", "unknown"]
MatchStatus = Literal["potential_fit", "not_eligible", "needs_information", "needs_provider_confirmation"]
Availability = Literal["open", "upcoming", "closed", "unknown", "contact_administrator"]
DataMode = Literal["live", "demo"]
