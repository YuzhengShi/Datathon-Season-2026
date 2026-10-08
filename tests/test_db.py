"""Database layer: Alembic migration, SQLite constraints, and parity with the in-memory repository.

Needs the pinned stack (``python -m pip install -r requirements.lock``). Written without being able to
run SQLAlchemy at authoring time: if a test here fails, read it as a real finding, not a flaky test."""

import gc
import tempfile
import unittest
from pathlib import Path

from navigator.config import derive_runtime
from navigator.demo.dataset import DEMO_SOURCES
from navigator.ingestion.memory_repo import MemoryRepository
from navigator.services.pipeline import run_demo_pipeline
from tests.support import AS_OF, DemoEnv, isolated_runtime, requires_web_stack

NOW = "2026-10-07T12:00:00Z"


@requires_web_stack
class MigrationTests(unittest.TestCase):
    def setUp(self):
        from navigator.db import make_engine, upgrade_database

        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.url = f"sqlite:///{(Path(self.tmp.name) / 'nested' / 'navigator.db').as_posix()}"  # parent folder does not exist yet
        upgrade_database(self.url)
        self.engine = make_engine(self.url)

    def tearDown(self):
        self.engine.dispose()
        gc.collect()
        self.tmp.cleanup()

    def test_schema_is_created_by_alembic_and_is_current(self):
        from sqlalchemy import inspect

        from navigator.db import EXPECTED_REVISION, migration_state

        tables = set(inspect(self.engine).get_table_names())
        self.assertTrue(
            {
                "sources",
                "runs",
                "snapshots",
                "fetches",
                "opportunities",
                "application_cycles",
                "application_groups",
                "application_group_members",
                "evidence",
                "opportunity_revisions",
                "alembic_version",
            }
            <= tables
        )
        state = migration_state(self.engine)
        self.assertEqual((state["connected"], state["current"], state["up_to_date"]), (True, EXPECTED_REVISION, True))

    def test_upgrade_is_idempotent(self):
        from navigator.db import migration_state, upgrade_database

        upgrade_database(self.url)
        self.assertTrue(migration_state(self.engine)["up_to_date"])

    def test_models_and_migration_describe_the_same_schema(self):
        from alembic.autogenerate import compare_metadata
        from alembic.migration import MigrationContext

        from navigator.models import Base

        with self.engine.connect() as connection:
            diff = compare_metadata(MigrationContext.configure(connection), Base.metadata)
        self.assertEqual(diff, [])

    def test_foreign_keys_and_uniqueness_are_enforced(self):
        from sqlalchemy.exc import IntegrityError
        from sqlalchemy.orm import Session

        from navigator.models import Evidence, Opportunity, Source

        with Session(self.engine) as session:
            session.add(
                Evidence(
                    opportunity_id="nope",
                    evidence_id="e",
                    position=0,
                    field_path="/x",
                    source_id="s",
                    snapshot_id="snap",
                    source_url="u",
                    quote="q",
                    locator={},
                    raw_sha256="0" * 64,
                    text_sha256="0" * 64,
                )
            )
            with self.assertRaises(IntegrityError):
                session.commit()
            session.rollback()
            session.add(
                Source(
                    source_id="s1",
                    url="https://x.example/",
                    provider_id="p",
                    provider_name="P",
                    role="r",
                    parser="x",
                    language="en",
                    access_status="unreviewed",
                    created_at=NOW,
                    updated_at=NOW,
                )
            )
            session.commit()
        common = dict(
            schema_version="1.0",
            title="t",
            opportunity_type="award",
            provider_id="p",
            provider_name="P",
            official_url="https://x.example/",
            summary="s",
            provider={},
            application={},
            required_documents=[],
            source_refs=[],
            review_status="pending",
            publication_status="draft",
            extraction_method="curated",
            last_fetched_at=NOW,
            content_fingerprint="sha256:" + "0" * 64,
            is_demo=False,
            version=1,
            created_at=NOW,
            updated_at=NOW,
        )
        with Session(self.engine) as session:
            session.add(Opportunity(id="a", source_record_key="k", **common))
            session.commit()
            session.add(Opportunity(id="b", source_record_key="k", **common))  # same source_record_key
            with self.assertRaises(IntegrityError):
                session.commit()
            session.rollback()
            session.add(Opportunity(id="c", source_record_key="k2", **{**common, "opportunity_type": "scholarship"}))
            with self.assertRaises(IntegrityError):  # CHECK constraint on the type vocabulary
                session.commit()


