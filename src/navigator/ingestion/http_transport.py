"""The real HTTP transport (httpx). Kept tiny: all policy lives in :mod:`navigator.ingestion.fetcher`."""

from __future__ import annotations

import socket
from collections.abc import Mapping, Sequence

import httpx

from navigator.ingestion.fetcher import HttpResponse, TransportError


class HttpxTransport:
    """One GET per call, no redirects followed, streamed with a hard byte cap."""

    def __init__(self, client: httpx.Client | None = None) -> None:
        self._client = client or httpx.Client(follow_redirects=False)

    def get(self, url: str, headers: Mapping[str, str], timeout: float, max_bytes: int) -> HttpResponse:
        try:
            with self._client.stream("GET", url, headers=dict(headers), timeout=timeout,
                                     follow_redirects=False) as response:
                declared = response.headers.get("content-length")
                if declared and declared.isdigit() and int(declared) > max_bytes:
                    raise TransportError("too_large", f"content-length {declared} exceeds limit")
                chunks, total = [], 0
                for chunk in response.iter_bytes():
                    total += len(chunk)
                    if total > max_bytes:
                        raise TransportError("too_large", "body exceeds limit")
                    chunks.append(chunk)
                return HttpResponse(response.status_code, {k.lower(): v for k, v in response.headers.items()},
                                    b"".join(chunks), str(response.url))
        except httpx.TimeoutException as exc:
            raise TransportError("timeout", str(exc)) from exc
        except httpx.ConnectError as exc:
            raise TransportError("connect", str(exc)) from exc
        except httpx.HTTPError as exc:
            raise TransportError("protocol", str(exc)) from exc

    def close(self) -> None:
        self._client.close()


def system_resolver(host: str) -> Sequence[str]:
    """DNS answers for SSRF checks (a public-looking name must not resolve to a private address)."""
    return sorted({info[4][0] for info in socket.getaddrinfo(host, None)})
