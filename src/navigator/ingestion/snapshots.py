"""Content-addressed, never-overwritten snapshot storage.

Raw files live at ``raw/<sha[:2]>/<sha>.<ext>`` (named after the SHA-256 of their bytes, so a
changed page becomes a *new* file and old evidence stays valid). Extracted text lives at
``text/<sha[:2]>/<raw_sha>.<extractor>-<version>.txt``. All paths handed out are relative to
the artifact root, with forward slashes, so records stay portable across operating systems.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from navigator.core.evidence import safe_join, sha256_bytes, sha256_file
from navigator.core.ids import snapshot_id_for
from navigator.ingestion.fsutil import atomic_write_bytes

_EXT = {"text/html": "html", "application/pdf": "pdf", "application/json": "json", "text/plain": "txt"}


class SnapshotIntegrityError(RuntimeError):
    """A stored snapshot no longer matches its content hash."""


@dataclass(frozen=True)
class StoredRaw:
    snapshot_id: str
    raw_sha256: str
    raw_path: str
    created: bool  # False when identical content was already stored


@dataclass(frozen=True)
class StoredText:
    text_path: str
    text_sha256: str


class SnapshotStore:
    def __init__(self, root: Path) -> None:
        self.root = root

    @staticmethod
    def _ext(media_type: str) -> str:
        base = media_type.split(";")[0].strip().lower()
        return _EXT.get(base, "bin")

    def save_raw(self, data: bytes, media_type: str) -> StoredRaw:
        digest = sha256_bytes(data)
        rel = f"raw/{digest[:2]}/{digest}.{self._ext(media_type)}"
        target = safe_join(self.root, rel)
        created = False
        if target.exists():
            if sha256_file(target) != digest:
                raise SnapshotIntegrityError(f"stored snapshot {rel} does not match its hash")
        else:
            atomic_write_bytes(target, data)
            created = True
        return StoredRaw(snapshot_id_for(digest), digest, rel, created)

    def save_text(self, raw_sha256: str, text: str, extractor: str, version: str) -> StoredText:
        data = text.encode("utf-8")
        rel = f"text/{raw_sha256[:2]}/{raw_sha256}.{extractor}-{version}.txt"
        target = safe_join(self.root, rel)
        if not target.exists() or target.read_bytes() != data:
            atomic_write_bytes(target, data)  # derived data: safe to regenerate
        return StoredText(rel, sha256_bytes(data))

    def read_raw(self, rel: str) -> bytes:
        return safe_join(self.root, rel).read_bytes()

    def read_text(self, rel: str) -> str:
        return safe_join(self.root, rel).read_text(encoding="utf-8")

    def verify_raw(self, rel: str, expected_sha256: str) -> bool:
        path = safe_join(self.root, rel)
        return path.is_file() and sha256_file(path) == expected_sha256
