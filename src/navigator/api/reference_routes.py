"""Reference data the web app needs to ask its questions (read-only, public)."""

from __future__ import annotations

from fastapi import APIRouter, Request

from navigator.schemas.api import InstitutionList

router = APIRouter()


@router.get(
    "/reference/institutions",
    response_model=InstitutionList,
    tags=["reference"],
    summary="Schools a profile can name (controlled ids); live data lists real schools, demo data only the synthetic one",
)
def institutions(request: Request) -> dict:
    mode = request.app.state.runtime.mode
    items = [
        {"id": rec["id"], "name": rec["name"], "province": rec.get("province"), "aliases": list(rec.get("aliases", []))}
        for rec in request.app.state.institutions.records.values()
        if bool(rec.get("is_demo")) == (mode == "demo")
    ]
    items.sort(key=lambda item: item["name"].lower())
    return {"data_mode": mode, "institutions": items}
