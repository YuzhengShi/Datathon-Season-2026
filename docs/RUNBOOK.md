# Runbook

All commands run from the project root. `python` means the project's virtual-environment interpreter. On Windows you can skip
activation and call `.\.venv\Scripts\python.exe` instead of `python`. Nothing here needs administrator rights or a changed
PowerShell execution policy (activation is optional).

## 1. Install and verify offline

```bash
python -m venv .venv
# macOS/Linux: source .venv/bin/activate        Windows PowerShell: .\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.lock
python -m pip install --no-deps -e .
python -m navigator.cli pipeline --mode demo --as-of 2026-10-07
python -m pytest -q
python -m ruff check .
python -m ruff format --check .
python -m navigator.cli serve --mode demo --host 127.0.0.1 --port 8000
```

* `pip install` needs network access once; every other step in this section works offline and needs no API key.
* `pipeline --mode demo` creates the demo database with Alembic, writes synthetic snapshots, validates, imports, exports to
  `data/demo/awards.jsonl` and writes the reports. Re-running it changes nothing (`unchanged: 25`).
* If `ruff format --check` reports differences, run `python -m ruff format .` once (the code was not formatted by ruff when it
  was written) and commit the result.
* `requirements.lock` holds compatible *ranges*, not exact pins. After the first green run: `python scripts/freeze_lock.py`.

**Two terminals.** Terminal 1 runs `serve` (stays in the foreground). Terminal 2 runs the smoke test:

```bash
python scripts/smoke_test.py --base-url http://127.0.0.1:8000 --expect-mode demo
```

The smoke test uses only the standard library, needs no internet, loads the three demo requests from `examples/requests`,
and exits 0 only if every check passes. API documentation: `http://127.0.0.1:8000/docs`.

## 2. The three demonstrations (through the API)

Request bodies are in `examples/requests/`; real excerpts of the engine's answers are in `examples/expected/`. Post one with
any HTTP client, for example (PowerShell: `Invoke-RestMethod -Method Post -ContentType application/json -InFile examples/requests/1_supported_match.json http://127.0.0.1:8000/match`):

| # | request file | what to look for |
| --- | --- | --- |
| 1 | `1_supported_match.json` | `demo_supported_award`: `eligibility_result: pass`, `match_status: potential_fit`, `availability_status: open`, evidence quotes for each rule |
| 2 | `2_needs_clarification.json` | `demo_clarification_award`: `needs_information`, `missing_profile_fields: ["study_status"]`, a question about full-time/part-time |
| 3 | `3_shared_application.json` | `group_by_application: true`: group `demo_foundation_shared_form` holds two awards **matched separately** (one `potential_fit`, one `not_eligible`); the Leadership Award is its own group with `group_id: null` |

The profile is used for the call only: it is not stored, logged or echoed.

## 3. Live data

```bash
cp .env.example .env        # then set USER_AGENT=...(+mailto:you@example.org)
python -m navigator.cli db upgrade --mode live
python -m navigator.cli fetch   --mode live --sources sources.yaml --max-pages 50 --resume
python -m navigator.cli extract --mode live --resume
python -m navigator.cli validate --input data/candidates/awards.jsonl --artifact-root data
python -m navigator.cli import-data --mode live --input data/candidates/awards.jsonl --artifact-root data --dry-run
python -m navigator.cli import-data --mode live --input data/candidates/awards.jsonl --artifact-root data
python -m navigator.cli export --mode live --output data/awards.jsonl
python -m navigator.cli report --mode live --as-of 2026-10-07
# or everything at once:
python -m navigator.cli pipeline --mode live --limit 30 --max-pages 50 --resume
```

* Bounded: depth <= 2, `--max-pages` per run (default 50). `--limit` caps how many opportunities are imported.
* `--resume` skips pages that already have a snapshot; failed pages are retried. `--refresh` re-checks stored pages with
  conditional requests (`304` reuses the snapshot). A changed extractor version only re-runs extraction.
* Terms of use: see `docs/DATA_SOURCES.md`. Review them before the first real run.
* `data/awards.jsonl` is written only when there is at least one published real record.

### Exit codes

