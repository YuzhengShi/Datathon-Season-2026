# Handoff

*Updated after the provider-page verification run (October 2026). Every statement says where it was run.*

## 0. Read this first

* **Verified environment:** Windows, CPython 3.12.10, a fresh virtual environment installed from the exact `requirements.lock`.
  **Not verified:** Linux/macOS, Python 3.11, PostgreSQL.
* **Tests:** 258 pass (database, API and command-line suites included); 3 `live` tests (off by default) passed on the real network
  against `example.com` only, in the previous session. `ruff check`, `ruff format --check` and `scripts/check_static.py` are clean.
* **Real data: 37 records** in the live database (36 published, 1 archived), exported to `data/awards.jsonl`:
  8 SFU awards (curated from a real table), 4 funding channels (ISC PSSSP, ISC Inuit strategy, ISC Métis Nation strategy, MNBC STEPS),
  **7 awards verified on the provider's own page** (one of them archived because the provider says it is paused), and 18 awards that
  still rest only on the dated ISC directory page. Read section 3.
* **UBC is still missing** (HTTP 403 to an automated client). Decision and tools: section 4.
* Every record is `machine_checked` (each quote was found in the stored snapshot); none is `human_reviewed`. The project owner authorised
  fetching on 2026-10-07; robots.txt was honoured, one request per second per host. `access_status` in `sources.yaml` is still `unreviewed`.

## 1. First actions

1. `python -m venv .venv`, `python -m pip install -r requirements.lock`, `python -m pip install --no-deps -e .`
2. `python -m pytest -q` (expect 258 passed), `python -m ruff check .`, `python -m ruff format --check .`, `python scripts/check_static.py`
3. Demo: `python -m navigator.cli pipeline --mode demo --as-of 2026-10-07` twice (25 created, then 25 unchanged); `serve --mode demo` and
   `python scripts/smoke_test.py --base-url http://127.0.0.1:8000 --expect-mode demo` (29/29).
4. Live: the real snapshots are in `data/raw`/`data/text`; `python -m navigator.cli pipeline --mode live --limit 60 --max-pages 80 --resume`
   reuses them (37 created on an empty database, then 37 unchanged). Set a real contact in `USER_AGENT` before any larger run.

Next work for a coding agent: [NEXT_SESSION_PROMPT.md](NEXT_SESSION_PROMPT.md).

## 2. What was run where (this session)

| what | result |
| --- | --- |
| curated mappings for ISC PSSSP, Inuit strategy, Métis strategy and MNBC STEPS (quotes from the real pages) | 4 records, all verified on the first try |
| `scripts/provider_sources.py`: one start-page source per distinct provider link of the 25 ISC directory records (`sources.providers.yaml`) | 20 generated; `students.ubc.ca` and the record without a link skipped |
| real fetch of those 20 pages | 12 fetched (HTTP 200); **4 answered 403** (Sauder/UBC, FNIGC, langara.ca, NWAC) - removed from the file and never retried; 2 refused for an unreadable robots.txt (Camosun, www.langara.bc.ca); 2 VIU pages redirected to `viu.ca`/`services.viu.ca` (allowlist widened to the same institution; one fetched, one still blocked by robots) |
| curated mappings read from 7 provider pages | 7 records verified; each **replaces** the directory record with the same id (`data/discovery/superseded_directory_records.json`) |
| `pipeline --mode live` twice | 37 created, then 37 unchanged; 36 exported (the archived one is not published) |
| `serve --mode live` + `smoke_test.py --expect-mode live` | passed |
| `POST /match` for a First Nations, SFU, full-time BC undergraduate | 36 results: 33 `needs_provider_confirmation`, 3 `not_eligible` (the Inuit strategy, the Métis strategy and MNBC STEPS - correctly); the archived record is absent |

## 3. What the provider pages changed (the point of verifying)

