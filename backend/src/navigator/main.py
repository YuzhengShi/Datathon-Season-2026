import uuid
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text

from .assistant import Assistant, AssistantError
from .config import ROOT, Settings
from .db import Repository, engine_for
from .schemas import ConversationRequest, MatchRequest, SearchRequest, StatisticsArgs
from .services import DataService


def create_app(settings: Settings | None = None, llm_client=None):
    settings = settings or Settings()
    engine = engine_for(settings)
    service = DataService(Repository(engine, settings.data_mode))
    assistant = Assistant(settings, service, llm_client)
    app = FastAPI(
        title="Funding Navigator",
        version="0.5.0",
        docs_url="/api/docs",
        openapi_url="/api/openapi.json",
    )
    app.state.engine = engine
    if settings.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=[x.strip() for x in settings.cors_origins.split(",") if x.strip()],
            allow_methods=["GET", "POST"],
            allow_headers=["Content-Type"],
            allow_credentials=False,
        )

    def error(code, message, status, fields=None):
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

    @app.exception_handler(RequestValidationError)
    def validation_error(_: Request, exc: RequestValidationError):
        # No input values, body dumps or profile information in validation responses.
        return error(
            "INVALID_REQUEST",
            "Check the request fields.",
            422,
            [".".join(map(str, e["loc"])) for e in exc.errors()],
        )

    @app.exception_handler(AssistantError)
    def assistant_error(_: Request, exc: AssistantError):
        return error(exc.code, exc.message, exc.status)

    @app.get("/api/health")
    def health():
        try:
            with engine.connect() as connection:
                revision = connection.execute(
                    text("SELECT version_num FROM alembic_version")
                ).scalar()
            migrated = revision == "0001_query_read_model"
        except Exception:
            migrated = False
        return {
            "status": "ok" if migrated else "migration_required",
            "data_mode": settings.data_mode,
            "migration_ready": migrated,
            "llm_ready": settings.llm_ready,
        }

    @app.post("/api/opportunities/search")
    def search(body: SearchRequest):
        return service.search(body.filters, body.limit, body.offset)

    @app.get("/api/opportunities/{opportunity_id}")
    def detail(opportunity_id: str):
        item = service.detail(opportunity_id)
        return (
            {"data_mode": settings.data_mode, "record": item}
            if item
            else error("NOT_FOUND", "Opportunity not found.", 404)
        )

    @app.post("/api/match/evaluate")
    def evaluate(body: MatchRequest):
        return service.match(body.filters, body.profile, body.limit)

    @app.post("/api/statistics")
    def statistics(body: StatisticsArgs):
        return service.statistics(body.filters)

    @app.get("/api/facets")
    def facets():
        return service.facets()

    @app.post("/api/conversation")
    def conversation(body: ConversationRequest):
        return assistant.respond(body)

    frontend = ROOT.parent / "dist"
    if frontend.is_dir():
        app.mount("/", StaticFiles(directory=Path(frontend), html=True), name="frontend")
    return app