| code | meaning |
| --- | --- |
| 0 | success |
| 1 | data / validation / test failure (a rejected record, a failed batch, invalid candidates) |
| 2 | bad arguments or configuration (unknown mode, unsafe DB settings, database not migrated, bad `--as-of`) |
| 3 | an external source was unavailable, a page budget was hit, or the live run did not reach 20 published real opportunities - a *partial* run |

Items waiting for verification (`pending`, `ocr_required`, unreviewed terms, unstructured conditions) are normal findings.
They are listed in the run manifest and the freshness report; they do not by themselves make a run fail.

## 4. Recovery after an interruption

* Every run writes `data/runs/<run_id>.json` (demo: `data/demo/runs/`) after each step: parameters, completed steps,
  per-source status, counts, artifact paths + hashes, failures, pending items.
* `data/discovery/fetch_index.json` + `fetch_audit.jsonl` are rewritten atomically after every page. Raw files are
  content-addressed and never overwritten; a failed fetch never replaces a good snapshot.
* Just re-run the same command with `--resume`. Bad candidates are in `data/quarantine/<run_id>.jsonl` (line, id, field,
  error type, summary). Nothing is deleted automatically.
* Writes use temp-file + atomic rename; a failed parse or report never empties published data.

## 5. Import behaviour

* Default: validate everything first; any invalid record -> nothing is written (exit 1).
* `--allow-partial`: per-record transactions; valid records are committed; exit is still 1 if anything was rejected.
* `--dry-run`: real parsing, evidence/hash checks, conflict detection and diffs; no database or export writes.
* Re-importing unchanged data reports `unchanged` and changes nothing. Updating the current cycle keeps older cycles.
* An older snapshot never overwrites newer content (`pending_review`). Records absent from an input are never deleted.

## 6. Database

SQLite by default. For PostgreSQL install the extra (`python -m pip install -e ".[postgres]"`) and set
`DATABASE_URL=postgresql+psycopg://user:pass@host/dbname`. Schema changes go through Alembic only; `python scripts/check_static.py`
compares the models with the hand-written migration. `DEMO_DATABASE_URL` must differ from `DATABASE_URL` (the resolver refuses otherwise).

## 7. Troubleshooting

| symptom | likely cause / fix |
| --- | --- |
| exit 2 "database is not migrated" | `python -m navigator.cli db upgrade --mode <mode>` |
| exit 2 "DATABASE_URL and DEMO_DATABASE_URL must differ" | give demo its own file/URL |
| `/health` says `degraded` | migrations not at head; run `db upgrade` for that mode |
| smoke test: data_mode mismatch | the server was started in another mode: `serve --mode demo` vs `--expect-mode demo` |
| live run exits 3 | read the manifest `failures` and the freshness report `source_failures`; usually network, robots, or a page budget |
| `fetch` blocked `robots_unavailable` | the site's robots.txt returned a server error; retry later (never bypass) |
| a PDF shows `ocr_required` | it has no text layer; OCR is not performed in this build |
| import rejected everything | open the quarantine file for the first error; one bad record rejects the batch unless `--allow-partial` |
| `pytest` skips many tests | the web/database stack is not installed in that interpreter |
| `WinError 10013` when serving | Windows reserved that port; choose another (`--port 8080`) |
| `PermissionError` on `navigator.db` (Windows) | a server or Python process still holds the SQLite file; stop it |
| HTTP 403 from a source | the site refuses automated clients: stop, record it, do not change the User-Agent to get around it |
| a deadline differs by an hour between machines | the project prefers the `tzdata` package pinned in `requirements.lock` (`NAVIGATOR_SYSTEM_TZ=1` uses the OS copy) |
| warning `deadline.utc_tz_rules_changed` | the stored UTC instant was computed with older time-zone rules; matching recomputes it; re-run the pipeline |

## 8. What has and has not been run

See [HANDOFF.md](HANDOFF.md): it lists, command by command, what was executed and what was written but not run.

## Pages that refuse automated access (HTTP 403)

Some sites (for example `students.ubc.ca`) answer an automated client with HTTP 403. The project does not work around that: no
changed User-Agent, no retries, no headless browser. If you can open the page in your own browser, a person may save it and import
it with its provenance:

