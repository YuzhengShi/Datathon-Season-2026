"""Engine/session helpers and the Alembic runner. SQLite is the default; PostgreSQL works via DATABASE_URL."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import Engine, create_engine, event, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session, sessionmaker

#: Revision the running code expects (kept in sync with migrations/versions by tests/test_db.py).
EXPECTED_REVISION = "0001"
PROJECT_ROOT = Path(__file__).resolve().parents[2]


def make_engine(database_url: str, **overrides) -> Engine:
    """Create an engine; the single place engines are built (API, CLI and migrations).

    For SQLite: create the parent directory and enforce foreign keys on every connection.
    ``overrides`` go to ``create_engine`` (migrations pass ``poolclass=NullPool``).
    """
    url = make_url(database_url)
    kwargs: dict = {"future": True, "pool_pre_ping": True}
    if url.get_backend_name() == "sqlite":
        if url.database and url.database != ":memory:":
            Path(url.database).expanduser().parent.mkdir(parents=True, exist_ok=True)
        kwargs["connect_args"] = {"check_same_thread": False}
    kwargs.update(overrides)
    engine = create_engine(database_url, **kwargs)
    if url.get_backend_name() == "sqlite":

        @event.listens_for(engine, "connect")
        def _enable_foreign_keys(dbapi_connection, _record):  # noqa: ANN001
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

    return engine


def make_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, expire_on_commit=False, future=True)


@contextmanager
def session_scope(factory: sessionmaker[Session]) -> Iterator[Session]:
    session = factory()
    try:
        yield session
        session.commit()
    except BaseException:
        session.rollback()
        raise
    finally:
        session.close()


def upgrade_database(database_url: str, revision: str = "head") -> None:
    """Run Alembic migrations against ``database_url`` (never ``create_all``)."""
    from alembic import command
    from alembic.config import Config

    cfg = Config(str(PROJECT_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(PROJECT_ROOT / "migrations"))
    cfg.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))
    command.upgrade(cfg, revision)


def migration_state(engine: Engine) -> dict:
    """Connectivity and migration status for /health (never includes the connection string)."""
    state: dict = {"connected": False, "current": None, "expected": EXPECTED_REVISION, "up_to_date": False}
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
            state["connected"] = True
            try:
                row = connection.execute(text("SELECT version_num FROM alembic_version")).first()
                state["current"] = row[0] if row else None
            except Exception:  # noqa: BLE001 - table missing => not migrated yet
                state["current"] = None
    except Exception:  # noqa: BLE001
        return state
    state["up_to_date"] = state["current"] == EXPECTED_REVISION
    return state
