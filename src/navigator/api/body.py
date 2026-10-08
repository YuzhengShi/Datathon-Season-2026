"""The one error shape used by every failing response (kept free of web-framework imports)."""

from __future__ import annotations

from typing import Any


def error_body(code: str, message: str, mode: str, details: list[dict[str, Any]] | None = None) -> dict:
    body: dict[str, Any] = {"code": code, "message": message}
    if details is not None:
        body["details"] = details
    return {"error": body, "data_mode": mode}
