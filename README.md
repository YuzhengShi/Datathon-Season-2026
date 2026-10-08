# Indigenous Student Funding Navigator (backend)

A backend that helps First Nations, Inuit and Métis students find scholarships, bursaries and funding channels they may
qualify for, **shows the evidence and the official source for every fact, and says plainly what it does not know**.
It returns explainable rule outcomes (`potential_fit`, `needs_information`, `needs_provider_confirmation`,
`not_eligible`) - never an award probability and never an administrator's decision.

Two data paths, never mixed:

* **demo** - 25 clearly synthetic opportunities with synthetic HTML/PDF sources. Works offline, no API key. Every demo
  response says `"data_mode": "demo"`.
* **live** - bounded, polite fetching of official public pages (see `sources.yaml`). Real data only.

## 1. Problem evidence

**The problem.** Funding for Indigenous post-secondary students is spread across governments, institutions, foundations
and community administrators, each with its own rules, cycles and application route. A student has to find the right
page, work out which conditions really apply to them, and notice what the page does *not* say.

**What we have actually observed** (not interviews - see below):

* The federal *Indigenous Bursaries Search Tool* page (observed 2026-10-07 as page text through a web fetch; no raw HTML
  snapshot was stored, and the live structure has not been re-verified by this build) says it lists **538** bursaries,
  scholarships and incentives, and carries an *"Update in progress"* notice telling students to confirm that the listed
  information is accurate by contacting each organization.
* The listing is a flat table with five columns - name, province/territory, institution, field of study, Indigenous
  group. **No amount, deadline or eligibility appears in the table**; those are on detail pages.
* The same award name repeats per institution (for example one Métis student bursary program is listed once for each of
  many institutions), so a student cannot tell entries apart by title alone.
* Other pages seen in search results describe the tool's size inconsistently (522, 538, 540 and "more than 750"). The
  count changes over time; a count is an observation, not a target.

**What we do NOT have.** No student interviews, surveys, usage data or feedback were collected for this build, and none
are claimed. Nothing here has been reviewed by a funder, administrator or student. Treat the above as desk observations
of public pages, to be checked with real users.

**How the design answers what was observed.** Directory entries are kept as *discovery* data and are never presented as
verified awards. Each amount, date, condition, document and application route needs a quoted passage that exists in a
hashed snapshot of the official page. Unknown stays unknown (unknown is never zero or "no restriction"). Shared
application forms are modelled without merging the awards' eligibility.

## 2. Data evidence

| Dataset | Records | Real? | How it was produced |
| --- | --- | --- | --- |
| demo (`data/demo/`) | 25 (23 awards, 1 funding channel, 1 collection) | **No - synthetic** | `pipeline --mode demo`: synthetic snapshots -> evidence-quoted candidates -> validation -> import -> export |
| live (`data/`) | **33 real opportunities** | Yes | Fetched on the real network and verified quote by quote; see HANDOFF section 3 for what each source gave (and what it did not). Target 20-30. |

Nothing synthetic was used to fill the live numbers. `sources.yaml` lists the ten official entry points. Source adapters
exist for the ISC discovery index, UBC-style sectioned pages, listing/detail pages (Indspire funding) and policy/context
pages, plus an evidence-checked *curated mapping* for the free-text sources (SFU, MNBC, ISC channels). They were tested
on **synthetic structural fixtures only**; whether they fit the real pages is unverified (docs/HANDOFF.md).

What is checked for every record (`navigator.ingestion.validation`): JSON Schema; ids and URLs; deadline/amount/rule
semantics; every cited quote found in the cited paragraph/page of the stored text; SHA-256 of the raw file and of the
extracted text recomputed; path-traversal rejection; demo/live separation; status rules (`machine_checked` is parser +
validation, **not** human review).

## 3. What we are taking into Build Session 2

### Run it (from an empty folder, with network access for `pip`)

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

Windows without activating: use `.\.venv\Scripts\python.exe` in place of `python` everywhere above. In a **second**
terminal (server still running): `python scripts/smoke_test.py --base-url http://127.0.0.1:8000 --expect-mode demo`.
API docs: http://127.0.0.1:8000/docs. Full commands, live runs, resume/refresh and troubleshooting:
[docs/RUNBOOK.md](docs/RUNBOOK.md).

### Honest status (details and the acceptance table: [docs/HANDOFF.md](docs/HANDOFF.md))

* **Verified (Windows, CPython 3.12.10, fresh venv from the exact `requirements.lock`):** 241 tests pass, including the database, API and
  command-line suites; ruff is clean; the demo flow, the real FastAPI server and `scripts/smoke_test.py` work in demo and live mode; the real
  HTTP transport was exercised against a local server and, once, the real network (`example.com`).
* **Real data: 33 opportunities** (8 from a curated mapping of SFU's awards table, 25 from the dated ISC directory). The ISC ones have no
  deadline and only free-text eligibility; all 33 come back as `needs_provider_confirmation` in `/match`. **UBC returned HTTP 403** to the
  automated client and was not worked around. Site terms are unreviewed (`access_status: unreviewed`).
* **Not verified:** Linux/macOS, Python 3.11, PostgreSQL; a human review workflow; mappings for the ISC channel pages, MNBC and the Indspire
  donor pages. The LLM extractor is intentionally not implemented.

A ready-to-paste task for the next session (verify and fix the unexecuted layers, then real data): [docs/NEXT_SESSION_PROMPT.md](docs/NEXT_SESSION_PROMPT.md).

### Exit codes

`0` success - `1` data/validation/test failure - `2` bad arguments or configuration - `3` an external source was
unavailable or the live run did not reach its target (partial). Records waiting for verification are normal: they appear
in the manifest and report, not as errors.

### Decisions the team needs to make

1. Who reviews site terms of use for each source (and when `access_status` may become `reviewed_ok`).
2. Who writes/reviews the curated mappings and what counts as "human reviewed".
3. How the frontend should present `needs_provider_confirmation` (it is the honest answer for most free-text sources).
