"""Canonical-dataset publisher: honest transform, idempotent live import, API behaviour."""

import json
from datetime import date

import pytest
from fastapi.testclient import TestClient

from navigator.config import Settings
from navigator.db import engine_for, upgrade
from navigator.publish import (
    DEFAULT_DATASET,
    build_payload,
    load_institutions,
    load_records,
    publish,
    stable_id,
)

RECORDS = load_records(DEFAULT_DATASET)
INSTITUTIONS = load_institutions()


@pytest.fixture(scope="module")
def payload():
    return build_payload(RECORDS, INSTITUTIONS, date(2026, 10, 10))


def by_title(payload, fragment):
    return next(x for x in payload["records"] if fragment in x["title"])


def test_dataset_is_published_and_unique(payload):
    assert payload["data_mode"] == "live"
    assert len(payload["records"]) == 58
    assert len({x["id"] for x in payload["records"]}) == 58
    assert all(not x["is_demo"] for x in payload["records"])
    assert all(x["url"].startswith("https://") for x in payload["records"])


def test_community_and_province_mapping(payload):
    sfu = next(x for x in payload["records"] if x["provider"] == "Simon Fraser University")
    assert sfu["community"] == ["First Nations", "Inuit", "Métis"]
    assert sfu["province"] == "British Columbia"  # institution_id eq sfu -> institutions.yaml
    assert sfu["location"] == "British Columbia"
    psssp = by_title(payload, "Post-Secondary Student Support")
    assert psssp["community"] == ["First Nations"]  # first_nations_registered predicate
    nutrien = by_title(payload, "Nutrien")
    assert nutrien["province"] == "all" and nutrien["location"] == "Across Canada"


def test_amounts_are_honest(payload):
    nutrien = by_title(payload, "Nutrien")
    assert nutrien["amount"] == 5000 and nutrien["amount_details"]["kind"] == "maximum"
    fixed = next(x for x in payload["records"] if x["amount_details"]["kind"] == "fixed")
    assert isinstance(fixed["amount"], float) and fixed["amount"] > 0
    unknown = next(x for x in payload["records"] if x["amount_details"]["kind"] == "unspecified")
    assert unknown["amount"] is None  # unknown is not zero


def test_deadline_semantics(payload):
    nutrien = by_title(payload, "Nutrien")
    assert nutrien["deadline_kind"] == "date" and nutrien["timing"] == "Apply by Nov 23, 2026"
    assert nutrien["availability_status"] == "open"
    cenovus = by_title(payload, "Cenovus")
    assert cenovus["deadline_kind"] == "annual_rule" and cenovus["timing"].startswith(
        "Due every year"
    )
    assert "Aug" in cenovus["timing"] and "Nov" in cenovus["timing"] and "Feb" in cenovus["timing"]
    annual = [x for x in payload["records"] if x["deadline_kind"] == "annual_rule"]
    assert len(annual) == 27  # two more annual deadlines exist as non-first entries in mixed cycles
    assert all(x["availability_status"] == "annual" for x in annual)


def test_eligibility_rules_map_to_profile_fields(payload):
    sfu = next(x for x in payload["records"] if x["provider"] == "Simon Fraser University")
    rule = sfu["eligibility_rule"]
    assert rule["type"] == "all"
    fields = {child["field"] for child in rule["children"] if child["type"] == "predicate"}
    assert "communities" in fields and "institution_id" in fields
    communities = next(c for c in rule["children"] if c.get("field") == "communities")
    assert communities["value"] == ["First Nations", "Inuit", "Métis"]
    unknown = [x for x in payload["records"] if x["eligibility_rule"]["type"] == "unknown"]
    assert (
        len(unknown) == 16
    )  # 15 directory-only entries + Nutrien; other unknown nodes sit inside mixed rules
    assert all("confirm with the provider" in x["note"] for x in unknown)


