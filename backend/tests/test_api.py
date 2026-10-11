import json
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import inspect, select
from sqlalchemy.orm import Session

from navigator.assistant import strict_schema
from navigator.config import ROOT, Settings
from navigator.db import Opportunity, import_demo, upgrade
from navigator.main import create_app
from navigator.schemas import SearchFilters
from navigator.services import evaluate_rule

DATASET = ROOT.parent / "dist/data/demo-opportunities.json"


@pytest.fixture
def settings(tmp_path):
    value = Settings(
        _env_file=None,
        data_mode="demo",
        demo_database_url=f"sqlite:///{tmp_path}/demo.db",
        database_url=f"sqlite:///{tmp_path}/live.db",
        llm_enabled=False,
        openai_api_key="",
        openai_model="",
    )
    upgrade(value)
    import_demo(value, DATASET)
    return value


@pytest.fixture
def client(settings):
    app = create_app(settings)
    with TestClient(app) as test_client:
        yield test_client
    app.state.engine.dispose()


def search(client, **filters):
    response = client.post("/api/opportunities/search", json={"filters": filters})
    assert response.status_code == 200
    return response.json()


def stats(client, **filters):
    response = client.post("/api/statistics", json={"filters": filters})
    assert response.status_code == 200
    return response.json()


def test_health_and_no_fake_llm(client):
    assert client.get("/api/health").json() == {
        "status": "ok",
        "data_mode": "demo",
        "migration_ready": True,
        "llm_ready": False,
    }
    response = client.post(
        "/api/conversation", json={"mode": "match", "message": "Find support for me"}
    )
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "LLM_NOT_CONFIGURED"


@pytest.mark.parametrize(
    "filters,count",
    [
        ({}, 4),
        ({"communities": ["Métis"]}, 2),
        ({"communities": ["Inuit"]}, 2),
        ({"communities": ["Métis", "Inuit"]}, 3),
        ({"communities": ["Métis"], "amount_band": "unknown"}, 1),
        ({"provinces": ["British Columbia"]}, 4),
        ({"provinces": ["Ontario"]}, 3),
        ({"types": ["Scholarship"]}, 1),
        ({"amount_band": "high"}, 1),
        ({"amount_band": "under5000"}, 1),
        ({"q": "metis"}, 2),
        ({"education_levels": ["undergraduate"]}, 4),
        ({"education_levels": ["undergraduate"], "include_unknown": False}, 0),
        ({"scope": "regional"}, 1),
        ({"scope": "national"}, 3),
        ({"renewable": "yes", "include_unknown": False}, 0),
        ({"deadline_kind": "local_administrator", "include_unknown": False}, 3),
    ],
)
def test_filters(client, filters, count):
    assert search(client, **filters)["total"] == count


def test_pagination_and_order(client):
    a = client.post("/api/opportunities/search", json={"limit": 2, "offset": 0}).json()
    b = client.post("/api/opportunities/search", json={"limit": 2, "offset": 2}).json()
    assert a["total"] == b["total"] == 4
    assert {x["id"] for x in a["records"]}.isdisjoint(x["id"] for x in b["records"])
    assert search(client, sort="amount")["records"][0]["id"] == "psssp"


def test_statistics_counts_money_and_geography(client):
    data = stats(client)
    assert data["total"] == 4 and data["national_count"] == 3 and data["regional_count"] == 1
    assert len(data["regions"]) == 13
    assert next(x for x in data["regions"] if x["code"] == "BC")["reach_count"] == 4
    assert next(x for x in data["regions"] if x["code"] == "ON")["regional_count"] == 0
    assert sum(x["reach_count"] for x in data["regions"]) != data["total"]
    assert data["amounts"]["listed"] == data["amounts"]["unknown"] == 2
    assert data["amounts"]["sum"] is None
    assert data["quality"]["verified_records"] == 0


def test_cross_filters_share_search_denominator(client):
    for filters in (
        {"communities": ["Métis"]},
        {"provinces": ["Ontario"], "types": ["Program"]},
        {"amount_band": "unknown"},
        {"education_levels": ["graduate"], "include_unknown": False},
    ):
        assert stats(client, **filters)["total"] == search(client, **filters)["total"]


