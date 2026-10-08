"""Alembic environment. The URL is injected by ``navigator.db.upgrade_database`` so the CLI, the
API and the migrations all use the one configuration resolver."""

from __future__ import annotations

from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool

from navigator.db import make_engine
from navigator.models import Base

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name, disable_existing_loggers=False)
target_metadata = Base.metadata


def _url() -> str:
    url = config.get_main_option("sqlalchemy.url")
    if not url:
        raise RuntimeError("no database URL: run migrations through `python -m navigator.cli db upgrade`")
    return url


def run_migrations_offline() -> None:
    context.configure(url=_url(), target_metadata=target_metadata, literal_binds=True, render_as_batch=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    # make_engine creates the SQLite folder and switches foreign keys on per connection. Nothing may be executed
    # on the connection before configure(): that would autobegin a transaction Alembic treats as external, and
    # the alembic_version row would then never be committed.
    engine = make_engine(_url(), poolclass=pool.NullPool)
    try:
        with engine.connect() as connection:
            context.configure(connection=connection, target_metadata=target_metadata, render_as_batch=True)
            with context.begin_transaction():
                context.run_migrations()
    finally:
        engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
