"""Atomic file writes and JSONL helpers shared by every pipeline stage."""

from __future__ import annotations

import contextlib
import json
import os
import tempfile
from collections.abc import Iterable, Iterator
from pathlib import Path
from typing import Any


def atomic_write_bytes(path: Path, data: bytes) -> None:
    """Write ``data`` to a temp file in the same directory, fsync, then ``os.replace``."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, path)
    except BaseException:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(tmp_name)
        raise


def atomic_write_text(path: Path, text: str) -> None:
    atomic_write_bytes(path, text.encode("utf-8"))


def write_json(path: Path, value: Any) -> None:
    atomic_write_text(path, json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n")


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_jsonl(path: Path, rows: Iterable[Any]) -> int:
    lines = [json.dumps(r, sort_keys=True, ensure_ascii=False, separators=(",", ":")) for r in rows]
    atomic_write_text(path, "".join(line + "\n" for line in lines))
    return len(lines)


def iter_jsonl(path: Path) -> Iterator[Any]:
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                yield json.loads(line)
