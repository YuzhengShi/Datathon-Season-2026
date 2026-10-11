# Funding Navigator application backend

Shared natural-language search / matching / analytics tools. Python 3.11+; tested on Python 3.12.

This iteration implements the application read model and LLM adapter. It does not implement the entire earlier official-source ingestion specification. Four carried-over records are explicitly illustrative. Live mode starts empty and never imports them.

## Install and run

From the complete project folder (overlay the changed-file ZIP onto the previous source first):

```bash
cd backend
python -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.lock
python -m pip install --no-deps -e .
python -m navigator.cli init-demo --mode demo
python -m pytest -q
python -m navigator.cli serve --mode demo --host 127.0.0.1 --port 8000
```

Open `http://127.0.0.1:8000/#statistics`. FastAPI serves the existing frontend and `/api/*` from the same origin. OpenAPI is at `/api/docs`. Do not run the static-only server if you want LLM requests.

Windows PowerShell (no activation or security-policy changes required):

```powershell
cd backend
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.lock
.\.venv\Scripts\python.exe -m pip install --no-deps -e .
.\.venv\Scripts\python.exe -m navigator.cli init-demo --mode demo
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m navigator.cli serve --mode demo --host 127.0.0.1 --port 8000
```

Running `init-demo` twice reports `unchanged: 4` on the second run. It applies Alembic before importing and writes only the demo database. No runtime create_all or automatic production seeding is used.

## Connect the real LLM

Copy `.env.example` to `.env` **inside backend/** and set:

```dotenv
LLM_ENABLED=true
OPENAI_API_KEY=your-approved-server-side-key
OPENAI_MODEL=your-supported-Responses-model
```

Use the OpenAI Developers key workflow for hosted integration. Do not send a key through chat, commit it, or put it in browser files. Restart the service after configuration changes. `/api/health` reports `llm_ready:true` only when the enable flag, model and key are configured. This flag does not prove provider quota/access; requests surface provider failures explicitly.

No live model calls were run in the delivered verification: the API key was unavailable. Offline tests use a scripted provider fixture, which is injected only in tests and is never a runtime fallback. A missing key returns HTTP 503 `LLM_NOT_CONFIGURED`, not simulated recommendations.

The static hosted Site contains the dashboard and UI only. It is not a Python API deployment. Production API hosting, authentication, rate limiting and audited live-data publishing remain separate work; keep the current Site audience unchanged.

## Verify the API without a browser

The server command stays running in terminal 1. In terminal 2, from backend/ with the same virtual environment:

```bash
python scripts/smoke_test.py --base-url http://127.0.0.1:8000
```

This is a health/search/detail/statistics/eligibility HTTP check, not a browser layout test. It expects demo mode. An unconfigured LLM is an explicit expected state. It does not make a paid model request.

Alternatively, `python scripts/verify_runtime.py` starts a local CLI server, runs the five HTTP checks and stops only that child process. This workflow was verified; it needs the demo database initialized first.

Default pytest uses temporary databases and provider fixtures, with no network or API key. It checks shared orchestration, result hydration, schema strictness, untrusted tools/IDs, source uncertainties, profile non-persistence, pagination, filtering, mode isolation and non-additive geography/money semantics.

## Files and responsibilities

| Module | Responsibility |
| --- | --- |
| config.py | Same environment / mode resolver for CLI and API |
| db.py + migrations/ | Mode-isolated public read model, Alembic, transactional demo upsert |
| schemas.py | Shared query, profile, tools and response contracts |
| services.py | Search, evidence condition checks, facets and exact aggregates |
| assistant.py | Responses adapter, fixed tool registry, budget, ID/response validation |
| main.py | Typed APIs, redacted errors, same-origin frontend |
| cli.py | Initialize, migrate and serve |
| tests/ | Offline API and provider-contract verification |

The complete architecture, new filters, data semantics and production publisher design are in `../docs/BACKEND-REDESIGN.md`.