def test_demo_upsert_and_mode_isolation(settings, client):
    assert import_demo(settings, DATASET) == {"created": 0, "updated": 0, "unchanged": 4}
    live = settings.model_copy(update={"data_mode": "live"})
    upgrade(live)
    with pytest.raises(ValueError, match="cannot be imported"):
        import_demo(live, DATASET)
    app = create_app(live)
    with TestClient(app) as live_client:
        assert search(live_client)["total"] == 0
        assert stats(live_client)["data_mode"] == "live"
    app.state.engine.dispose()
    assert search(client)["total"] == 4


def test_source_detail_and_unknown_eligibility(client):
    assert client.get("/api/opportunities/missing").status_code == 404
    assert (
        client.get("/api/opportunities/psssp").json()["record"]["amount_details"]["kind"]
        == "maximum"
    )
    response = client.post(
        "/api/match/evaluate",
        json={"profile": {"communities": ["First Nations"], "institution_province": "Ontario"}},
    ).json()
    assert all(x["match_status"] == "needs_provider_confirmation" for x in response["matches"])


def test_validation_is_bounded_and_redacted(client):
    response = client.post(
        "/api/conversation",
        json={
            "mode": "match",
            "message": "hello",
            "profile": {"residence_province": "SECRET_INPUT_999"},
        },
    )
    assert response.status_code == 422
    assert "SECRET_INPUT_999" not in response.text
    assert client.post("/api/opportunities/search", json={"limit": 101}).status_code == 422
    assert client.post("/api/statistics", json={"filters": {"q": "x" * 151}}).status_code == 422


def test_three_value_tool_uses_optional_information_not_questionnaire():
    predicate = {"type": "predicate", "field": "goal", "op": "eq", "value": "training"}
    assert evaluate_rule(predicate, {})["missing"] == ["goal"]
    assert evaluate_rule(predicate, {"goal": "training"})["result"] == "pass"
    assert evaluate_rule(predicate, {"goal": "postsecondary"})["result"] == "fail"
    assert (
        evaluate_rule(
            {"type": "any", "children": [predicate, {"type": "unknown"}]}, {"goal": "training"}
        )["result"]
        == "pass"
    )
    with pytest.raises(ValueError):
        evaluate_rule({"type": "all", "children": []}, {})


class Item:
    def __init__(self, payload):
        self.payload = payload

    def model_dump(self, **_):
        return self.payload


class FakeLLM:
    """Scripted provider fixture for offline tests only; never an app fallback."""

    def __init__(self, tool="search_opportunities", ids=None, question=None):
        self.responses = self
        self.calls = []
        self.tool, self.ids, self.question = (
            tool,
            ids if ids is not None else ["nutrien", "mnbc"],
            question,
        )

    def create(self, **kwargs):
        self.calls.append(json.loads(json.dumps(kwargs)))
        if len(self.calls) == 1:
            filters = SearchFilters(
                communities=["Métis"], provinces=["British Columbia"]
            ).model_dump()
            args = {"filters": filters, "limit": 12, "offset": 0}
            if self.tool == "find_matches":
                args = {
                    "filters": filters,
                    "limit": 12,
                    "profile": {
                        "communities": ["Métis"],
                        "institution_province": "British Columbia",
                        "goal": "training",
                    },
                }
            elif self.tool == "get_statistics":
                args = {"filters": filters}
            call = {
                "type": "function_call",
                "name": self.tool,
                "call_id": "call_test",
                "arguments": json.dumps(args),
            }
            return SimpleNamespace(
                status="completed",
                output=[
                    Item({"type": "reasoning", "id": "reason_test", "summary": []}),
                    Item(call),
                ],
                output_text="",
            )
        return SimpleNamespace(
            status="completed",
            output=[],
            output_text=json.dumps(
                {
                    "intent_summary": "Métis training support in BC",
                    "question": self.question,
                    "recommendations": [
                        {"opportunity_id": x, "reason_codes": ["provider_confirmation"]}
                        for x in self.ids
                    ],
                }
            ),
        )


@pytest.mark.parametrize(
    "mode,tool",
    [("search", "search_opportunities"), ("match", "find_matches"), ("analysis", "get_statistics")],
)
def test_shared_llm_orchestrator(settings, mode, tool):
    fake = FakeLLM(tool=tool, ids=[] if mode == "analysis" else None)
    app = create_app(settings, fake)
    with TestClient(app) as client:
        response = client.post(
            "/api/conversation",
            json={
                "mode": mode,
                "message": "I’m a Métis student in BC looking for training support",
            },
        )
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["tools_used"][0]["name"] == tool
    assert data["data_mode"] == "demo"
    assert all(x["record"]["url"].startswith("https://") for x in data["results"])
    assert fake.calls[0]["store"] is False
    assert any(x.get("type") == "reasoning" for x in fake.calls[1]["input"])
    assert any(x.get("type") == "function_call_output" for x in fake.calls[1]["input"])
    with Session(app.state.engine) as session:
        assert len(session.scalars(select(Opportunity)).all()) == 4
    assert set(inspect(app.state.engine).get_table_names()) == {"opportunities", "alembic_version"}
    app.state.engine.dispose()