| award | directory said | the provider's own page says |
| --- | --- | --- |
| First Citizens Fund Student Bursary Program | an active bursary | **paused until further notice** (funding cuts) -> `archived`, not shown to students |
| Nutrien Indigenous Youth Financial Management Awards | no deadline | **open until 2026-11-23**, scholarship of up to $5,000 |
| Gillis Purcell Memorial Journalism Scholarship | no deadline | **$4,000, due Nov. 1 every year**; eligibility in the page's own words |
| Cenovus Indigenous Scholarships (Indspire portal) | varies | **deadlines August 1, November 1, February 1**; full-time; listed fields of study |
| Chief Roy Mussell Bursary (Fraser Basin Council) | $1,000 | 2025-26 **closed**; applications open again in fall 2026; age 17-30, BC |
| First Nations Home EnergySave Learning Grants | up to $1,000 | **fully allocated**; applications re-open mid-November 2026 |
| First Nations, Inuit and Métis Nurse Education Bursary (RNFBC) | $1,500 | BC nursing students; randomized draw; the page states no amount and no deadline |

Directory pages carry their own "Date modified": 2012 to 2025. The 18 records that rest only on a directory page say so in their summary.
**Pages fetched but not mapped yet:** BC Hydro (the link now lands on a general page that does not name the award), Capilano (the page text is
empty: it is rendered by JavaScript), UBC Forestry and UBC iSchool (the award is only a name in a list), UNBC (a generic resources page),
VIU `services.viu.ca` (114 KB list of awards; three ISC records point to it).

## 4. UBC: decision

`students.ubc.ca` (two pages) and the Sauder School page answer an automated client with HTTP 403 (the iSchool and Forestry pages were reachable). **Decision: do not work
around it** (no changed User-Agent, no retries, no headless browser). Instead:

1. Ask UBC. Two ready-to-send drafts were prepared: a full request (low-volume access / an official data source / manual use) and a short
   one (may a person save the pages and quote excerpts with attribution?). They are not in the repository; they need the sender's contact details.
2. Meanwhile the system supports a human route: `python -m navigator.cli import-snapshot --source ubc_award_descriptions --url "<address>" --file "<saved page>" --saved-by "<name>"`
   stores a page that a person saved in their own browser. The index records `acquisition: manual_upload` and who saved it and when, the
   audit log gets a `manual_import` row, the allowlist still applies and every evidence check runs unchanged (see `docs/RUNBOOK.md`).
   It has been tested with synthetic pages only; **no UBC page has been imported**.
3. Until then UBC is covered only through a few ISC directory entries that mention UBC; the `ischool.ubc.ca` and `forestry.ubc.ca` pages were
   reachable but did not describe the award.

## 5. Findings of the real runs (fixed unless marked open)

1. Migrations did not create the SQLite folder; `alembic_version` was never committed; the CLI never released SQLite connections; tests
   shared one SQLite file. Fixed (earlier sessions).
2. Time-zone rules change (`tzdata 2026.5` keeps British Columbia on UTC-7 from November 2026): the pinned `tzdata` is preferred; a stored
   `deadline_at_utc` within two hours of the recomputation is a warning.
3. The page budget was global and refused links used it up; now per source, refused links are free and pages reused by `--resume` count.
4. Indspire's funding portal is a list of **donors**; its adapter produced a bogus record from a donor page before the budget was fixed.
   Donor pages are not followed (`max_pages: 1`) and there is no parser for them.
5. The supersession of a directory record by a provider record happens **after** both are verified (a first version did it before and
   lost three awards when their provider records were rejected for wrong field names).
