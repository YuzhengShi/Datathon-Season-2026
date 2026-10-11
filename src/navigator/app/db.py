"""The read model: published opportunity records, one mode per database file."""

import json
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import JSON, String, create_engine, event, select
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column

from .config import REPO_ROOT, Settings

MIGRATIONS = REPO_ROOT / "migrations_app"


class Base(DeclarativeBase):
    pass


class Opportunity(Base):
    __tablename__ = "opportunities"

    data_mode: Mapped[str] = mapped_column(String(8), primary_key=True)
    id: Mapped[str] = mapped_column(String(100), primary_key=True)
    title: Mapped[str] = mapped_column(String(300), index=True)
    publication_status: Mapped[str] = mapped_column(String(16), index=True)
    body: Mapped[dict] = mapped_column(JSON)


def engine_for(settings: Settings):
    url = settings.selected_url
    if url.startswith("sqlite:///") and not url.endswith(":memory:"):
        Path(url.removeprefix("sqlite:///")).parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(url, connect_args={"check_same_thread": False} if url.startswith("sqlite") else {})
    if url.startswith("sqlite"):

        @event.listens_for(engine, "connect")
        def sqlite_foreign_keys(connection, _):
            connection.execute("PRAGMA foreign_keys=ON")

    return engine


def upgrade(settings: Settings):
    """Apply the read model's own migrations (``migrations_app``) to the database of the selected mode."""
    cfg = Config()
    cfg.set_main_option("script_location", str(MIGRATIONS))
    cfg.set_main_option("sqlalchemy.url", settings.selected_url.replace("%", "%%"))
    engine_for(settings).dispose()
    command.upgrade(cfg, "head")


def import_demo(settings: Settings, dataset: Path):
    if settings.data_mode != "demo":
        raise ValueError("Illustrative frontend records cannot be imported into live mode")
    payload = json.loads(dataset.read_text(encoding="utf-8"))
    if payload["data_mode"] != "demo" or not all(x.get("is_demo") for x in payload["records"]):
        raise ValueError("Demo import requires explicit mode and record labels")
    ids = [x["id"] for x in payload["records"]]
    if len(set(ids)) != len(ids):
        raise ValueError("Duplicate IDs")
    engine = engine_for(settings)
    counts = {"created": 0, "updated": 0, "unchanged": 0}
    try:
        with Session(engine) as session, session.begin():
            for body in payload["records"]:
                existing = session.get(Opportunity, ("demo", body["id"]))
                if existing and existing.body == body:
                    counts["unchanged"] += 1
                elif existing:
                    existing.title, existing.body = body["title"], body
                    counts["updated"] += 1
                else:
                    session.add(
                        Opportunity(
                            data_mode="demo",
                            id=body["id"],
                            title=body["title"],
                            publication_status="published",
                            body=body,
                        )
                    )
                    counts["created"] += 1
    finally:
        engine.dispose()
    return counts


class Repository:
    def __init__(self, engine, mode: str):
        self.engine, self.mode = engine, mode

    def all(self) -> list[dict]:
        with Session(self.engine) as session:
            statement = (
                select(Opportunity)
                .where(
                    Opportunity.data_mode == self.mode,
                    Opportunity.publication_status == "published",
                )
                .order_by(Opportunity.id)
            )
            # This prototype is bounded. Production aggregation belongs in SQL views.
            rows = session.scalars(statement.limit(5001)).all()
            if len(rows) > 5000:
                raise RuntimeError("Dataset exceeds the prototype's query bound")
            return [row.body for row in rows if bool(row.body.get("is_demo")) == (self.mode == "demo")]
