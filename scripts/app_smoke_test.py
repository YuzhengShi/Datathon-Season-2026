"""HTTP smoke check of the application layer's routes against a running server in DEMO mode.

Run `python -m navigator.cli serve --mode demo` first (or use scripts/app_verify_runtime.py, which does both).
It makes no AI request.
"""

import argparse
from urllib.parse import urlparse

import httpx


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    args = parser.parse_args()
    local = urlparse(args.base_url).hostname in {"127.0.0.1", "localhost", "::1"}
    with httpx.Client(base_url=args.base_url, timeout=10, trust_env=not local) as client:
        health = client.get("/api/health")
        health.raise_for_status()
        assert health.json()["data_mode"] == "demo" and health.json()["migration_ready"]
        dataset = client.get("/data/opportunities.json")
        dataset.raise_for_status()
        assert dataset.json()["data_mode"] == "demo" and len(dataset.json()["records"]) == 4
        search = client.post("/api/opportunities/search", json={"filters": {"communities": ["Métis"]}})
        search.raise_for_status()
        assert search.json()["total"] == 2
        detail = client.get("/api/opportunities/mnbc")
        detail.raise_for_status()
        assert detail.json()["record"]["amount"] is None
        statistics = client.post("/api/statistics", json={"filters": {}})
        statistics.raise_for_status()
        stats = statistics.json()
        assert stats["total"] == 4 and stats["amounts"]["sum"] is None
        assert stats["national_count"] + stats["regional_count"] + stats["unspecified_region_count"] == 4
        match = client.post("/api/match/evaluate", json={"profile": {"communities": ["Métis"], "goal": "training"}})
        match.raise_for_status()
        assert all(x["match_status"] == "needs_provider_confirmation" for x in match.json()["matches"])
        print("6 API checks passed; no live model call was made.")


if __name__ == "__main__":
    main()
