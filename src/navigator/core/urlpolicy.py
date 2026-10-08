"""URL canonicalisation and the fetch allowlist / SSRF guard.

Canonicalisation only removes the fragment and well-known tracking parameters. Path case,
semantic query parameters (award ids, ``wbdisable=true``) and parameter order are preserved,
so two different award detail URLs never collapse into one.
"""

from __future__ import annotations

import ipaddress
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from urllib.parse import urlsplit, urlunsplit

TRACKING_PARAMS = frozenset({"gclid", "fbclid", "mc_cid", "mc_eid", "msclkid", "igshid", "_ga", "yclid", "dclid"})
TRACKING_PREFIXES = ("utm_",)
_BLOCKED_SUFFIXES = (".localhost", ".local", ".internal", ".lan", ".home.arpa", ".corp")
_BLOCKED_NAMES = frozenset({"localhost", "metadata.google.internal", "metadata"})
_DEFAULT_PORTS = {"http": 80, "https": 443}


class UnsafeUrlError(ValueError):
    """The URL cannot be used as a fetch target."""


@dataclass(frozen=True)
class AllowRule:
    """One allowed (domain, path-prefix) scope. ``*.example.ca`` allows subdomains."""

    domains: tuple[str, ...]
    path_prefixes: tuple[str, ...] = ("/",)

    def matches(self, host: str, path: str) -> bool:
        host_ok = any(host == d.lower() or (d.startswith("*.") and host.endswith(d[1:].lower())) for d in self.domains)
        return host_ok and any(path.startswith(p) for p in self.path_prefixes)


@dataclass(frozen=True)
class UrlDecision:
    ok: bool
    reason: str
    canonical: str | None = None


def _is_tracking(key: str) -> bool:
    lowered = key.lower()
    return lowered in TRACKING_PARAMS or lowered.startswith(TRACKING_PREFIXES)


def canonicalize_url(url: str) -> str:
    """Drop fragment + tracking params; lowercase scheme/host; keep everything else."""
    parts = urlsplit(url.strip())
    if parts.username or parts.password:
        raise UnsafeUrlError("credentials in URL")
    scheme = parts.scheme.lower()
    host = (parts.hostname or "").lower()
    if not scheme or not host:
        raise UnsafeUrlError("URL needs a scheme and host")
    port = parts.port
    netloc = host if port in (None, _DEFAULT_PORTS.get(scheme)) else f"{host}:{port}"
    if ":" in host:  # IPv6 literal
        netloc = f"[{host}]" + (f":{port}" if port not in (None, _DEFAULT_PORTS.get(scheme)) else "")
    kept = [seg for seg in parts.query.split("&") if seg and not _is_tracking(seg.split("=", 1)[0])]
    return urlunsplit((scheme, netloc, parts.path or "/", "&".join(kept), ""))


def is_public_ip(value: str) -> bool:
    try:
        return ipaddress.ip_address(value).is_global
    except ValueError:
        return False


def check_url(
    url: str,
    rules: Sequence[AllowRule],
    *,
    resolver: Callable[[str], Sequence[str]] | None = None,
) -> UrlDecision:
    """Decide whether ``url`` may be fetched under ``rules``.

    ``resolver`` (host -> IP strings) is optional so pure tests need no DNS; the real fetcher
    passes ``socket.getaddrinfo`` so a public-looking name resolving to a private address is
    refused too.
    """
    try:
        parts = urlsplit(url.strip())
        port = parts.port
    except ValueError:
        return UrlDecision(False, "unparseable_url")
    if parts.scheme.lower() not in {"http", "https"}:
        return UrlDecision(False, "scheme_not_allowed")
    if parts.username or parts.password:
        return UrlDecision(False, "credentials_in_url")
    host = (parts.hostname or "").lower()
    if not host:
        return UrlDecision(False, "no_host")
    if port not in (None, 80, 443):
        return UrlDecision(False, "port_not_allowed")

    try:
        ipaddress.ip_address(host)
        is_literal = True
    except ValueError:
        is_literal = False
    if is_literal:
        if not is_public_ip(host):
            return UrlDecision(False, "private_address")
    else:
        if host in _BLOCKED_NAMES or host.endswith(_BLOCKED_SUFFIXES) or "." not in host:
            return UrlDecision(False, "private_hostname")
        try:
            host.encode("idna")
        except UnicodeError:
            return UrlDecision(False, "bad_hostname")

    path = parts.path or "/"
    if not any(rule.matches(host, path) for rule in rules):
        return UrlDecision(False, "outside_allowlist")

    if resolver is not None and not is_literal:
        try:
            addresses = list(resolver(host))
        except OSError:
            return UrlDecision(False, "dns_failure")
        if not addresses or not all(is_public_ip(a) for a in addresses):
            return UrlDecision(False, "dns_private_address")

    return UrlDecision(True, "ok", canonicalize_url(url))
