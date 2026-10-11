"""Canonical-dataset publisher: honest transform, idempotent live import, API behaviour."""

import json
from collections import Counter
from datetime import date

import pytest
from fastapi.testclient import TestClient

from navigator.app.config import Settings
from navigator.app.db import engine_for, upgrade
from navigator.app.main import create_app
from navigator.app.publish import (
    DEFAULT_DATASET,
    FRONTEND_DATASET,
    _directory_community,
    _directory_region,
    build_payload,
    ensure_read_model,
    import_live,
    load_institutions,
    load_records,
    publish,
    stable_id,
)
from navigator.app.services import REGIONS

RECORDS = load_records(DEFAULT_DATASET)
INSTITUTIONS = load_institutions()
N = len(RECORDS)


@pytest.fixture(scope="module")
def payload():
    return build_payload(RECORDS, INSTITUTIONS, date(2026, 10, 10))


def by_title(payload, fragment):
    return next(x for x in payload["records"] if fragment in x["title"])


def by_provider(payload, name):
    return next(x for x in payload["records"] if x["provider"] == name)


def live_settings(tmp_path):
    return Settings(
        _env_file=None,
        data_mode="live",
        read_model_url=f"sqlite:///{tmp_path}/live.db",
        demo_read_model_url=f"sqlite:///{tmp_path}/demo.db",
        llm_enabled=False,
        openai_api_key="",
        openai_model="",
    )


def test_dataset_is_published_and_unique(payload):
    assert payload["data_mode"] == "live"
    assert N == 529  # the committed dataset; update it on purpose when the dataset is refreshed
    assert len(payload["records"]) == N
    assert len({x["id"] for x in payload["records"]}) == N
    assert all(not x["is_demo"] for x in payload["records"])
    assert all(x["url"].startswith("https://") for x in payload["records"])


def test_community_and_province_mapping(payload):
    sfu = by_provider(payload, "Simon Fraser University")
    assert sfu["community"] == ["First Nations", "Inuit", "Métis"]
    assert sfu["province"] == "British Columbia"  # institution_id eq sfu -> institutions.yaml
    assert sfu["location"] == "British Columbia"
    assert sfu["region_basis"] == "rule"
    psssp = by_title(payload, "Post-Secondary Student Support")
    assert psssp["community"] == ["First Nations"]  # first_nations_registered predicate
    # Nothing in its rules or in its source names a region: NOT STATED, never silently national.
    nutrien = by_title(payload, "Nutrien")
    assert nutrien["province"] is None and nutrien["location"] == "Region not stated"
    assert nutrien["region_basis"] == "not_stated"


def test_region_comes_from_rules_then_the_directory_and_silence_is_not_national(payload):
    assert Counter(x["region_basis"] for x in payload["records"]) == {"rule": 36, "directory": 486, "not_stated": 7}
    assert Counter(x["province"] for x in payload["records"]) == {
        "Manitoba": 130,
        "British Columbia": 95,
        "Ontario": 88,
        "Alberta": 62,
        "Saskatchewan": 50,
        "all": 38,  # "National" and "Any Location" in the directory
        "Northwest Territories": 21,
        "Nova Scotia": 15,
        "New Brunswick": 7,
        None: 7,
        "Yukon": 6,
        "Quebec": 3,
        "Nunavut": 3,
        "Newfoundland and Labrador": 2,
        "Prince Edward Island": 2,
    }
    assert {x["province"] for x in payload["records"]} <= set(REGIONS.values()) | {"all", None}
    # The federal directory lists these entries itself ("Province/territory: British Columbia." / "National.").
    hydro = by_provider(payload, "B.C. Hydro")
    assert (hydro["province"], hydro["region_basis"], hydro["location"]) == (
        "British Columbia",
        "directory",
        "British Columbia",
    )
    nwac = next(x for x in payload["records"] if x["provider"].startswith("Native Women"))
    assert (nwac["province"], nwac["region_basis"], nwac["location"]) == ("all", "directory", "Across Canada")
    # A directory listing feeds coverage and statistics, never the eligibility check.
    assert hydro["eligibility_rule"] == {"type": "unknown"}


def test_a_directory_region_it_cannot_read_stays_unstated():
    adapter = {"extraction_method": "deterministic_adapter"}
    assert _directory_region({**adapter, "summary": "x. Province/territory: Ontario. y"}) == "Ontario"
    assert _directory_region({**adapter, "summary": "Province/territory: National. y"}) == "all"
    assert _directory_region({**adapter, "summary": "Province/territory: Any Location. y"}) == "all"
    assert _directory_region({**adapter, "summary": "Province/territory: Narnia. y"}) is None
    assert _directory_region({**adapter, "summary": "Province/territory: Ontario, Alberta. y"}) is None
    assert _directory_region({**adapter, "summary": "no such line"}) is None
    assert _directory_region({"extraction_method": "curated", "summary": "Province/territory: Ontario."}) is None