6. The static checker flagged an f-string format spec (`:<5`) as a placeholder-less f-string; the checker was fixed, not the code.
7. **Open:** a rerun with the same run id can leave an older `data/quarantine/<run_id>.jsonl` (the pipeline writes it twice per run id).
8. **Open:** the validator proves that a quote exists in the stored page, not that the interpretation is right (for example "Canadian
   Indigenous" read as First Nations, Inuit or Métis; "Open until 2026-11-23" read as open from the day it was observed). That is what
   `human_reviewed` is for.
9. **Open:** a record whose rule is `unknown` can only be `needs_provider_confirmation`, never `potential_fit`: that is the intended
   behaviour, and it means no SFU or provider record is presented as a confirmed fit.

## 6. Acceptance table

| item | state | evidence / what is missing |
| --- | --- | --- |
| Environment and architecture rebuilt | **Verified (Windows)** | fresh venv from the exact lock, 258 tests, ruff clean |
| Core configuration rebuilt | **Verified (Windows)** | resolver and loader tests, Alembic upgrade, `/health` on the real app in both modes |
| From an empty directory | **Verified (Windows)** | new folder, new venv from `requirements.lock`, editable install, migrations, both pipelines twice, serve, smoke. Not run: Linux/macOS, Python 3.11 |
| No network / no key | **Verified** | tests and the demo pipeline need neither; live needs the network and no key |
| Traceable import | **Verified, including real pages** | every quote checked against stored real snapshots (SFU, ISC channels, MNBC, 7 provider pages); forged/moved/mis-hashed evidence rejected |
| Idempotency and transactions | **Verified** | live pipeline twice: 37 created then 37 unchanged; a failing batch leaves no rows; dry-run writes nothing |
| Data semantics | **Verified by tests and real pages** | unknown vs zero, deadline kinds (a date, an annual rule, three intakes, rolling, local), paused programmes, amounts as maximum, rules in three-valued logic |
| Three demonstrations | **Verified through the real FastAPI app** | tests and `smoke_test.py` against uvicorn (demo and live); a real live `/match` |
| Live data | **Partly achieved: 37 real records** | 8 SFU + 4 channels + 7 provider-verified + 18 directory-only (dated); UBC missing; 6 provider pages fetched but unmapped (3 more could not be fetched) |
| Data isolation | **Verified** | live database separate; the live runs never touched the demo database; no `is_demo` record in the live export |
| Recovery | **Verified, including on the real network** | `--resume` reuses stored pages; scripted-transport failure tests; a failed fetch never replaces a good snapshot |

## 8. The web app

`frontend/` (plain HTML, CSS and ES modules) is served by the API at `/app/`. Design decisions:

* **A store, not a form.** After five optional questions the student lands on a results page that works like any online store: search on top,
  filters with live counts on the left (a sheet on phones), sort, one card per scholarship with the amount as the "price" and the deadline as the
  "delivery date", then a detail page with a buy box (the apply button) and "My list".
* **Honesty is part of the layout.** Each card carries a source badge ("Checked on the provider's page" or "Government directory entry, year");
  eligibility is shown as "You meet 4 requirements we can check, 2 to confirm with the provider"; an unknown rule is never a fail; a deadline
  without a time zone says so; the detail page quotes the provider's own words with a link and the date they were checked.
* **No answer is stored or shown anywhere** except in memory for the open tab (no cookies, no storage, nothing in the URL).
* **Real data has almost no "potential fit"** (SFU and the providers all have rules only they can judge), so ranking uses how many checkable
  requirements are met and puts directory entries after provider-verified ones.
* Verified: 22 JavaScript logic tests (also run by `pytest`); 5 serving tests (MIME types, CSP, no path traversal, institutions list); a real
  Chrome end-to-end run of 25 checks on a desktop and on a 390 px phone (questionnaire, search, filters, sort, save, list, detail, no stored data,
  accessible names, no sideways scrolling, no JavaScript errors).
* **Not verified:** Firefox and Safari; a screen reader; measured colour contrast (colours were chosen for AA but not measured); French;
  a contact address (`CONTACT_EMAIL` in `frontend/assets/config.js` and the contact in `USER_AGENT` are still empty); the User-Agent text now says what the crawler is for
  and a warning is logged while it has no contact address.

## 7. Where to resume

* Runs: `data/runs/<run_id>.json`; fetch audit: `data/discovery/fetch_audit.jsonl`; index: `data/discovery/fetch_index.json`;
  provider links: `data/discovery/provider_links.json`; superseded directory records: `data/discovery/superseded_directory_records.json`;
  quarantine: `data/quarantine/`; reports: `data/reports/`; export: `data/awards.jsonl`.
* Curated mappings: `data/curated/*.yaml` (SFU, four channels, seven provider pages). Format: `data/curated/README.md`.
* The web app: `frontend/` (served at `/app/`), tests in `tests/js/` and `tests/e2e/`.
* Contract and examples: `docs/DATA_MODEL.md`, `docs/schemas/`, `examples/`. Operations: `docs/RUNBOOK.md`. Sources and terms: `docs/DATA_SOURCES.md`.
