"""Commands of the application layer. The core CLI mounts them as ``navigator app <command>``."""

import json
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from .config import Settings
from .db import Opportunity, engine_for, import_demo, upgrade
from .publish import DEFAULT_DATASET, DEMO_DATASET, FRONTEND_DATASET, publish


def upgrade_read_model(settings: Settings) -> dict:
    upgrade(settings)
    return {"data_mode": settings.data_mode, "migration": "complete"}


def init_demo(settings: Settings, dataset: Path | None = None) -> dict:
    if settings.data_mode != "demo":
        raise ValueError("init-demo requires --mode demo")
    upgrade(settings)
    return {"data_mode": "demo", **import_demo(settings, dataset or DEMO_DATASET)}


def publish_dataset(settings: Settings, dataset: Path | None = None, write_frontend: bool = True) -> dict:
    """Canonical dataset -> live read model (and the static file in dist/ unless ``write_frontend`` is false)."""
    if settings.data_mode != "live":
        raise ValueError("publish requires --mode live")
    upgrade(settings)
    return publish(settings, dataset or DEFAULT_DATASET, write_frontend=write_frontend)


def status(settings: Settings) -> dict:
    """Where the read model is, what it holds, and whether the static file in dist/ agrees with the mode."""
    info: dict = {
        "data_mode": settings.data_mode,
        "read_model": settings.selected_url.split("///", 1)[-1],
        "llm_ready": settings.llm_ready,
        "llm_model": settings.openai_model or None,
        "llm_endpoint": settings.openai_base_url or "OpenAI (default)",
    }
    engine = engine_for(settings)
    try:
        with Session(engine) as session:
            info["records"] = session.scalar(
                select(func.count()).select_from(Opportunity).where(Opportunity.data_mode == settings.data_mode)
            )
    except SQLAlchemyError:
        info["records"] = None
        info["hint"] = "the read model is not initialised: run `navigator app publish` (live) or `app init-demo`"
    finally:
        engine.dispose()
    try:
        static_mode = json.loads(FRONTEND_DATASET.read_text(encoding="utf-8")).get("data_mode")
    except (OSError, ValueError):
        static_mode = None
    info["static_file_mode"] = static_mode
    info["static_file_matches_mode"] = static_mode == settings.data_mode
    return info