1. Open the exact page in a browser, then *File > Save page as...* ("Webpage, HTML only") or save the PDF.
2. `python -m navigator.cli import-snapshot --source ubc_award_descriptions --url "<the page address>" --file "<saved file>" --saved-by "<your name>"`
3. `python -m navigator.cli extract --mode live`. Write the curated mapping with verbatim quotes as for any other page, and say in the
   record's summary that the page was saved by a person on a given date.

The snapshot is stored like a fetched one; the fetch index records `acquisition: manual_upload` and who saved it, the audit log gets a
`manual_import` row, the source's allowlist still applies, and every evidence check runs unchanged. Ask the site for permission before
relying on it for more than a handful of pages.

## The site, Statistics and AI search (application layer)

One server runs everything: `python -m navigator.cli serve --mode live` (or `.\scripts\start_app.ps1`), then open `http://127.0.0.1:8000/`.

| URL | What |
| --- | --- |
| `/` | the site in `dist/`: Explore, Statistics, My saved, AI search ("Find a match", "Ask about the data") |
| `/app/` | the questionnaire app in `frontend/` (talks to `/opportunities` and `/match`) |
| `/api/*`, `/data/opportunities.json` | the application layer: typed search, statistics, evidence check, AI conversation, and the records the site loads |
| `/docs` | OpenAPI for all of it |

* **One mode, one `.env`.** `DATA_MODE`, `DATA_DIR` and `CORS_ALLOW_ORIGINS` are read once for both layers and `--mode` beats `DATA_MODE`. The site
  loads its records from `/data/opportunities.json`, which the server answers from the read model of the same mode as `/api/*`: a page can never show
  one mode's records and call another mode's API.
* **The read model** is a second SQLite file per mode (`data/read_model.db`, `data/demo/read_model.db`) with its own migrations in `migrations_app/`.
  `serve` brings it up to date when it starts (migrate, then an idempotent import: `data/awards.jsonl` in live mode, the four demo records in demo mode).
* Commands:

```powershell
python -m navigator.cli app status --mode live     # read model, record count, AI settings (never the key), and whether dist/data/opportunities.json agrees with the mode
python -m navigator.cli app upgrade --mode live    # create or upgrade the read model's database
python -m navigator.cli app publish                # data/awards.jsonl -> live read model AND dist/data/opportunities.json (static hosting)
python -m navigator.cli app init-demo              # the four illustrative demo records -> demo read model
```

  `app publish` is the only command that rewrites `dist/data/opportunities.json`; a test fails when the committed file lags behind
  `data/awards.jsonl`. Add `--no-frontend` to skip that file, `--dataset <file>` to publish another export.
* **Region.** A record is regional when its rules name a school or a province, and regional or national when the federal directory lists it so
  (`Province/territory:` in the entry). Otherwise its region is *not stated*: Statistics counts it separately and never as national.
* **AI search** needs `LLM_ENABLED=true`, `OPENAI_MODEL` and `OPENAI_API_KEY` in `.env` (`OPENAI_BASE_URL` for an OpenAI-compatible provider such as
  `https://api.deepseek.com/v1`). The assistant uses the Responses API; `docs/LLM_PROVIDERS.md` records what was verified. Without these settings the
  page says AI is not connected and the filters and Statistics keep working. Probe a provider with `scripts/probe_deepseek.py` and `scripts/probe_deepseek_tools.py`.
* **Static hosting** serves only `dist/` (no Python): run `app publish` first. Statistics then computes in the browser and AI search is off.
* Checks: `python -m pytest -q`; `node scripts/qa-ui.cjs` (jsdom; `npm install --no-save --package-lock=false jsdom@30.1.2` first);
  `python scripts/app_verify_runtime.py` starts a demo server (on a free port) and smoke-tests its HTTP routes;
  `node tests/e2e/site.mjs --base=http://127.0.0.1:8000 --out=shots` drives the site in a real Chrome or Edge against a running `serve --mode live`
  (numbers on the Statistics page checked against the published dataset, a directory entry, a 390 px phone; add `--ai` for one natural-language search,
  which makes a few real model calls on the configured key).
* The site is plain HTML, CSS and JavaScript with no build: edit a file in `dist/` and reload. Python (`navigator/app/services.py`) and JavaScript
  (`dist/model.js`) filter the same way; `tests/test_filter_parity.py` fails when they drift apart.

