"""In-memory :class:`Repository` with real transaction semantics (copy-on-begin, restore on error).

Used by tests and offline dry runs. It is *not* a substitute for ``SqlRepository`` when judging
SQL behaviour (constraints, migrations); it exists so planning, idempotency, rollback and
export logic can be exercised without a database.
"""

from __future__ import annotations

import copy
from collections.abc import Iterator, Sequence
from contextlib import contextmanager

from navigator.ingestion.planner import PlanItem


class MemoryRepository:
    def __init__(self) -> None:
        self.records: dict[str, tuple[dict, int]] = {}
        self.revisions: list[dict] = []
        self.runs: list[dict] = []
        self.sources: dict[str, dict] = {}
        self.fail_on: set[str] = set()  # ids whose write should raise (rollback tests)

    def ensure_sources(self, sources: Sequence[dict]) -> None:
        for source in sources:
            self.sources[source["source_id"]] = dict(source)

    def load_existing(self, ids: Sequence[str]) -> dict[str, tuple[dict, int]]:
        return {i: copy.deepcopy(self.records[i]) for i in ids if i in self.records}

    @contextmanager
    def transaction(self) -> Iterator[None]:
        saved = (copy.deepcopy(self.records), copy.deepcopy(self.revisions))
        try:
            yield
        except BaseException:
            self.records, self.revisions = saved
            raise

    def apply_item(self, item: PlanItem, run_id: str, now_iso: str) -> None:
        if item.id in self.fail_on:
            raise RuntimeError(f"simulated database failure while writing {item.id}")
        if item.record is None:
            return
        if item.action == "updated":
            self.revisions.append({"opportunity_id": item.id, "version": item.version, "run_id": run_id,
                                   "changed_at": now_iso, "diff": copy.deepcopy(item.diff)})
        self.records[item.id] = (copy.deepcopy(item.record), item.version)

    def record_run(self, run: dict) -> None:
        self.runs.append(copy.deepcopy(run))

    def get_record(self, record_id: str, *, published_only: bool = True, with_meta: bool = False) -> dict | None:
        stored = self.records.get(record_id)
        if stored is None or (published_only and stored[0]["publication_status"] != "published"):
            return None
        return copy.deepcopy(stored[0])

    def latest_run_context(self, mode: str) -> dict:
        for run in reversed(self.runs):
            if run.get("mode") == mode and "context" in run:
                return copy.deepcopy(run["context"])
        return {}

    def list_records(self, *, published_only: bool, is_demo: bool, with_meta: bool = False) -> list[dict]:
        out = []
        for record, _ in self.records.values():
            if record["is_demo"] != is_demo:
                continue
            if published_only and record["publication_status"] != "published":
                continue
            out.append(copy.deepcopy(record))
        return sorted(out, key=lambda r: r["id"])
