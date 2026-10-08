# Handoff

*Updated after the first real runs: a Windows machine, then the real network (October 2026). Every statement says where it was run.*

## 0. Read this first

* **Verified environment:** Windows, CPython 3.12.10, a fresh virtual environment installed from the exact `requirements.lock`
  (`pip check` clean). **Not verified:** Linux/macOS, Python 3.11, PostgreSQL.
* **Tests:** 241 pass (database, API and command-line suites included); 3 more are marked `live`, are off by default, and were run once on
  the real network against `example.com` only (3 passed). `ruff check`, `ruff format --check` and `scripts/check_static.py` are clean.
* **Real data: 33 real opportunities** (target 20-30, numerically met) in the live database and `data/awards.jsonl`. **Read section 3 before
  using them:** 25 of the 33 come from a dated Government of Canada directory and have no deadline and only free-text eligibility.
* **UBC could not be fetched:** both `students.ubc.ca` pages answered HTTP 403 to an automated client. Nothing was retried, disguised or
  worked around.
* Every record is `machine_checked` (each quote was found in the stored snapshot); none is `human_reviewed`. Site terms were not reviewed by me:
  the project owner authorised the fetch on 2026-10-07, robots.txt was honoured, one request per second per host, at most 60 pages in total.
  `access_status` in `sources.yaml` is still `unreviewed`; update it when a person has read the terms.

## 1. First actions

1. `python -m venv .venv`, `python -m pip install -r requirements.lock`, `python -m pip install --no-deps -e .`
2. `python -m pytest -q` (expect 241 passed), `python -m ruff check .`, `python -m ruff format --check .`, `python scripts/check_static.py`
3. Demo: `python -m navigator.cli pipeline --mode demo --as-of 2026-10-07` twice (25 created, then 25 unchanged); `serve --mode demo` and
   `python scripts/smoke_test.py --base-url http://127.0.0.1:8000 --expect-mode demo` (29/29).
4. Live: the stored real snapshots are in `data/raw`/`data/text`; `python -m navigator.cli pipeline --mode live --limit 40 --max-pages 60 --resume`
   reuses them without downloading again. Set a real contact in `USER_AGENT` (`.env`) before any larger run.

Next work for a coding agent: [NEXT_SESSION_PROMPT.md](NEXT_SESSION_PROMPT.md).

## 2. What was run where

| where | what | result |
| --- | --- | --- |
| Windows, fresh venv from the exact lock | `pip install -r requirements.lock`, `pip check` | installed, no broken requirements |
| same | full `pytest -q` | **241 passed**, 83 subtests, 1 warning (Starlette `TestClient` will move from `httpx` to `httpx2`) |
| same | `ruff check .`, `ruff format --check .`, `check_static.py` | clean |
| same | demo pipeline twice; `serve --mode demo` + smoke | 25 created then 25 unchanged; smoke 29/29 |
| real network | `tests/test_live_network.py` (`NAVIGATOR_LIVE_TESTS=1 pytest -m live`), `example.com` only | 3 passed: real TLS fetch through `Fetcher`, robots.txt consulted, loopback/metadata addresses refused with the real resolver |
| local loopback server | `tests/test_http_transport.py` | redirects not followed, size limit on declared and streamed bodies and **after decompression**, timeout, refused connection, no request reaches the server for a blocked URL |
| real network | `fetch` of the 10 configured sources (details in section 3) | 8 sources fetched (HTTP 200), 2 UBC pages HTTP 403 |
| same | `pipeline --mode live` twice | 33 created, then 33 unchanged; exit code 3 (partial: UBC failed) |
| same | `serve --mode live` + `smoke_test.py --expect-mode live`; `GET /opportunities`; `POST /match` | smoke passed; 33 records, none `is_demo`; match works and does not echo the profile |
| Linux sandbox (no web stack) | `unittest discover` of the earlier tree | superseded by the Windows runs above |

## 3. The real run (what the real pages showed)

| source | result |
| --- | --- |
| ISC bursaries index | HTTP 200, 192 KB. The adapter read **540 of 540** declared entries (coverage 100%, no pagination, the "update in progress" notice was seen). These are discovery entries only. |
| ISC directory detail pages | The index links use `http://` and a different path prefix than the adapter assumed, so none was followed until fixed. Now: https, only rows whose province is British Columbia or National, 25 pages fetched (HTTP 200) -> **25 records** |
| SFU Indigenous scholarships and awards | HTTP 200. A real table of 8 awards with values plus a "Minimum Requirements" list. A curated mapping with verbatim quotes gives **8 records** (`data/curated/sfu_indigenous_awards.yaml`). The first attempt was rejected by the validator (wrong amount field, wrong type) - the checks work. |
| Indspire funding portal | HTTP 200 but the page is an alphabetical **list of donors**, not of awards. The adapter's assumption was wrong, and it produced a bogus record from a donor page (`AbbVie Corporation`) before the page budget was fixed and the snapshot removed. The source now has `max_pages: 1`: donor pages are not followed and there is **no parser for them**. |
| Indspire apply-now, ISC PSSSP / Inuit / Métis strategy pages, MNBC STEPS | HTTP 200; stored; **no curated mapping written yet** -> reported as pending, 0 records |
| UBC award descriptions / context | **HTTP 403** (automated access refused) -> 0 records |

