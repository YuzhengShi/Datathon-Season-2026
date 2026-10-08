"""Polite, bounded HTTP fetching with an injectable transport.

All policy lives here and is transport-independent: allowlist + SSRF checks on every hop,
robots.txt, per-host spacing, bounded retries (429 honours a *bounded* ``Retry-After``),
redirect limits, conditional requests (304 only reuses an existing snapshot), size caps and
media-type checks. :class:`navigator.ingestion.http_transport.HttpxTransport` is the thin real
adapter; tests drive this class with a scripted fake transport and never touch the network.
"""

from __future__ import annotations

import email.utils
import time
import urllib.robotparser
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Protocol
from urllib.parse import urljoin, urlsplit

from navigator.core.urlpolicy import AllowRule, UnsafeUrlError, canonicalize_url, check_url

ACCEPTED_MEDIA = ("text/html", "application/xhtml+xml", "application/pdf", "text/plain", "application/json")
_RETRYABLE_STATUS = {500, 502, 503, 504}
_REDIRECT_STATUS = {301, 302, 303, 307, 308}


class TransportError(Exception):
    """Network-level failure. ``kind``: timeout | connect | too_large | protocol."""

    def __init__(self, kind: str, message: str = "") -> None:
        super().__init__(message or kind)
        self.kind = kind


@dataclass(frozen=True)
class HttpResponse:
    status: int
    headers: dict[str, str]  # lower-case names
    body: bytes
    url: str


class Transport(Protocol):
    def get(self, url: str, headers: Mapping[str, str], timeout: float, max_bytes: int) -> HttpResponse:
        """One GET, no redirect following, body capped at ``max_bytes`` (raise TransportError('too_large'))."""
        ...


@dataclass(frozen=True)
class FetchPolicy:
    user_agent: str
    timeout: float = 30.0
    max_bytes: int = 10 * 1024 * 1024
    retries: int = 3
    min_interval: float = 1.0
    max_redirects: int = 5
    backoff_base: float = 1.0
    backoff_max: float = 30.0
    retry_after_max: float = 60.0


@dataclass
class FetchOutcome:
    url: str
    outcome: str  # ok | not_modified | failed | blocked
    reason: str | None = None
    final_url: str | None = None
    status: int | None = None
    attempts: int = 0
    duration_ms: int = 0
    size: int = 0
    media_type: str | None = None
    etag: str | None = None
    last_modified: str | None = None
    body: bytes | None = None
    redirects: list[str] = field(default_factory=list)
    robots_status: str | None = None

    def audit(self) -> dict:
        """Row for the fetch audit trail (no body)."""
        return {
            "url": self.url,
            "final_url": self.final_url,
            "outcome": self.outcome,
            "reason": self.reason,
            "http_status": self.status,
            "attempts": self.attempts,
            "duration_ms": self.duration_ms,
            "bytes": self.size,
            "etag": self.etag,
            "last_modified": self.last_modified,
            "redirects": self.redirects,
            "robots_status": self.robots_status,
        }


def parse_retry_after(value: str | None, now: Callable[[], float] = time.time) -> float | None:
    """Seconds to wait from a ``Retry-After`` header (delta-seconds or HTTP-date)."""
    if not value:
        return None
    value = value.strip()
    if value.isdigit():
        return float(value)
    try:
        when = email.utils.parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
    return max(0.0, when.timestamp() - now())