def test_study_plans_are_post_secondary_and_training_only_when_the_title_says_so(payload):
    assert all("postsecondary" in x["goals"] for x in payload["records"])  # the dataset is post-secondary funding
    training = {x["title"] for x in payload["records"] if "training" in x["goals"]}
    assert len(training) == 5 and by_title(payload, "MNBC STEPS")["title"] in training
    assert any("Trades" in title for title in training)
    assert not any("Research" in title for title in training)  # research training is graduate research funding


def test_a_directory_entry_is_not_presented_as_the_providers_own_page(payload):
    kinds = Counter(x["source_kind"] for x in payload["records"])
    assert kinds == {"official_page": 43, "directory_listing": 486}
    # ... and it agrees with how each record was built: the directory adapter makes the directory listings.
    built = Counter(r["extraction_method"] for r in RECORDS)
    assert (built["curated"], built["deterministic_adapter"]) == (kinds["official_page"], kinds["directory_listing"])
    assert by_provider(payload, "B.C. Hydro")["source_kind"] == "directory_listing"
    assert by_title(payload, "Nutrien")["source_kind"] == "official_page"


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
    assert cenovus["deadline_kind"] == "annual_rule" and cenovus["timing"].startswith("Due every year")
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
    assert len(unknown) == 487  # 486 directory-only entries + Nutrien; other unknown nodes sit inside mixed rules
    assert all(
        x["eligibility_rule"]["type"] == "unknown"
        for x in payload["records"]
        if x["source_kind"] == "directory_listing"
    )
    assert all("confirm with the provider" in x["note"] for x in unknown)


def test_every_province_and_territory_has_records(payload):
    """The point of the multi-province dataset: no region is empty."""
    counts = Counter(x["province"] for x in payload["records"])
    empty = [name for name in REGIONS.values() if counts[name] == 0]
    assert empty == [], f"no record for: {empty}"


def test_a_directory_entry_gets_its_communities_from_the_directorys_own_group_column(payload):
    adapter = {"extraction_method": "deterministic_adapter"}
    everyone = ["First Nations", "Inuit", "M\u00e9tis"]
    assert _directory_community({**adapter, "summary": "x. Indigenous group: All Indigenous People. y"}) == everyone
    assert _directory_community({**adapter, "summary": "Indigenous group: M\u00e9tis. y"}) == ["M\u00e9tis"]
    assert (
        _directory_community({**adapter, "summary": "Indigenous group: Inuit; M\u00e9tis; First Nations. y"})
        == everyone
    )
    assert _directory_community({**adapter, "summary": "Indigenous group: M\u00e9tis; First Nations. y"}) == [
        "First Nations",
        "M\u00e9tis",
    ]
    assert (
        _directory_community({**adapter, "summary": "Indigenous group: Narnians. y"}) is None
    )  # unknown is not everyone
    assert _directory_community({**adapter, "summary": "no such line"}) is None
    assert _directory_community({"extraction_method": "curated", "summary": "Indigenous group: Inuit."}) is None
    # In the dataset: an entry that names one group is not shown as open to all three.
    one_group = [x for x in RECORDS if "Indigenous group: M\u00e9tis." in (x.get("summary") or "")]
    assert one_group, "the dataset has entries the directory lists for M\u00e9tis students only"
    published = {x["source_id"]: x for x in payload["records"]}
    assert all(published[r["id"]]["community"] == ["M\u00e9tis"] for r in one_group)


def test_a_stated_range_is_a_range_never_one_figure(payload):
    ranges = [x for x in payload["records"] if x["amount_details"]["kind"] == "range"]
    assert ranges, "the dataset has stated ranges"
    for x in ranges:
        assert x["amount"] is None
        assert 0 < x["amount_details"]["minimum"] < x["amount_details"]["maximum"], x["title"]
    assert all(
        x["amount_details"]["minimum"] is None for x in payload["records"] if x["amount_details"]["kind"] != "range"
    )


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


def test_the_committed_static_dataset_matches_what_publish_writes():
    """dist/data/opportunities.json is what static hosting serves: it must not lag behind data/awards.jsonl."""
    committed = json.loads(FRONTEND_DATASET.read_text(encoding="utf-8"))
    fresh = build_payload(RECORDS, INSTITUTIONS, date(2026, 10, 10))

    def stable(record):  # availability depends on the day the file was written
        return {k: v for k, v in record.items() if k != "availability_status"}

    assert committed["data_mode"] == "live"
    assert [stable(x) for x in committed["records"]] == [stable(x) for x in fresh["records"]], (
        "run `python -m navigator.cli app publish` to refresh dist/data/opportunities.json"
    )


