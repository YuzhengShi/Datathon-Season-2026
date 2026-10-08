"""ASGI entry point: ``uvicorn navigator.main:app_factory --factory`` (``python -m navigator.cli serve`` wraps this)."""

from __future__ import annotations

from fastapi import FastAPI

from navigator.api.app import create_app


def app_factory() -> FastAPI:
    return create_app()
