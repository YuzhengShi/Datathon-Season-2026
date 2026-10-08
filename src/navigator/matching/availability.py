"""Application availability, computed separately from eligibility.

An expired cycle is *closed*, never "not eligible". ``open`` is only reported when the source
supports it: a stated start date (or a stated rolling intake) together with a window that has
not ended. A future deadline alone does not prove an application is open.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta

from navigator.core.timeutil import format_utc, resolve_close_window

STATUSES = ("open", "upcoming", "closed", "unknown", "contact_administrator")
_RANK = {"open": 0, "upcoming": 1, "contact_administrator": 2, "unknown": 3, "closed": 4}


def _day_end_utc(day: date) -> datetime:
    """Latest instant at which ``day`` can still be running anywhere on Earth (UTC-12)."""
    return datetime.combine(day + timedelta(days=1), time(12, 0), tzinfo=UTC)


def _day_start_utc(day: date) -> datetime:
    """Earliest instant at which ``day`` has begun anywhere on Earth (UTC+14)."""
    return datetime.combine(day, time(0, 0), tzinfo=UTC) - timedelta(hours=14)


def cycle_availability(cycle: dict, as_of: datetime) -> dict:
    as_of = as_of.astimezone(UTC)
    deadlines = cycle.get("deadlines") or []
    windows = [(d, resolve_close_window(d)) for d in deadlines]
    dated = [(d, w) for d, w in windows if w is not None]
    states = [w.state(as_of) for _, w in dated]
    flags: list[str] = []
    for _, w in dated:
        flags.extend(w.flags)
    kinds = {d.get("kind") for d in deadlines}
    starts = date.fromisoformat(cycle["starts_on"]) if cycle.get("starts_on") else None
    ends = date.fromisoformat(cycle["ends_on"]) if cycle.get("ends_on") else None
    if "annual_rule" in kinds:
        flags.append("annual_rule_unconfirmed")
    if "local_administrator" in kinds:
        flags.append("local_administrator_deadline")
    if not deadlines or kinds <= {"unspecified"}:
        flags.append("deadline_unknown")
    if any(s == "closing_ambiguous" for s in states):
        flags.append("closing_time_ambiguous")

    pending = [w for (_, w), s in zip(dated, states, strict=True) if s != "closed"]
    next_close = min((w.latest_utc for w in pending), default=None)
    started = starts is not None and as_of >= _day_start_utc(starts)
    not_started = starts is not None and as_of < _day_start_utc(starts)
    ended = ends is not None and as_of >= _day_end_utc(ends)

    def result(status: str, reason: str) -> dict:
        return {
            "status": status,
            "reason": reason,
            "next_deadline_utc": format_utc(next_close) if next_close else None,
            "flags": sorted(set(flags)),
        }

    if not_started:
        return result("upcoming", "the application window has not opened yet")
    if ended:
        return result("closed", "the stated application window has ended")
    if dated and not pending and "rolling" not in kinds and "local_administrator" not in kinds:
        return result("closed", "every stated deadline has passed")
    if pending:
        if started:
            return result("open", "the window has opened and a deadline is still ahead")
        return result("unknown", "a deadline is ahead but the source does not say the window is open")
    if "rolling" in kinds and not ended:
        return result("open", "the source states applications are accepted on a rolling basis")
    if "local_administrator" in kinds:
        return result("contact_administrator", "the deadline is set by a local administrator")
    if started and ends is not None:
        return result("open", "stated start and end dates surround today")
    return result("unknown", "the source gives no dated, verifiable application window")


def _sort_date(cycle: dict) -> int:
    candidates = [cycle.get("ends_on"), cycle.get("starts_on")]
    candidates += [d.get("date") for d in cycle.get("deadlines") or []]
    ordinals = [date.fromisoformat(c).toordinal() for c in candidates if c]
    return max(ordinals, default=0)


def select_cycle(record: dict, as_of: datetime, cycle_key: str | None = None) -> tuple[dict | None, dict | None]:
    """Pick the cycle to evaluate: the requested one, else the most relevant current one.

    Preference: open > upcoming > contact_administrator > unknown > closed; ties go to the
    most recent cycle, then to the larger ``cycle_key`` so the choice is deterministic.
    """
    cycles = record.get("cycles") or []
    if cycle_key is not None:
        for cycle in cycles:
            if cycle["cycle_key"] == cycle_key:
                return cycle, cycle_availability(cycle, as_of)
        return None, None
    scored = []
    for cycle in cycles:
        avail = cycle_availability(cycle, as_of)
        scored.append((_RANK[avail["status"]], -_sort_date(cycle), _neg_key(cycle["cycle_key"]), cycle, avail))
    if not scored:
        return None, None
    scored.sort(key=lambda t: t[:3])
    return scored[0][3], scored[0][4]


def _neg_key(key: str) -> tuple[int, ...]:
    return tuple(-ord(ch) for ch in key)


def freshness_flags(record: dict, cycle: dict, availability: dict, as_of: datetime, freshness_days: int) -> list[str]:
    flags = set(availability["flags"])
    verified = record.get("last_verified_at")
    if not verified:
        flags.add("never_verified")
    else:
        age = as_of - datetime.fromisoformat(verified.replace("Z", "+00:00"))
        if age > timedelta(days=freshness_days):
            flags.add("verification_stale")
    if cycle.get("cycle_key") == "unspecified":
        flags.add("cycle_unspecified")
    if (cycle.get("amount") or {}).get("kind") == "unspecified":
        flags.add("amount_unknown")
    elig = cycle.get("eligibility") or {}
    if elig.get("unstructured") or not elig.get("mandatory"):
        flags.add("eligibility_not_fully_structured")
    if availability["status"] == "closed":
        flags.add("historical_cycle_only")
    if (record.get("_meta") or {}).get("changed_since_verified"):
        flags.add("source_changed_since_verification")
    return sorted(flags)