def test_publish_and_import_round_trip(tmp_path, monkeypatch):
    settings = live_settings(tmp_path)
    upgrade(settings)
    frontend = tmp_path / "opportunities.json"
    monkeypatch.setattr("navigator.app.publish.FRONTEND_DATASET", frontend)
    result = publish(settings)
    assert result["records"] == N and result["created"] == N
    again = publish(settings)
    assert again == {"data_mode": "live", "records": N, "created": 0, "updated": 0, "unchanged": N}
    dataset = json.loads(frontend.read_text(encoding="utf-8"))
    assert dataset["data_mode"] == "live" and len(dataset["records"]) == N
    with pytest.raises(ValueError, match="requires live mode"):
        publish(settings.model_copy(update={"data_mode": "demo"}))
    engine_for(settings).dispose()


def test_ensure_read_model_is_idempotent_keeps_modes_apart_and_leaves_the_static_file_alone(tmp_path, monkeypatch):
    frontend = tmp_path / "opportunities.json"
    monkeypatch.setattr("navigator.app.publish.FRONTEND_DATASET", frontend)
    live = Settings(_env_file=None, data_mode="live", data_dir=str(tmp_path), llm_enabled=False)
    first = ensure_read_model(live)
    assert first == {"data_mode": "live", "records": N, "created": N, "updated": 0, "unchanged": 0}
    second = ensure_read_model(live)
    assert (second["created"], second["unchanged"]) == (0, N)
    assert not frontend.exists()  # only `navigator app publish` rewrites the static file
    demo = live.model_copy(update={"data_mode": "demo"})
    assert ensure_read_model(demo)["created"] == 4
    # Demo and live never share a file.
    assert (tmp_path / "read_model.db").is_file() and (tmp_path / "demo" / "read_model.db").is_file()


def test_a_missing_export_publishes_nothing_and_says_so(tmp_path):
    live = Settings(_env_file=None, data_mode="live", data_dir=str(tmp_path), llm_enabled=False)
    result = ensure_read_model(live, dataset_path=tmp_path / "missing.jsonl")
    assert result["records"] == 0 and "not found" in result["note"]


def test_live_api_serves_the_canonical_dataset(tmp_path):
    settings = live_settings(tmp_path)
    upgrade(settings)
    import_live(settings, build_payload(RECORDS, INSTITUTIONS, date(2026, 10, 10)))
    app = create_app(settings)
    with TestClient(app) as client:

        def total(**filters):
            return client.post("/api/opportunities/search", json={"filters": filters}).json()["total"]

        health = client.get("/api/health").json()
        assert health["data_mode"] == "live" and health["migration_ready"]
        assert total() == N
        published = build_payload(RECORDS, INSTITUTIONS, date(2026, 10, 10))["records"]
        counts = Counter(x["province"] for x in published)
        national, unstated = counts["all"], counts[None]
        regional = N - national - unstated
        unspecified_deadline = sum(1 for x in published if x["deadline_kind"] == "unspecified")
        assert total(deadline_kind="annual_rule", include_unknown=False) == 27
        assert (
            total(deadline_kind="annual_rule") == 27 + unspecified_deadline
        )  # the default keeps unspecified deadlines
        # Region: three separate buckets, and a province filter keeps what reaches it.
        assert (total(scope="regional"), total(scope="national"), total(scope="unspecified")) == (
            regional,
            national,
            unstated,
        )
        assert total(provinces=["British Columbia"], scope="regional") == counts["British Columbia"]
        # A province filter keeps its own records and the nationwide ones; the ones that state no region only with unknowns.
        assert total(provinces=["Ontario"], include_unknown=False) == counts["Ontario"] + national
        assert total(provinces=["Ontario"]) == counts["Ontario"] + national + unstated
        by_region = {name: total(provinces=[name], scope="regional") for name in REGIONS.values()}
        assert by_region == {name: counts[name] for name in REGIONS.values()}
        assert all(by_region.values()), "every province and territory has records"
        stats = client.post("/api/statistics", json={"filters": {}}).json()
        assert stats["dataset_version"] == "live-read-model"
        assert (stats["national_count"], stats["regional_count"], stats["unspecified_region_count"]) == (
            national,
            regional,
            unstated,
        )
        assert stats["national_count"] + stats["regional_count"] + stats["unspecified_region_count"] == stats["total"]
        assert stats["quality"]["verified_records"] == N
        listed = sum(1 for x in published if x["amount"] is not None)
        assert stats["amounts"]["listed"] == listed and stats["amounts"]["unknown"] == N - listed
        match = client.post(
            "/api/match/evaluate",
            json={"filters": {}, "profile": {"communities": ["Métis"], "metis_citizen": True}},
        ).json()
        statuses = {x["match_status"] for x in match["matches"]}
        # MNBC STEPS is the one record whose stated rules are fully checkable.
        assert "potential_fit" in statuses
        assert "needs_provider_confirmation" in statuses  # the honest default for the rest
        dataset = client.get("/data/opportunities.json").json()
        assert dataset["data_mode"] == "live" and len(dataset["records"]) == N
    app.state.engine.dispose()
    engine_for(settings).dispose()
