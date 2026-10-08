"""One error shape for every failure: ``{"error": {code, message, details?}, "data_mode": ...}``.

Validation errors list *where* a request is wrong (``loc``/``type``/``msg``) but never echo the
submitted values, so a sensitive profile cannot leak through an error response.
"""

from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from navigator.api.body import error_body

logger = logging.getLogger("navigator.api")


def install_error_handlers(app: FastAPI, mode: str) -> None:
    @app.exception_handler(StarletteHTTPException)
    async def _http_error(_request: Request, exc: StarletteHTTPException) -> JSONResponse:
        message = exc.detail if isinstance(exc.detail, str) else "request failed"
        return JSONResponse(status_code=exc.status_code, content=error_body(f"http_{exc.status_code}", message, mode))

    @app.exception_handler(RequestValidationError)
    async def _validation_error(_request: Request, exc: RequestValidationError) -> JSONResponse:
        details = [
            {"loc": [str(part) for part in err.get("loc", ())], "type": err.get("type"), "msg": err.get("msg")}
            for err in exc.errors()
        ]  # deliberately drops err["input"] and err["ctx"]
        return JSONResponse(
            status_code=422, content=error_body("validation_error", "request validation failed", mode, details)
        )

    @app.exception_handler(Exception)
    async def _unhandled(_request: Request, exc: Exception) -> JSONResponse:
        logger.error("unhandled error of type %s", type(exc).__name__)  # type only: never the message or body
        return JSONResponse(status_code=500, content=error_body("internal_error", "internal server error", mode))
