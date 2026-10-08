# Architecture

## Shape

Ports and adapters. Everything that decides something (time and deadline semantics, evidence verification, rule
evaluation, record validation, import planning, matching, reports) is plain Python in the package core and has no
dependency on FastAPI, SQLAlchemy, httpx or Typer. The web, database, HTTP and CLI layers are thin adapters around it.
That is why the core can be tested without the web stack, and why a rule is never "implemented twice" (once for the API,
once for the importer).

```
sources.yaml ──► fetch_stage ──► SnapshotStore (raw/, text/, sha256, never overwritten)
   (allowlist,      │  Fetcher (robots, rate limit, retries, redirects, 304)      │
    terms status)   ▼                                                              ▼
              FetchIndex + audit        text extraction (HTML blocks / PDF pages / ocr_required)
                                                                                   │
                         source adapters (isc_index, sectioned, listing_detail, policy, curated)
                                                                                   ▼
                              candidates ──► validation (schema, semantics, evidence, hashes) ──► quarantine
                                                                                   ▼
                                     planner (created/updated/unchanged/rejected/pending_review)
                                                                                   ▼
                          Repository port ─► SqlRepository (SQLAlchemy) | MemoryRepository (tests)
                                                          │
                      export (JSONL) ◄────────────────────┼────────────► reports (freshness JSON + Markdown)
                                                          ▼
                    services.query / matching.engine ──► FastAPI routes (read-only)
```

## Modules

| Package / module | Responsibility |
| --- | --- |
| `navigator.core` | Time zones and deadline *windows*, money, ids, canonical fingerprints, evidence verification, URL policy/SSRF guard, JSON-Schema-lite validator, the record contract |
| `navigator.matching` | Rule AST + three-valued engine (`rules`), availability (`availability`), per-profile matching and grouping (`engine`) |
| `navigator.ingestion` | `fetcher` (+ `http_transport`), `fetch_stage`, `snapshots`, `text`, `adapters/`, `builder` (quote -> evidence), `validation`, `planner`, `importer`, `rows`, `manifest`, `sources` |
| `navigator.services` | Use cases shared by CLI/API/tests: `pipeline` (demo), `live`, `query` |
| `navigator.models` | SQLAlchemy models and `SqlRepository` |
| `navigator.api` / `navigator.schemas` | FastAPI app factory, routes, error handling; Pydantic request/response models |
| `navigator.cli` | Typer commands |
| `navigator.demo` | The synthetic sources and the 25 demo records |
| `navigator.config` | The single configuration resolver (`derive_runtime`, `load_runtime`) |
| `migrations/` | Alembic (hand-written initial migration; `scripts/check_static.py` checks it against the models) |

## Data flow rules that matter

* **Evidence first.** A record cites quotes by `evidence_ids`; `builder.attach_evidence` locates each quote in the stored
  text and fills `field_path` itself, so a pointer can't be mistyped. Under `/cycles` the pointer token is the
  `cycle_key` (stable when cycles are merged).
* **Verification is not fetching.** `last_verified_at` is stamped only after the validator passes. A successful download
  or file import never sets it.
* **Idempotent import.** Same stable id -> same opportunity; cycles merge by `(opportunity, cycle_key)`; older cycles
  survive; an older input can't overwrite a newer verified one (`pending_review`); nothing is deleted because a source
  stopped listing it.
* **Strict by default.** One invalid record rejects the whole batch (nothing written); `--allow-partial` commits per
  record and still exits non-zero if anything was rejected. `--dry-run` runs the real checks and writes nothing.
* **demo/live isolation.** Separate database URL and artifact folder; the resolver refuses a configuration where they
  could share a database; the importer rejects records whose `is_demo` doesn't match the mode; listings are scoped to
  one mode; the live pipeline never writes an export file when it has no real data.

## SQLite and PostgreSQL

SQLite is the default (`DATABASE_URL=sqlite:///./data/navigator.db`; the parent folder is created and foreign keys are
switched on). PostgreSQL works through `DATABASE_URL` (install the `postgres` extra). Nested objects (rule trees,
deadlines, amounts) are JSON columns so they round-trip exactly; scalars used for querying are real columns. Timestamps
are ISO-8601 UTC strings so a record is byte-for-byte the same in the database, the export and the API.

## Privacy

`POST /match` receives a self-reported profile and uses it for that call only: not stored, not logged, not echoed, not
sent to any model. There is no field for a name, address, e-mail, SIN, status-card/registry/membership number, student
number, income or application documents; unknown fields are rejected (HTTP 422) and validation errors list *where* a
request is wrong without echoing *what* was sent.

## How a frontend should call it

All endpoints are read-only JSON over HTTP (OpenAPI at `/docs`). Typical flow: `GET /opportunities` to browse;
`POST /match` with the questionnaire answers; ask the student the `clarification_questions` of `needs_information`
results and call again; show `source_uncertainties` and the `official_url`/`application_route` for
`needs_provider_confirmation`; always display `data_mode` (a `demo` response must be visibly labelled synthetic) and the
`disclaimer`. Group results with `group_by_application: true` to show awards that share one form, while still showing
each award's own result. Enable CORS only by listing explicit origins in `CORS_ALLOW_ORIGINS`.
