"""Run manifest: what a pipeline run did, written atomically after every step so a dropped
session can resume. Never records student data or secrets."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from navigator.core.evidence import sha256_file
from navigator.core.timeutil import format_utc
from navigator.ingestion.fsutil import read_json, write_json


class RunManifest:
    def __init__(self, path: Path, run_id: str, kind: str, mode: str, params: dict, started_at: datetime) -> None:
        self.path = path
        self.data: dict[str, Any] = {
            "run_id": run_id,
            "kind": kind,
            "data_mode": mode,
            "params": params,
            "started_at": format_utc(started_at),
            "finished_at": None,
            "status": "running",
            "completed_steps": [],
            "sources": {},
            "counts": {},
            "artifacts": {},
            "failures": [],
            "pending_verification": [],
            "notes": [],
        }

    @classmethod
    def load(cls, path: Path) -> dict:
        return read_json(path)

    def save(self) -> None:
        write_json(self.path, self.data)

    def step_done(self, name: str, **info: Any) -> None:
        self.data["completed_steps"].append({"step": name, **info})
        self.save()

    def source_status(self, source_id: str, **info: Any) -> None:
        self.data["sources"].setdefault(source_id, {}).update(info)

    def count(self, **counts: Any) -> None:
        self.data["counts"].update(counts)

    def artifact(self, label: str, path: Path, root: Path) -> None:
        rel = path.relative_to(root).as_posix() if path.is_absolute() else path.as_posix()
        entry: dict[str, Any] = {"path": rel}
        if path.is_file():
            entry["sha256"] = sha256_file(path)
        self.data["artifacts"][label] = entry

    def failure(self, where: str, reason: str) -> None:
        self.data["failures"].append({"where": where, "reason": reason})

    def pending(self, what: str, reason: str) -> None:
        self.data["pending_verification"].append({"item": what, "reason": reason})

    def note(self, text: str) -> None:
        self.data["notes"].append(text)

    def finish(self, status: str, at: datetime) -> None:
        self.data["status"] = status
        self.data["finished_at"] = format_utc(at)
        self.save()
