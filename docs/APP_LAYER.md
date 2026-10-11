# The application layer (`navigator.app`)

Everything the site in `dist/` needs beyond the evidence pipeline: a read model of the published records, search, Statistics, an
evidence check and the AI conversation. The pipeline (`navigator.ingestion`, `navigator.core`, `navigator.matching`, ...) stays
the only producer of data. This layer reads what was published and never writes records of its own.

```
sources -> pipeline (snapshots, quotes checked) -> data/awards.jsonl      the canonical, evidence-backed export
                                                       |  navigator app publish   (serve does the same, without touching dist/)
                                                       v
                          data/read_model.db   (data/demo/read_model.db in demo mode)   published records as JSON, one file per mode
                                                       |
                  /api/*  +  /data/opportunities.json  +  the static site in dist/      Explore - Statistics - AI search
```

One server runs it all: `python -m navigator.cli serve --mode live`. `/` is the site, `/app/` the questionnaire app, `/docs` the
OpenAPI of both layers. Commands, settings and checks are in [RUNBOOK.md](RUNBOOK.md) ("The site, Statistics and AI search").
The design behind it (tool registry, counting rules, privacy) is [BACKEND-REDESIGN.md](BACKEND-REDESIGN.md); what was verified
against which AI provider is [LLM_PROVIDERS.md](LLM_PROVIDERS.md).

## Modules (`src/navigator/app/`)

| Module | Responsibility |
| --- | --- |
| `config.py` | Settings. `DATA_MODE`, `DATA_DIR` and `CORS_ALLOW_ORIGINS` are the core's own settings, so one `.env` drives both layers; the AI settings (`LLM_*`, `OPENAI_*`) live here |
| `db.py` | The read model: one table of published records, one SQLite file per mode, its own migrations in `migrations_app/` |
| `publish.py` | Canonical export -> read model records. Region, amount, deadline, study plans and source kind are derived without guessing; a fact the source does not state stays null |
| `schemas.py` | The typed contract shared by the filters, the AI tools and Statistics (`SearchFilters`, `AppProfile`, `AppMatchRequest`, ...) |
| `services.py` | Search, the evidence check (three-valued), facets and exact aggregates |
| `assistant.py` | The Responses-API adapter: a fixed tool registry, a call budget, ID and answer validation; card facts are read back from the database |
| `main.py` | `install()` adds the routes to the core's FastAPI app; `create_app()` is a standalone app for tests |
| `cli.py` | The functions behind `navigator app upgrade / init-demo / publish / status` |

## Rules that hold across the layers

* **Unknown is not zero, and not national.** A region the source does not state is `null`; Statistics counts it as "not stated",
  separately from "nationwide" and "region-specific". Amounts are never summed into a funding pool.
* **One mode.** The site, `/api/*` and the pipeline read the same `DATA_MODE`; demo and live never share a database file.
* **Two implementations, one behaviour.** The static site filters and counts in `dist/model.js`; the server does it in
  `services.py`. `tests/test_filter_parity.py` runs the same cases through both and fails when they differ.
* **Nothing about a person is stored.** The profile and messages live in the browser tab; the server neither saves nor logs them.
  The AI is asked with `store: false`; a provider's own retention may still apply.
* **The API has no write endpoints.** `tests/test_api.py` asserts the exact list of routes and that none is PUT, PATCH or DELETE.

## What it is not

Not a crawler and not a verification pipeline: those are the core. Not a national market census: the live data is the 529 published
records, and the demo mode is four illustrative ones. No accounts, uploads or public write endpoints.
