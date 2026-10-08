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