## The questionnaire app (`/app/`)

* The app is the folder `frontend/`: edit a file and reload, there is no build. `model.js` holds every rule that turns API data into words
  (amounts, deadlines, fit, sorting); change it together with `tests/js/model.test.mjs`.
* Checks: `python -m pytest -q` (includes the JavaScript logic tests), and the real-browser run
  `node tests/e2e/smoke.mjs --base=http://127.0.0.1:8000 --out=shots` (use `--chrome="<path to chrome.exe or msedge.exe>"` if the default path is wrong;
  it writes screenshots to `shots/`). It fails on any JavaScript error, sideways scrolling on a 390 px phone, stored data or an unnamed control.
  **Stale since the frontend redesign:** it was written for the earlier routes (its second step looks for `#/start/1`, which no longer exists), so it stops after
  the first check. It needs updating to the redesigned app before it can be relied on again.
* `/app/` is served with a strict Content-Security-Policy (no inline scripts or styles, no third-party hosts). Keep it that way: do not add CDN links.
  The site at `/` is not under that policy because its charts use inline styles.
* A contact address for corrections goes in `frontend/config.js` (`contactEmail`); the crawler's contact goes in `USER_AGENT` in `.env`.

## Build Session 3: every province, the map and the leftovers

**Reading the whole federal directory.** `sources.yaml` gives the directory source a page budget of 600 (the index page plus one detail page per row; 540 rows on
2026-10-05). Run `python -m navigator.cli pipeline --mode live --limit 1000 --max-pages 700 --resume`: about 540 polite requests at one per second, roughly ten
minutes the first time. `--resume` reuses stored pages, so later runs need no network (about 30 seconds). Do not open `data/discovery/fetch_audit.jsonl` while a
run is fetching: on Windows the audit file is replaced after every request and a reader can make the replace fail (the writer now retries for about ten seconds,
but a program that keeps the file open longer still stops the run).

**What the directory adapter does with the rows.**

* Repeated listings of the same award by the same provider (one Métis bursary is listed about forty times) become one record. The listing with the smallest id is
  kept, so the choice does not depend on fetch order; the number merged is in the source summary (`repeated_listings_merged`).
* A page without "Provider Name" uses its "Contact Organisation" (the summary says so). A page with neither stays pending.
* The directory's "Indigenous group" column is added to the summary ("Indigenous group: Métis.") and `navigator app publish` reads it to set the community;
  "Province/Territory" sets the region, and "National" and "Any Location" both count as across Canada. None of them is an eligibility rule.
* A directory entry whose title equals a curated provider-page record's title, and whose provider name contains the other's, is replaced by the provider-page
  record (`data/discovery/superseded_directory_records.json`). If the directory entry was imported earlier, rebuild the database (below).

**Exit codes.** A normal live run still exits 3 when a few provider sites cannot be read (robots.txt unavailable: camosun.ca, langara.bc.ca). That is a source
failure, not a data failure: the import reports `rejected: 0`.

**Rebuilding the live database from the saved pages (offline).** Stop every server that has `data/navigator.db` open (Windows will not delete it otherwise), delete
`data/navigator.db`, and run the pipeline command above twice: the first run creates every record, the second must report all of them unchanged. Then run
`python -m navigator.cli app publish`.

**A leftover `backend/` folder overwrites the site's data.** Before the application layer was merged into the main package (`navigator.app`) its code lived in
`backend/`. If an old, untracked copy is still on disk, starting its server (or its `publish`) rewrites `dist/data/opportunities.json` in the old format.
`tests/test_app_publish.py::test_the_committed_static_dataset_matches_what_publish_writes` fails when that happens; `python -m navigator.cli app publish` restores
the file. Delete the folder if it is there.

**Checks of the site.** `node scripts/qa-ui.cjs` (simulated DOM, 44 checks, including the map, the tiles, the ranking and the amounts);
`node tests/e2e/site.mjs --base=http://127.0.0.1:8000 --out=shots` (real Chrome with screenshots; `--ai` adds one real model search); `node --test tests/js/`
(the numbers behind the map are in `tests/js/regions.test.mjs`, the wording of amounts in `tests/js/amounts.test.mjs`).
