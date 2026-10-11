"""HTTP layer of the application layer: typed ``/api/*`` routes and the dataset the site loads.

``install`` adds these routes to an existing FastAPI app (the core's app, so one server serves everything);
``create_app`` builds a standalone app for tests and for running the layer on its own.
"""

import inspect
import uuid
from pathlib import Path

from fastapi import APIRouter, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text

from .assistant import Assistant, AssistantError
from .config import REPO_ROOT, Settings
from .db import Repository, engine_for
from .schemas import ConversationRequest, AppMatchRequest, SearchRequest, StatisticsArgs
from .services import DataService

SITE_DIR = REPO_ROOT / "dist"
READ_MODEL_REVISION = "0001_query_read_model"


def _error(code, message, status, fields=None):
    return JSONResponse(
        status_code=status,
        content={
            "error": {
                "code": code,
                "message": message,
                "fields": fields or [],
                "request_id": str(uuid.uuid4()),
            }
        },
    )


def install(app: FastAPI, settings: Settings, llm_client=None):
    """Add the application layer's routes and error handlers to ``app``. Returns the read model's engine."""
    engine = engine_for(settings)
    service = DataService(Repository(engine, settings.data_mode))
    assistant = Assistant(settings, service, llm_client)
    router = APIRouter()

    @router.get("/api/health")
    def health():
        try:
            with engine.connect() as connection:
                revision = connection.execute(text("SELECT version_num FROM alembic_version")).scalar()
            migrated = revision == READ_MODEL_REVISION
        except Exception:
            migrated = False
        return {
            "status": "ok" if migrated else "migration_required",
            "data_mode": settings.data_mode,
            "migration_ready": migrated,
            "llm_ready": settings.llm_ready,
        }

    @router.get("/data/opportunities.json", include_in_schema=False)
    def dataset():
        """The records the site loads. Served from the SAME read model and mode as ``/api/*``, so a page
        and its API can never disagree about the data mode. Static hosting uses the file in dist/ instead."""
        try:
            records = service.repository.all()
        except Exception:
            return _error("READ_MODEL_NOT_READY", "The read model is not initialised. Run: navigator app publish", 503)
        records.sort(key=lambda x: (x.get("display_order", 100), x["id"]))
        return JSONResponse(
            {"data_mode": settings.data_mode, "records": records}, headers={"Cache-Control": "no-cache"}
        )

    @router.post("/api/opportunities/search")
    def search(body: SearchRequest):
        return service.search(body.filters, body.limit, body.offset)

    @router.get("/api/opportunities/{opportunity_id}")
    def detail(opportunity_id: str):
        item = service.detail(opportunity_id)
        return (
            {"data_mode": settings.data_mode, "record": item}
            if item
            else _error("NOT_FOUND", "Opportunity not found.", 404)
        )

    @router.post("/api/match/evaluate")
    def evaluate(body: AppMatchRequest):
        return service.match(body.filters, body.profile, body.limit)

    @router.post("/api/statistics")
    def statistics(body: StatisticsArgs):
        return service.statistics(body.filters)

    @router.get("/api/facets")
    def facets():
        return service.facets()

    @router.post("/api/conversation")
    def conversation(body: ConversationRequest):
        return assistant.respond(body)

    app.include_router(router)

    previous_validation = app.exception_handlers.get(RequestValidationError)

    async def validation_error(request: Request, exc: RequestValidationError):
        # No input values, body dumps or profile information in validation responses.
        if previous_validation is not None and not request.url.path.startswith("/api/"):
            result = previous_validation(request, exc)  # the core's routes keep the core's error shape
            return await result if inspect.isawaitable(result) else result
        return _error(
            "INVALID_REQUEST",
            "Check the request fields.",
            422,
            [".".join(map(str, e["loc"])) for e in exc.errors()],
        )

    def assistant_error(_: Request, exc: AssistantError):
        return _error(exc.code, exc.message, exc.status)

    app.add_exception_handler(RequestValidationError, validation_error)
    app.add_exception_handler(AssistantError, assistant_error)
    return engine


def create_app(settings: Settings | None = None, llm_client=None):
    """A standalone app: the ``/api/*`` routes plus the site. The core's ``create_app`` is the normal entry."""
    settings = settings or Settings()
    app = FastAPI(
        title="Funding Navigator",
        version="0.5.0",
        docs_url="/api/docs",
        openapi_url="/api/openapi.json",
    )
    if settings.cors_allow_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=[x.strip() for x in settings.cors_allow_origins.split(",") if x.strip()],
            allow_methods=["GET", "POST"],
            allow_headers=["Content-Type"],
            allow_credentials=False,
        )
    app.state.engine = install(app, settings, llm_client)
    if SITE_DIR.is_dir():
        app.mount("/", StaticFiles(directory=Path(SITE_DIR), html=True), name="site")
    return app
