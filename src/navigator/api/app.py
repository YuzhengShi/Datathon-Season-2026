"""FastAPI application factory (no import-time side effects: nothing connects until it is called)."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from navigator import __version__
from navigator.api.errors import install_error_handlers
from navigator.api.routes import router
from navigator.config import Runtime, load_runtime
from navigator.db import make_engine, make_session_factory
from navigator.logging_setup import configure_logging
from navigator.reference import load_institutions

DESCRIPTION = (
    "Read-only API over sourced, evidence-backed funding opportunities for First Nations, Inuit and Métis "
    "students in Canada. `/match` returns explainable rule outcomes - never award probabilities. "
    "Every response carries `data_mode`; `demo` responses describe SYNTHETIC data only."
)


def create_app(runtime: Runtime | None = None) -> FastAPI:
    rt = runtime or load_runtime()
    configure_logging(rt.log_level)
    engine = make_engine(rt.database_url)
    app = FastAPI(title="Indigenous Student Funding Navigator API", version=__version__, description=DESCRIPTION,
                  docs_url="/docs", redoc_url=None)
    app.state.runtime = rt
    app.state.engine = engine
    app.state.session_factory = make_session_factory(engine)
    app.state.institutions = load_institutions(rt.reference_dir / "institutions.yaml")
    install_error_handlers(app, rt.mode)
    if rt.cors_origins:  # disabled unless explicit origins are configured; never wildcard + credentials
        app.add_middleware(CORSMiddleware, allow_origins=list(rt.cors_origins), allow_credentials=False,
                           allow_methods=["GET", "POST"], allow_headers=["Content-Type"])
    app.include_router(router)
    return app
