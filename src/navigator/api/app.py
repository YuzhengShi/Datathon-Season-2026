"""FastAPI application factory (no import-time side effects: nothing connects until it is called)."""

from __future__ import annotations

import mimetypes
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware

from navigator import __version__
from navigator.api.errors import install_error_handlers
from navigator.api.reference_routes import router as reference_router
from navigator.api.routes import router
from navigator.config import Runtime, load_runtime
from navigator.db import make_engine, make_session_factory
from navigator.logging_setup import configure_logging
from navigator.reference import load_institutions

DESCRIPTION = (
    "Read-only API over sourced, evidence-backed funding opportunities for First Nations, Inuit and Métis "
    "students in Canada. `/match` returns explainable rule outcomes - never award probabilities. "
    "Every response carries `data_mode`; `demo` responses describe SYNTHETIC data only. "
    "The `/api/*` routes are the application layer used by the site (search, statistics, AI search)."
)


def create_app(runtime: Runtime | None = None, app_settings=None) -> FastAPI:
    """One app for everything: the core API, the application layer's ``/api/*`` routes and both web apps.

    ``app_settings`` (``navigator.app.config.Settings``) carries the AI settings; the CLI passes it. Callers that
    hand in only a ``Runtime`` (tests) get an application layer with the AI off and no ``.env`` read.
    """
    production = runtime is None
    rt = runtime or load_runtime()
    configure_logging(rt.log_level)
    engine = make_engine(rt.database_url)
    app = FastAPI(
        title="Indigenous Student Funding Navigator API",
        version=__version__,
        description=DESCRIPTION,
        docs_url="/docs",
        redoc_url=None,
    )
    app.state.runtime = rt
    app.state.engine = engine
    app.state.session_factory = make_session_factory(engine)
    app.state.institutions = load_institutions(rt.reference_dir / "institutions.yaml")
    install_error_handlers(app, rt.mode)
    if rt.cors_origins:  # disabled unless explicit origins are configured; never wildcard + credentials
        app.add_middleware(
            CORSMiddleware,
            allow_origins=list(rt.cors_origins),
            allow_credentials=False,
            allow_methods=["GET", "POST"],
            allow_headers=["Content-Type"],
        )
    app.include_router(router)
    app.include_router(reference_router)
    _install_application_layer(app, rt, app_settings, production)
    _mount_frontend(app)
    return app


def _install_application_layer(app: FastAPI, rt: Runtime, app_settings, production: bool) -> None:
    """The ``/api/*`` routes and the dataset the site loads. Mode and data folder always come from the core."""
    from navigator.app.config import Settings
    from navigator.app.main import install

    if app_settings is None:
        app_settings = Settings() if production else Settings(_env_file=None, llm_enabled=False)
    settings = app_settings.model_copy(update={"data_mode": rt.mode, "data_dir": str(rt.data_dir)})
    app.state.app_engine = install(app, settings)


ROOT_DIR = Path(__file__).resolve().parents[3]
FRONTEND_DIR = ROOT_DIR / "frontend"  # the questionnaire app, served at /app/
SITE_DIR = ROOT_DIR / "dist"  # the site (Explore, Statistics, AI search), served at /
CSP = (
    "default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; connect-src 'self'; "
    "base-uri 'none'; form-action 'none'; frame-ancestors 'none'; object-src 'none'"
)


def _mount_frontend(app: FastAPI) -> None:
    """Serve both web apps from the same origin as the API: no CORS, no build step, nothing to deploy twice."""
    for suffix, media in (
        (".js", "text/javascript"),
        (".mjs", "text/javascript"),
        (".css", "text/css"),
        (".svg", "image/svg+xml"),
    ):
        mimetypes.add_type(
            media, suffix
        )  # the Windows registry can map .js to text/plain, which browsers refuse for modules

    @app.middleware("http")
    async def frontend_headers(request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        if request.url.path == "/app" or request.url.path.startswith("/app/"):
            response.headers["Content-Security-Policy"] = CSP
            response.headers["Cache-Control"] = "no-cache"
        return response

    if FRONTEND_DIR.is_dir():
        app.mount("/app", StaticFiles(directory=FRONTEND_DIR, html=True), name="app")
    if SITE_DIR.is_dir():  # last: a mount at "/" answers every path no route above has taken
        app.mount("/", StaticFiles(directory=SITE_DIR, html=True), name="site")
    elif FRONTEND_DIR.is_dir():

        @app.get("/", include_in_schema=False)
        def home() -> RedirectResponse:
            return RedirectResponse("/app/")
