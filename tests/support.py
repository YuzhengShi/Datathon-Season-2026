"""Shared test helpers (stdlib only so the core suite runs without the web/database stack)."""

from __future__ import annotations

import copy
import importlib.util
import shutil
import tempfile
import unittest
import weakref
from collections.abc import Mapping
from pathlib import Path

from navigator.config import derive_runtime
from navigator.core.fingerprint import compute_fingerprint
from navigator.core.timeutil import parse_as_of
from navigator.demo.dataset import build_demo_artifacts, build_demo_records
from navigator.ingestion.fetcher import HttpResponse, TransportError

AS_OF = parse_as_of("2026-10-07")

STACK_MODULES = ("fastapi", "sqlalchemy", "alembic", "pydantic", "pydantic_settings", "httpx", "typer", "uvicorn")
MISSING_STACK = [m for m in STACK_MODULES if importlib.util.find_spec(m) is None]
HAS_WEB_STACK = not MISSING_STACK


def requires_web_stack(obj):
    """These tests need the pinned web/database stack; they are skipped (loudly) where it is not installed."""
    return unittest.skipIf(bool(MISSING_STACK), f"not installed: {', '.join(MISSING_STACK)}")(obj)


class DemoEnv:
    """A temp artifact root holding the synthetic snapshots plus the demo records built on them."""

    _shared: "DemoEnv | None" = None

    def __init__(self) -> None:
        self.root = Path(tempfile.mkdtemp(prefix="demo-env-"))
        weakref.finalize(self, shutil.rmtree, str(self.root), True)
        self.art = build_demo_artifacts(self.root, AS_OF)
        self.records = build_demo_records(self.art)

    @classmethod
    def get(cls) -> "DemoEnv":
        if cls._shared is None:
            cls._shared = cls()
        return cls._shared

    def record(self, rid: str) -> dict:
        return copy.deepcopy(next(r for r in self.records if r["id"] == rid))

    def all_records(self) -> list[dict]:
        return copy.deepcopy(self.records)

    def copy_root(self) -> Path:
        """A private copy of the artifact tree for tests that corrupt files."""
        target = Path(tempfile.mkdtemp())
        shutil.copytree(self.root, target, dirs_exist_ok=True)
        return target


def isolated_runtime(tmp: str, mode: str, **extra: str):
    """A runtime whose databases and artefacts all live inside ``tmp``.

    ``DATA_DIR`` only moves artefacts; the default ``sqlite:///./data/...`` URLs are relative to the working
    directory, so tests that skipped this shared one database file (and failed on the second run).
    """
    root = Path(tmp).as_posix()
    raw = {
        "DATA_DIR": tmp,
        "DATABASE_URL": f"sqlite:///{root}/navigator.db",
        "DEMO_DATABASE_URL": f"sqlite:///{root}/demo/navigator.db",
        **extra,
    }
    return derive_runtime(raw, mode)


def with_conflict(record: dict, field_path: str) -> dict:
    """A copy of ``record`` carrying a conflict whose two statements are copies of two different real quotes."""
    out = copy.deepcopy(record)
    picked: list[dict] = []
    for ev in out["evidence"]:
        if ev["quote"] not in {p["quote"] for p in picked}:
            picked.append(ev)
        if len(picked) == 2:
            break
    cited = []
    for n, ev in enumerate(picked):
        clone = copy.deepcopy(ev)
        clone["id"], clone["field_path"] = f"ev_conflict_{n}", "/conflicts/0"
        cited.append(clone)
    out["evidence"].extend(cited)
    out["conflicts"] = [
        {
            "field_path": field_path,
            "summary": "Two official statements disagree.",
            "evidence_ids": [c["id"] for c in cited],
        }
    ]
    out["review_status"], out["publication_status"], out["last_verified_at"] = "pending", "draft", None
    return refinger(out)


def refinger(record: dict) -> dict:
    record["content_fingerprint"] = compute_fingerprint(record)
    return record


class FakeTransport:
    """Scripted transport: ``script[url]`` is a response, an exception, or a list consumed in order."""

    def __init__(self, script: Mapping[str, object]) -> None:
        self.script = {k: (list(v) if isinstance(v, list) else v) for k, v in script.items()}
        self.calls: list[tuple[str, dict]] = []

    def get(self, url, headers, timeout, max_bytes):  # noqa: ANN001
        self.calls.append((url, dict(headers)))
        item = self.script[url]
        if isinstance(item, list):
            item = item.pop(0) if len(item) > 1 else item[0]
        if isinstance(item, Exception):
            raise item
        return item


def resp(status: int, body: bytes = b"", url: str = "", **headers: str) -> HttpResponse:
    return HttpResponse(status, {k.replace("_", "-"): v for k, v in headers.items()}, body, url)


__all__ = [
    "AS_OF",
    "DemoEnv",
    "FakeTransport",
    "TransportError",
    "isolated_runtime",
    "refinger",
    "requires_web_stack",
    "resp",
    "with_conflict",
]