**Quality of the 33 records.** The 8 SFU records have amounts, structured rules (identity, institution, level, full-time) and two `unknown` rules
the page does not define ("good academic standing", demonstrated community involvement); the deadline is only "Fall term each year"
(`unspecified`). The 25 ISC records say, in their own summary, that they come from the directory (each page carries its own "Date modified";
11 of them say 2022), have **no deadline and no application steps**, keep the eligibility text unstructured, and point to the provider's
website. In `POST /match` all 33 therefore come back as `needs_provider_confirmation` for a First Nations, full-time SFU undergraduate:
nothing is presented as a confirmed fit.

## 4. Findings of the real runs (all fixed unless marked open)

1. Migrations did not create the SQLite folder; `alembic_version` was never committed (a `PRAGMA` before `context.configure()`). Fixed.
2. The CLI never released SQLite connections (a Windows file lock); `typer.get_current_context` does not exist in Typer 0.27. Fixed with a context manager.
3. Tests shared one relative SQLite file. Fixed.
4. Time-zone rules change: `tzdata 2026.5` keeps British Columbia on UTC-7 from November 2026, an older system database does not. The pinned `tzdata`
   is preferred; a stored `deadline_at_utc` within two hours of the recomputation is a warning, not an error.
5. The page budget was global, so the first source (ISC, hundreds of links) starved the rest, and links refused by the URL policy used up the
   budget. Now each source gets a fair share (`max_pages // sources`) or its own `max_pages`; refused links are free; pages reused by `--resume` count.
6. ISC index links are `http://`; with an unreadable robots.txt the fetcher correctly refuses, so the adapter now upgrades them to https.
7. **Open:** a rerun with the same run id (same `--as-of` day) can leave an older `data/quarantine/<run_id>.jsonl` behind. A clean-up inside
   `write_quarantine` was tried and reverted: the pipeline writes it twice per run id. Clean it at the start of a run instead.
8. **Open:** the validator proves that a quote exists in the stored snapshot, not that the interpretation is right (for example "Canadian
   Indigenous" is read as First Nations, Inuit or Métis). That is what `human_reviewed` is for.
9. A console showing `M??tis` is only the Windows code page: the stored text has no U+FFFD and "Métis" is intact.

## 5. Acceptance table

| item | state | evidence / what is missing |
| --- | --- | --- |
| Environment and architecture rebuilt | **Verified (Windows)** | fresh venv from the exact lock, 241 tests, ruff clean |
| Core configuration rebuilt | **Verified (Windows)** | resolver and loader tests, Alembic upgrade, `/health` on the real app in both modes |
| From an empty directory | **Verified (Windows)** | new folder, new venv from `requirements.lock`, editable install, migrations, demo pipeline twice, serve, smoke. Not run: Linux/macOS, Python 3.11 |
| No network / no key | **Verified** | tests and the demo pipeline need neither; live needs the network and no key |
| Traceable import | **Verified, including real pages** | quotes checked against the stored real snapshots; forged/moved/mis-hashed evidence rejected; evidence persisted and re-exported |
| Idempotency and transactions | **Verified** | live pipeline twice: 33 created then 33 unchanged; a failing batch leaves no rows; dry-run writes nothing |
| Data semantics | **Verified by tests and the real SFU table** | unknown vs zero, deadline kinds, time zones and rule changes, pooled/maximum amounts, preferences, OR rules, shared forms, funder conditions, conflicts |
| Three demonstrations | **Verified through the real FastAPI app** | tests and `smoke_test.py` against uvicorn (demo and live) |
| Live data | **Partly achieved: 33 real records, with the caveats of section 3** | UBC blocked (HTTP 403); 25 records are dated directory entries; ISC channel pages, MNBC and Indspire donor pages are not mapped yet |
| Data isolation | **Verified** | live database separate; the live run did not touch the demo database; no `is_demo` record in the live export |
| Recovery | **Verified, including on the real network** | the live pipeline rerun downloaded nothing new except the two UBC retries (`attempted` 0 for every other source); scripted-transport failure tests; failed fetch never replaces a good snapshot |

## 6. Decisions that differ from the brief

1. Candidate records are validated by a framework-free validator driven by the exported JSON Schema (not Pydantic models); Pydantic is used for settings and the API.
2. Evidence `field_path` uses the `cycle_key` token under `/cycles`.
3. `requirements.lock` is an exact set, verified on Windows / CPython 3.12.10 only.
4. No LLM extractor: `EXTRACTION_MODE=llm` is an explicit error.
5. Tests are `unittest` classes (pytest collects them); the `live` marker is real now.
6. Fetching is sequential per host; `FETCH_PER_HOST_CONCURRENCY` is validated but not used.
7. OCR is not performed; scanned PDFs are reported as `ocr_required`.
8. Contradicting official statements are recorded (`conflicts`) but not detected automatically.
9. Conditions on the organisation that receives the funds stay in `eligibility.funder_conditions`.
10. One time-zone database: the pinned `tzdata` package is preferred over the operating system's.
11. ISC directory entries stay discovery-only in `data/discovery`; only their detail pages are promoted to records, with the limits stated in each record's summary.

## 7. Where to resume

* Runs: `data/runs/<run_id>.json`; fetch audit: `data/discovery/fetch_audit.jsonl`; index: `data/discovery/fetch_index.json`;
  quarantine: `data/quarantine/`; reports: `data/reports/freshness.json` and `.md`; export: `data/awards.jsonl`.
* Contract and examples: `docs/DATA_MODEL.md`, `docs/schemas/`, `examples/`. Operations: `docs/RUNBOOK.md`. Sources and terms: `docs/DATA_SOURCES.md`.