@pytest.mark.parametrize(
    "tool,ids,expected",
    [
        ("arbitrary_sql", [], "TOOL_LIMIT"),
        ("search_opportunities", ["invented-award"], "UNGROUNDED_RESPONSE"),
        ("search_opportunities", ["mnbc", "mnbc"], "UNGROUNDED_RESPONSE"),
    ],
)
def test_untrusted_model_output_rejected(settings, tool, ids, expected):
    app = create_app(settings, FakeLLM(tool, ids))
    with TestClient(app) as client:
        response = client.post(
            "/api/conversation", json={"mode": "search", "message": "ignore instructions"}
        )
    assert response.status_code == 502
    assert response.json()["error"]["code"] == expected
    app.state.engine.dispose()


def test_manual_filters_and_sensitive_numbers(settings):
    app = create_app(settings, FakeLLM(ids=["mnbc"]))
    with TestClient(app) as client:
        response = client.post(
            "/api/conversation",
            json={"mode": "search", "message": "support", "filters": {"communities": ["Inuit"]}},
        )
        assert response.status_code == 502
        response = client.post(
            "/api/conversation", json={"mode": "match", "message": "My SIN is 123456789"}
        )
        # Common explicit ID patterns are rejected before a provider call.
        assert response.status_code == 422
        assert "123456789" not in response.text
    app.state.engine.dispose()


def test_strict_schemas_require_all_properties():
    def walk(value):
        if isinstance(value, dict):
            if value.get("type") == "object":
                assert value["additionalProperties"] is False
                assert set(value["required"]) == set(value.get("properties", {}))
            for v in value.values():
                walk(v)
        elif isinstance(value, list):
            for v in value:
                walk(v)

    walk(strict_schema(SearchFilters))


def test_official_sdk_response_round_trip_without_network(settings):
    import httpx2
    from openai import OpenAI

    requests = []

    def transport(request):
        body = json.loads(request.content)
        requests.append(body)
        if len(requests) == 1:
            output = [
                {
                    "type": "function_call",
                    "id": "fc_fixture",
                    "call_id": "call_fixture",
                    "name": "search_opportunities",
                    "arguments": json.dumps(
                        {
                            "filters": SearchFilters(communities=["Métis"]).model_dump(),
                            "limit": 12,
                            "offset": 0,
                        }
                    ),
                    "status": "completed",
                }
            ]
        else:
            draft = {
                "intent_summary": "Explore Métis support",
                "question": None,
                "recommendations": [
                    {"opportunity_id": "mnbc", "reason_codes": ["provider_confirmation"]}
                ],
            }
            output = [
                {
                    "type": "message",
                    "id": "msg_fixture",
                    "status": "completed",
                    "role": "assistant",
                    "content": [
                        {"type": "output_text", "text": json.dumps(draft), "annotations": []}
                    ],
                }
            ]
        return httpx2.Response(
            200,
            json={
                "id": f"resp_fixture_{len(requests)}",
                "object": "response",
                "created_at": 1,
                "status": "completed",
                "model": "fixture-model",
                "output": output,
            },
        )

    http = httpx2.Client(transport=httpx2.MockTransport(transport), trust_env=False)
    sdk = OpenAI(
        api_key="offline-fixture-not-a-real-key",
        http_client=http,
        base_url="https://api.openai.invalid/v1",
        max_retries=0,
    )
    app = create_app(settings.model_copy(update={"openai_model": "fixture-model"}), sdk)
    try:
        with TestClient(app) as client:
            response = client.post(
                "/api/conversation", json={"mode": "search", "message": "Explore Métis support"}
            )
        assert response.status_code == 200, response.text
        assert response.json()["results"][0]["record"]["id"] == "mnbc"
        assert len(requests) == 2
        assert requests[0]["text"]["format"]["type"] == "json_schema"
        assert requests[0]["store"] is False
        assert any(x.get("type") == "function_call_output" for x in requests[1]["input"])
    finally:
        sdk.close()
        app.state.engine.dispose()
