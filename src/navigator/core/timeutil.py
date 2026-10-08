"""UTC clock, timezone resolution and deadline close-window semantics.

Design rule
-----------
A deadline resolves to a *window* of possible closing instants
``[earliest_utc, latest_utc]``. An application counts as **closed** only when
``as_of >= latest_utc``. Ambiguity (unknown timezone, literal "EST" in summer, a repeated
or skipped local hour at a DST change) therefore widens the window and can never close an
application early. A date-only deadline closes at the *end* of that local date, never at
00:00 of that date.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta, timezone
from typing import Protocol
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

# Extreme UTC offsets that exist in the real world; used when the zone is unknown.
_EARLIEST_ZONE = timezone(timedelta(hours=14))  # UTC+14: a given local time happens first here
_LATEST_ZONE = timezone(timedelta(hours=-12))  # UTC-12: ... and last here

_ABBREV_OFFSET_MINUTES = {
    "EST": -300,
    "EDT": -240,
    "CST": -360,
    "CDT": -300,
    "MST": -420,
    "MDT": -360,
    "PST": -480,
    "PDT": -420,
    "AST": -240,
    "ADT": -180,
    "NST": -210,
    "NDT": -150,
    "UTC": 0,
    "GMT": 0,
}
_ABBREV_GENERIC_ZONE = {
    "EST": "America/Toronto",
    "EDT": "America/Toronto",
    "CST": "America/Winnipeg",
    "CDT": "America/Winnipeg",
    "MST": "America/Edmonton",
    "MDT": "America/Edmonton",
    "PST": "America/Vancouver",
    "PDT": "America/Vancouver",
    "AST": "America/Halifax",
    "ADT": "America/Halifax",
    "NST": "America/St_Johns",
    "NDT": "America/St_Johns",
}
_GENERIC_NAMES = {
    "eastern time": "America/Toronto",
    "eastern": "America/Toronto",
    "et": "America/Toronto",
    "central time": "America/Winnipeg",
    "ct": "America/Winnipeg",
    "mountain time": "America/Edmonton",
    "mt": "America/Edmonton",
    "pacific time": "America/Vancouver",
    "pt": "America/Vancouver",
    "atlantic time": "America/Halifax",
    "newfoundland time": "America/St_Johns",
}

_DATE_ONLY = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class Clock(Protocol):
    """Injectable time source."""

    def now(self) -> datetime: ...


class SystemClock:
    def now(self) -> datetime:
        return datetime.now(UTC)


@dataclass(frozen=True)
class FixedClock:
    instant: datetime

    def now(self) -> datetime:
        return self.instant


def parse_iso_datetime(value: str) -> datetime:
    """Parse an ISO-8601 datetime. A missing offset is interpreted as UTC."""
    dt = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def parse_as_of(value: str | date | datetime | None, clock: Clock | None = None) -> datetime:
    """Return the reference instant (aware, UTC).

    ``None`` -> the clock's current time. A bare date means 12:00 UTC on that date, so a
    reproducible ``--as-of 2026-10-07`` is unambiguous.
    """
    if value is None:
        return (clock or SystemClock()).now().astimezone(UTC)
    if isinstance(value, datetime):
        return (value if value.tzinfo else value.replace(tzinfo=UTC)).astimezone(UTC)
    if isinstance(value, date):
        return datetime(value.year, value.month, value.day, 12, 0, tzinfo=UTC)
    text = value.strip()
    if _DATE_ONLY.match(text):
        d = date.fromisoformat(text)
        return datetime(d.year, d.month, d.day, 12, 0, tzinfo=UTC)
    return parse_iso_datetime(text)


def format_utc(dt: datetime) -> str:
    """``2026-10-07T12:00:00Z`` (seconds precision)."""
    return dt.astimezone(UTC).replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%SZ")


@dataclass(frozen=True)
class TzCandidate:
    """One concrete way to interpret a written timezone."""

    iana: str | None = None
    fixed_minutes: int | None = None

    def local_to_utc_options(self, local: datetime) -> list[datetime]:
        """All UTC instants a naive local datetime can denote under this interpretation."""
        if self.fixed_minutes is not None:
            offset = timezone(timedelta(minutes=self.fixed_minutes))
            return [local.replace(tzinfo=offset).astimezone(UTC)]
        assert self.iana is not None
        zone = ZoneInfo(self.iana)
        first = local.replace(tzinfo=zone, fold=0).astimezone(UTC)
        second = local.replace(tzinfo=zone, fold=1).astimezone(UTC)
        return [first] if first == second else [first, second]


@dataclass(frozen=True)
class TzResolution:
    raw: str | None
    status: str  # "iana" | "generic" | "fixed" | "ambiguous" | "unknown"
    candidates: tuple[TzCandidate, ...]
    note: str | None = None

    @property
    def known(self) -> bool:
        return self.status in {"iana", "generic", "fixed"}


def _offset_minutes(zone_name: str, on: date) -> int:
    local_noon = datetime.combine(on, time(12, 0), tzinfo=ZoneInfo(zone_name))
    offset = local_noon.utcoffset()
    assert offset is not None
    return int(offset.total_seconds() // 60)


def resolve_timezone(raw: str | None, on_date: date | None = None) -> TzResolution:
    """Interpret a written timezone.

    * IANA names (``America/Toronto``) are exact.
    * Generic names (``Eastern Time``, ``ET``) mean the regional zone *with* daylight saving.
    * Literal abbreviations (``EST``) mean a fixed offset. If that contradicts the regional
      zone's offset on ``on_date`` (e.g. "EST" in July) the result is ``ambiguous`` and
      carries both interpretations, so the deadline is never closed early.
    """
    if raw is None or not str(raw).strip():
        return TzResolution(raw, "unknown", (), "no timezone stated")
    text = str(raw).strip()

    if "/" in text or text.upper() == "UTC":
        try:
            ZoneInfo(text)
        except (ZoneInfoNotFoundError, ValueError):
            return TzResolution(raw, "unknown", (), f"unrecognised IANA zone {text!r}")
        return TzResolution(raw, "iana", (TzCandidate(iana=text),))

    lowered = text.lower()
    if lowered in _GENERIC_NAMES:
        return TzResolution(
            raw,
            "generic",
            (TzCandidate(iana=_GENERIC_NAMES[lowered]),),
            "generic zone name interpreted with daylight-saving rules",
        )

    upper = text.upper()
    if upper in _ABBREV_OFFSET_MINUTES:
        literal = TzCandidate(fixed_minutes=_ABBREV_OFFSET_MINUTES[upper])
        generic = _ABBREV_GENERIC_ZONE.get(upper)
        if generic is not None and on_date is not None:
            if _offset_minutes(generic, on_date) != literal.fixed_minutes:
                return TzResolution(
                    raw,
                    "ambiguous",
                    (literal, TzCandidate(iana=generic)),
                    f"literal {upper} conflicts with {generic} daylight-saving offset on "
                    f"{on_date.isoformat()}; both readings kept",
                )
        return TzResolution(raw, "fixed", (literal,), f"literal fixed offset {upper}")

    return TzResolution(raw, "unknown", (), f"unrecognised timezone {text!r}")


@dataclass(frozen=True)
class CloseWindow:
    """Range of instants at which an application may actually close."""

    earliest_utc: datetime
    latest_utc: datetime
    flags: tuple[str, ...]
    basis: str  # "stated_time" | "end_of_local_day"

    @property
    def exact(self) -> bool:
        return self.earliest_utc == self.latest_utc

    def state(self, as_of: datetime) -> str:
        """``closed`` | ``not_closed`` | ``closing_ambiguous``."""
        as_of = as_of.astimezone(UTC)
        if as_of >= self.latest_utc:
            return "closed"
        if as_of < self.earliest_utc:
            return "not_closed"
        return "closing_ambiguous"


def _parse_local_time(text: str) -> tuple[time, timedelta]:
    """Return (time, granularity). A stated minute is valid for the whole minute."""
    parts = text.strip().split(":")
    if len(parts) == 2:
        return time(int(parts[0]), int(parts[1])), timedelta(minutes=1)
    if len(parts) == 3:
        return time(int(parts[0]), int(parts[1]), int(float(parts[2]))), timedelta(seconds=1)
    raise ValueError(f"bad local_time {text!r}")


def resolve_close_window(deadline: dict) -> CloseWindow | None:
    """Window for a ``date`` / ``datetime`` deadline; ``None`` for every other kind.

    ``annual_rule``, ``rolling``, ``local_administrator`` and ``unspecified`` deadlines never
    resolve to an instant.
    """
    kind = deadline.get("kind")
    if kind not in {"date", "datetime"} or not deadline.get("date"):
        return None
    day = date.fromisoformat(deadline["date"])
    local_time = deadline.get("local_time")
    if local_time:
        t, granularity = _parse_local_time(local_time)
        local_close = datetime.combine(day, t) + granularity
        basis = "stated_time"
    else:
        local_close = datetime.combine(day + timedelta(days=1), time(0, 0))
        basis = "end_of_local_day"

    resolution = resolve_timezone(deadline.get("timezone"), day)
    flags: list[str] = []
    options: list[datetime] = []
    if resolution.known or resolution.status == "ambiguous":
        for cand in resolution.candidates:
            options.extend(cand.local_to_utc_options(local_close))
        if resolution.status == "ambiguous":
            flags.append("timezone_ambiguous")
        # fold / gap detection for IANA candidates
        for cand in resolution.candidates:
            if cand.iana:
                opts = cand.local_to_utc_options(local_close)
                if len(opts) == 2:
                    zone = ZoneInfo(cand.iana)
                    round_trip = opts[0].astimezone(zone).replace(tzinfo=None)
                    flags.append(
                        "dst_repeated_local_time"
                        if round_trip == local_close
                        else "dst_skipped_local_time"
                    )
    else:
        flags.append("timezone_unknown")
        options = [
            local_close.replace(tzinfo=_EARLIEST_ZONE).astimezone(UTC),
            local_close.replace(tzinfo=_LATEST_ZONE).astimezone(UTC),
        ]
    return CloseWindow(min(options), max(options), tuple(sorted(set(flags))), basis)


def canonical_deadline_utc(deadline: dict) -> str | None:
    """The unambiguous closing instant as UTC text, or ``None`` if it is not exact."""
    window = resolve_close_window(deadline)
    if window is None or not window.exact:
        return None
    return format_utc(window.latest_utc)