def test_evidence_refs_carry_quotes(payload):
    any_record = payload["records"][0]
    assert any(ref["quote"] for ref in any_record["evidence_refs"])
    assert any(ref["source_url"] for ref in any_record["evidence_refs"])


def test_stable_id_is_deterministic_and_bounded():
    short = "viu:an_award"
    assert stable_id(short) == short
    long_id = "x" * 200
    first, second = stable_id(long_id), stable_id(long_id)
    assert first == second and len(first) <= 100 and first != long_id
    assert stable_id("y" * 200) != first


def test_publish_and_import_round_trip(tmp_path, monkeypatch):
    settings = Settings(
        _env_file=None,
        data_mode="live",
        database_url=f"sqlite:///{tmp_path}/live.db",
        demo_database_url=f"sqlite:///{tmp_path}/demo.db",
    )
    upgrade(settings)
    frontend = tmp_path / "opportunities.json"
    monkeypatch.setattr("navigator.publish.FRONTEND_DATASET", frontend)
    result = publish(settings)
    assert result["records"] == 58 and result["created"] == 58
    again = publish(settings)
    assert again == {
        "data_mode": "live",
        "records": 58,
        "created": 0,
        "updated": 0,
        "unchanged": 58,
    }
    dataset = json.loads(frontend.read_text(encoding="utf-8"))
    assert dataset["data_mode"] == "live" and len(dataset["records"]) == 58
    with pytest.raises(ValueError, match="requires live mode"):
        publish(settings.model_copy(update={"data_mode": "demo"}))


def test_live_api_serves_the_canonical_dataset(tmp_path):
    settings = Settings(
        _env_file=None,
        data_mode="live",
        database_url=f"sqlite:///{tmp_path}/live.db",
        demo_database_url=f"sqlite:///{tmp_path}/demo.db",
        llm_enabled=False,
        openai_api_key="",
        openai_model="",
    )
    upgrade(settings)
    from navigator.publish import build_payload as build
    from navigator.publish import import_live as do_import

    staged = tmp_path / "staged.json"
    staged.write_text(
        json.dumps(build(RECORDS, INSTITUTIONS, date(2026, 10, 10)), ensure_ascii=False),
        encoding="utf-8",
    )
    do_import(settings, staged)
    from navigator.main import create_app

    app = create_app(settings)
    with TestClient(app) as client:
        health = client.get("/api/health").json()
        assert health["data_mode"] == "live" and health["migration_ready"]
        search = client.post("/api/opportunities/search", json={"filters": {}}).json()
        assert search["total"] == 58
        annual = client.post(
            "/api/opportunities/search",
            json={"filters": {"deadline_kind": "annual_rule", "include_unknown": False}},
        ).json()
        assert annual["total"] == 27
        annual_keep_unknown = client.post(
            "/api/opportunities/search", json={"filters": {"deadline_kind": "annual_rule"}}
        ).json()
        assert (
            annual_keep_unknown["total"] == 53
        )  # default keeps the 26 unspecified-deadline records
        bc = client.post(
            "/api/opportunities/search", json={"filters": {"provinces": ["British Columbia"]}}
        ).json()
        assert bc["total"] >= 33  # VIU (25) + SFU (8)
        stats = client.post("/api/statistics", json={"filters": {}}).json()
        assert stats["dataset_version"] == "live-read-model"
        assert stats["quality"]["verified_records"] == 58
        assert stats["amounts"]["listed"] == 43 and stats["amounts"]["unknown"] == 15
        match = client.post(
            "/api/match/evaluate",
            json={
                "filters": {},
                "profile": {"communities": ["Métis"], "metis_citizen": True},
            },
        ).json()
        statuses = {x["match_status"] for x in match["matches"]}
        # MNBC STEPS is the one record whose stated rules are fully checkable.
        assert "potential_fit" in statuses
        assert "needs_provider_confirmation" in statuses  # the honest default for the rest
    app.state.engine.dispose()
    engine_for(settings).dispose()