class Fetcher:
    def __init__(
        self,
        transport: Transport,
        policy: FetchPolicy,
        *,
        resolver: Callable[[str], Sequence[str]] | None = None,
        sleeper: Callable[[float], None] = time.sleep,
        monotonic: Callable[[], float] = time.monotonic,
        respect_robots: bool = True,
        wall_clock: Callable[[], float] = time.time,
    ) -> None:
        self.transport, self.policy, self.resolver = transport, policy, resolver
        self._sleep, self._mono, self._wall = sleeper, monotonic, wall_clock
        self.respect_robots = respect_robots
        self._next_ok: dict[str, float] = {}
        self._robots: dict[str, tuple[urllib.robotparser.RobotFileParser | None, str]] = {}

    # ------------------------------------------------------------------ helpers
    def _pace(self, host: str) -> None:
        wait = self._next_ok.get(host, 0.0) - self._mono()
        if wait > 0:
            self._sleep(wait)

    def _mark(self, host: str) -> None:
        self._next_ok[host] = self._mono() + self.policy.min_interval

    def _backoff(self, attempt: int) -> float:
        return min(self.policy.backoff_max, self.policy.backoff_base * (2**attempt))

    def _request(self, url: str, headers: dict[str, str]) -> tuple[HttpResponse | None, str | None, int]:
        """GET with bounded retries. Returns (response, failure_reason, attempts)."""
        host = (urlsplit(url).hostname or "").lower()
        attempts = 0
        for attempt in range(self.policy.retries + 1):
            attempts += 1
            self._pace(host)
            try:
                response = self.transport.get(url, headers, self.policy.timeout, self.policy.max_bytes)
            except TransportError as exc:
                self._mark(host)
                if exc.kind == "too_large":
                    return None, "response_too_large", attempts
                if attempt < self.policy.retries:
                    self._sleep(self._backoff(attempt))
                    continue
                return None, f"transport_{exc.kind}", attempts
            self._mark(host)
            if len(response.body) > self.policy.max_bytes:
                return None, "response_too_large", attempts
            if response.status == 429:
                delay = parse_retry_after(response.headers.get("retry-after"), self._wall)
                if delay is not None and delay > self.policy.retry_after_max:
                    return None, "retry_after_too_long", attempts
                if attempt < self.policy.retries:
                    self._sleep(delay if delay is not None else self._backoff(attempt))
                    continue
                return None, "http_429", attempts
            if response.status in _RETRYABLE_STATUS and attempt < self.policy.retries:
                self._sleep(self._backoff(attempt))
                continue
            return response, None, attempts
        return None, "retries_exhausted", attempts  # pragma: no cover

    def robots_status(self, url: str) -> tuple[bool, str]:
        """(allowed, status). RFC 9309: 4xx = no rules; 5xx/unreachable = treat as disallowed."""
        if not self.respect_robots:
            return True, "not_checked"
        parts = urlsplit(url)
        origin = f"{parts.scheme}://{parts.netloc}"
        if origin not in self._robots:
            robots_url = f"{origin}/robots.txt"
            decision = check_url(
                robots_url, [AllowRule((parts.hostname or "",), ("/robots.txt",))], resolver=self.resolver
            )
            parser: urllib.robotparser.RobotFileParser | None = None
            status = "unavailable"
            if decision.ok:
                response, reason, _ = self._request(robots_url, {"User-Agent": self.policy.user_agent})
                if response is not None and response.status == 200:
                    parser = urllib.robotparser.RobotFileParser()
                    parser.parse(response.body.decode("utf-8", "replace").splitlines())
                    status = "present"
                elif response is not None and 400 <= response.status < 500:
                    status = "not_found"
            self._robots[origin] = (parser, status)
        parser, status = self._robots[origin]
        if status == "unavailable":
            return False, status
        if parser is None:
            return True, status
        return parser.can_fetch(self.policy.user_agent, url), status

    # --------------------------------------------------------------------- main
    def fetch(
        self,
        url: str,
        rules: Sequence[AllowRule],
        *,
        etag: str | None = None,
        last_modified: str | None = None,
        have_snapshot: bool = False,
    ) -> FetchOutcome:
        """Fetch ``url``. Conditional headers are sent only when a snapshot exists to fall back on."""
        started = self._mono()
        conditional = bool(have_snapshot and (etag or last_modified))
        redirects: list[str] = []
        visited = set()
        current = url
        attempts = 0

        def done(
            outcome: str, reason: str | None = None, response: HttpResponse | None = None, robots: str | None = None
        ) -> FetchOutcome:
            out = FetchOutcome(
                url,
                outcome,
                reason,
                current,
                response.status if response else None,
                attempts,
                int((self._mono() - started) * 1000),
                len(response.body) if response else 0,
                None,
                None,
                None,
                None,
                redirects,
                robots,
            )
            if response is not None:
                out.media_type = response.headers.get("content-type", "").split(";")[0].strip().lower() or None
                out.etag, out.last_modified = response.headers.get("etag"), response.headers.get("last-modified")
                if outcome == "ok":
                    out.body = response.body
            return out

        robots_seen = None
        while True:
            decision = check_url(current, rules, resolver=self.resolver)
            if not decision.ok:
                return done("blocked", f"url_{decision.reason}")
            allowed, robots_seen = self.robots_status(current)
            if not allowed:
                return done(
                    "blocked",
                    f"robots_{robots_seen}" if robots_seen == "unavailable" else "robots_disallowed",
                    robots=robots_seen,
                )
            headers = {"User-Agent": self.policy.user_agent, "Accept": ", ".join(ACCEPTED_MEDIA)}
            if conditional:
                if etag:
                    headers["If-None-Match"] = etag
                if last_modified:
                    headers["If-Modified-Since"] = last_modified
            response, reason, used = self._request(current, headers)
            attempts += used
            if response is None:
                return done("failed", reason, robots=robots_seen)

            status = response.status
            if status in _REDIRECT_STATUS:
                location = response.headers.get("location")
                if not location:
                    return done("failed", "redirect_without_location", response, robots_seen)
                target = urljoin(current, location)
                if len(redirects) >= self.policy.max_redirects:
                    return done("failed", "too_many_redirects", response, robots_seen)
                try:
                    canonical = canonicalize_url(target)
                except UnsafeUrlError:
                    return done("blocked", "redirect_unsafe_url", response, robots_seen)
                visited.add(canonicalize_url(current))
                if canonical in visited:
                    return done("failed", "redirect_loop", response, robots_seen)
                redirects.append(target)
                current = target
                continue
            if status == 304:
                if conditional:
                    return done("not_modified", None, response, robots_seen)
                return done("failed", "unexpected_304", response, robots_seen)
            if 200 <= status < 300:
                media = response.headers.get("content-type", "").split(";")[0].strip().lower()
                if media and media not in ACCEPTED_MEDIA:
                    return done("failed", "unsupported_media_type", response, robots_seen)
                return done("ok", None, response, robots_seen)
            if status in {401, 403}:
                return done("failed", f"access_denied_{status}", response, robots_seen)
            return done("failed", f"http_{status}", response, robots_seen)