@requires_web_stack
class RepositoryParityTests(unittest.TestCase):
    """The SQL repository must round-trip exactly what the in-memory repository does."""

    def setUp(self):
        from navigator.db import make_engine, make_session_factory, upgrade_database
        from navigator.models.repository import SqlRepository

        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.rt = isolated_runtime(self.tmp.name, "demo")
        upgrade_database(self.rt.database_url)
        self.engine = make_engine(self.rt.database_url)
        self.repo = SqlRepository(make_session_factory(self.engine), self.engine)

    def tearDown(self):
        self.engine.dispose()
        gc.collect()
        self.tmp.cleanup()

    def test_demo_pipeline_on_sqlite_matches_the_memory_repository(self):
        sql = run_demo_pipeline(self.repo, self.rt, as_of=AS_OF)
        self.assertEqual((sql["exit_code"], sql["import"]["counts"]["created"]), (0, 25))
        with tempfile.TemporaryDirectory() as other:
            memory = MemoryRepository()
            run_demo_pipeline(memory, derive_runtime({"DATA_DIR": other}, "demo"), as_of=AS_OF)
            self.assertEqual(
                self.repo.list_records(published_only=False, is_demo=True),
                memory.list_records(published_only=False, is_demo=True),
            )
        again = run_demo_pipeline(self.repo, self.rt, as_of=AS_OF)
        self.assertEqual(
            again["import"]["counts"], {"created": 0, "updated": 0, "unchanged": 25, "rejected": 0, "pending_review": 0}
        )

    def test_live_and_demo_data_never_share_rows(self):
        run_demo_pipeline(self.repo, self.rt, as_of=AS_OF)
        self.assertEqual(self.repo.list_records(published_only=False, is_demo=False), [])
        live_rt = isolated_runtime(self.tmp.name, "live")
        self.assertNotEqual(live_rt.database_url, self.rt.database_url)
        self.assertFalse((Path(self.tmp.name) / "navigator.db").exists())  # the live database file was never created

    def test_failed_batch_leaves_no_rows_behind(self):
        from navigator.ingestion.importer import import_records
        from navigator.ingestion.validation import ValidationContext, validate_lines
        import json

        env = DemoEnv.get()
        self.repo.ensure_sources(DEMO_SOURCES)
        records = [dict(r, last_verified_at=NOW) for r in env.all_records()]
        validation = validate_lines(
            [(i, json.dumps(r)) for i, r in enumerate(records, 1)],
            ValidationContext(artifact_root=env.root, expected_mode="demo", now=AS_OF),
        )
        original = type(self.repo).apply_item

        def explode(repo, item, run_id, now_iso):
            if item.id == "demo_funding_channel":
                raise RuntimeError("simulated failure")
            return original(repo, item, run_id, now_iso)

        type(self.repo).apply_item = explode
        try:
            report = import_records(self.repo, validation, mode="demo", run_id="r", now_iso=NOW)
        finally:
            type(self.repo).apply_item = original
        self.assertEqual(report.status, "failed")
        self.assertEqual(self.repo.list_records(published_only=False, is_demo=True), [])

    def test_children_cascade_with_the_opportunity(self):
        from sqlalchemy import func, select, text
        from sqlalchemy.orm import Session

        from navigator.models import ApplicationCycle, Evidence

        run_demo_pipeline(self.repo, self.rt, as_of=AS_OF)
        with Session(self.engine) as session:
            session.execute(text("DELETE FROM opportunities WHERE id = 'demo_multi_cycle_award'"))
            session.commit()
            self.assertEqual(
                session.scalar(
                    select(func.count())
                    .select_from(ApplicationCycle)
                    .where(ApplicationCycle.opportunity_id == "demo_multi_cycle_award")
                ),
                0,
            )
            self.assertEqual(
                session.scalar(
                    select(func.count())
                    .select_from(Evidence)
                    .where(Evidence.opportunity_id == "demo_multi_cycle_award")
                ),
                0,
            )


if __name__ == "__main__":
    unittest.main()
