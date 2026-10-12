# Indigenous Student Funding Navigator

**A free funding board for First Nations, Inuit and Métis students in Canada.** Browse scholarships, bursaries and funding programs the way you would browse a store, see where support is across the country on a map, or ask in your own words. Each record shows its amount, its deadline, where the information came from, and what you still have to confirm with the provider.

> **Build Session 3:** the data now covers every province and territory (529 published records, up from 58 that were almost all in British Columbia), and the site has a Statistics page with a map, plus optional AI search. Build Session 2 (the questionnaire app, now at `/app/`) is described in [docs/BUILD_SESSION_2.md](docs/BUILD_SESSION_2.md); the Build Session 1 submission is kept in [docs/build-session-1.md](docs/build-session-1.md). How the application layer is built: [docs/APP_LAYER.md](docs/APP_LAYER.md).

## 1. Idea and choices

**The problem.** Funding for Indigenous students sits in separate systems: PSSSP through First Nations and their organisations, Inuit and Métis programs run by their own governments, institutional awards and private foundations. Each has its own rules, dates and application. The best national lead, the federal [Indigenous Bursaries Search Tool](https://www.sac-isc.gc.ca/eng/1351185180120/1351685455328), lists 540 entries but asks students to confirm everything with each provider, and Indspire covers its own awards. Nothing puts the rules, the dates and the source of each claim in one place, or shows where the support is (evidence in [Session 1](docs/build-session-1.md)).

**What the site does.** *Explore*: search, filters with live counts, sort, one card per record with its amount and deadline, a detail page with the provider's own words and a link to apply, and "My list". *Statistics*: a map of Canada (north at the top, every region labelled with its count, or equal-size tiles), a ranking of all 13 provinces and territories, how many records come from a provider's own page and how many only from the federal directory, how current the sources are, and the main providers. Every chart narrows the others. *AI search* (optional): ask in plain words; the model can only choose among fixed tools over the published records and can only return records that exist. The Session 2 questionnaire app is still at `/app/`. Nothing decides for the student: a condition only the provider can judge is shown as *to confirm*, not as a yes or a no.

**Choices, and the evidence behind them**

| Choice | Why |
| --- | --- |
| Every province and territory, from the source that lists them | The first version followed only British Columbia and national entries of the federal directory (a UBC student's first needs), so 48 of 58 records were in one province. The directory lists all 13 regions; the pipeline now reads every one of its 540 pages. Counts show what the directory and the provider pages list, not what exists. |
| Say where every fact comes from, and how old it is | 486 of the 529 records are federal-directory entries: none states a deadline, and the pages were last changed in 2015 or earlier (235 of all records), 2016–2019 (3), 2020–2022 (207) or 2023 and later (44); 40 state no date. The providers' own pages corrected some directory entries (the Cummins award at Vancouver Island University: $500 in the directory, $1,000 on the university's page) and showed one that is no longer offered (the First Citizens Fund bursary: paused by its provider, so students never see it). |
| Rules and verbatim quotes decide eligibility, not an LLM | A wrong "eligible" costs a student real effort, so each statement is a deterministic parser or a hand-written mapping tied to a quote that the pipeline re-checks against the stored page. The LLM never writes data; it is only used by the optional AI search. |
| The directory's own columns, nothing inferred | Region ("Province/Territory"; "National" and "Any Location" both count as across Canada) and community (the "Indigenous group" column: 155 of 540 entries name one or two groups, not all three) come from the directory as written. They feed filters and statistics, never the eligibility check. |
| Free, no account, answers not stored | Answers live in memory in the open tab. The service does not store the profile. With AI search on, the typed question and the records the tools return are sent to the model provider you configure ([docs/LLM_PROVIDERS.md](docs/LLM_PROVIDERS.md)); with `LLM_ENABLED=false` nothing leaves the machine. |
| Respect the sources | robots.txt, one request per second, a User-Agent that says who we are and why. UBC's pages refuse automated access (HTTP 403): we do not work around it, so UBC awards are missing until UBC agrees. A page that a person saves in a browser can be imported with its provenance. |

Developed with an LLM coding assistant (Claude) under the owner's direction. The data pipeline uses no LLM; the optional AI search does.

## 2. Data and how it supports the result

**The data** is [`data/awards.jsonl`](data/awards.jsonl): 529 published records ([schema](docs/schemas/opportunity-record-1.0.schema.json)), each with provider, official URL, deadline rule, amount, eligibility rules and the quotes that support them (1,781 in total). All of it comes from public web pages, and every province and territory has records:

| Region | Records | Region | Records |
| --- | --- | --- | --- |
| Manitoba | 130 | Northwest Territories | 21 |
| British Columbia | 95 | Nova Scotia | 15 |
| Ontario | 88 | New Brunswick | 7 |
| Alberta | 62 | Yukon | 6 |
| Saskatchewan | 50 | Nunavut | 3 |
| Across Canada | 38 | Quebec | 3 |
| Region not stated | 7 | Newfoundland and Labrador | 2 |
| | | Prince Edward Island | 2 |

| Source | Records |
| --- | --- |
| Indigenous Services Canada: Indigenous Bursaries Search Tool (540 entries, every detail page read; 41 repeated listings of the same award merged, 2 pages that name no provider and no contact organisation not used) | 486 directory entries (11 more were replaced by their provider's own page) |
| Indigenous Services Canada: program pages (PSSSP, the Inuit and Métis Nation post-secondary strategies) | 3 |
| Métis Nation British Columbia: STEPS | 1 |
| Simon Fraser University: Indigenous awards | 8 |
| Vancouver Island University: scholarships and awards database (one shared application) | 25 |
| AFOA Canada, The Canadian Press, Fraser Basin Council (2), Indspire portal (Cenovus), Registered Nurses Foundation of BC | 6 |

**What a directory entry is, and is not.** It is the directory's own record of an award: dated, with no deadline or application steps, read by a machine and checked against the stored page, not reviewed by a person. For 111 of its records the page names no provider, only a contact organisation, which is then shown as the provider. A region count is the number of records that state that region, not a measure of need or of the money available.

**Permission.** Information from Indigenous Services Canada is reproduced under the Government of Canada's non-commercial reproduction terms, with the statement those terms ask for (shown on every affected page and on the About page). For the other providers we use public facts and short quotations with a link back and the date checked, honour robots.txt, and copy no page wholesale; their terms of use have not been read by a person yet (`access_status: unreviewed` in [sources.yaml](sources.yaml)), and the About page gives a contact for corrections or removal. Nothing is taken from sites that refuse automated access. The app collects no personal data.

**How it supports the result.** 257 of 529 records show an amount as one figure (234 fixed, 23 "up to"; 8 more state a range), 28 show a deadline or a yearly rule (4 more say rolling or set locally), and 25 share one application. [`tests/test_export_path.py`](tests/test_export_path.py) loads the dataset into a fresh database without the saved pages and checks that the API serves exactly the dataset's titles, amounts and links, that **every amount and date shown appears in the quote that supports it**, and that the demo student's results are the expected ones; [`tests/test_filter_parity.py`](tests/test_filter_parity.py) checks that the site and the API filter, sort and count about 600 cases the same way. The freshness report is in [docs/freshness-report.md](docs/freshness-report.md).

## 3. Run it locally

You need Python 3.12 (tested with 3.12.10 on Windows) and Git. Optional: Node.js 20+ (JavaScript tests; 22+ for the browser test) and Chrome.

```powershell
git clone https://github.com/YuzhengShi/Datathon-Season-2026.git
cd Datathon-Season-2026
python -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements.lock
.\.venv\Scripts\python -m pip install --no-deps -e .
.\scripts\start_app.ps1        # builds the database from data/awards.jsonl, then opens http://127.0.0.1:8000/ (the site; the questionnaire app is at /app/)
```

On macOS or Linux use `source .venv/bin/activate` and `scripts/start_app.sh` (the Windows script is the one that has been run). If Windows refuses port 8000, add `-Port 8080`. The first start can take a few minutes (Python prepares its packages and the database is built); later starts take a couple of seconds. AI search stays off until `.env` has `LLM_ENABLED=true` and a key (see [docs/LLM_PROVIDERS.md](docs/LLM_PROVIDERS.md)); everything else works without it.

**Data preparation.** None is needed to run: the prepared dataset is in the repository and `start_app` loads it. To rebuild and re-check it from the sources (network access, about 540 polite requests at one per second, roughly ten minutes): copy `.env.example` to `.env`, put your contact address in `USER_AGENT`, then `python -m navigator.cli pipeline --mode live --limit 1000 --max-pages 700 --resume` (`--resume` reuses pages already stored, so a second run needs no network), and `python -m navigator.cli app publish` to refresh the site's data. The hand-written mappings are in [data/curated](data/curated); the Vancouver Island University ones are generated by `scripts/generate_viu_curated.py`. More: [docs/RUNBOOK.md](docs/RUNBOOK.md), [docs/TECHNICAL_README.md](docs/TECHNICAL_README.md).

**Checks.**

```powershell
.\.venv\Scripts\python -m pytest -q                       # 330 tests (includes the JavaScript tests when Node is installed)
node scripts/qa-ui.cjs                                    # 43 checks of the site in a simulated DOM (no browser)
node tests/e2e/site.mjs --base=http://127.0.0.1:8000     # 33 checks of the site in a real Chrome; 36 with --ai (a few real model calls)
node tests/e2e/smoke.mjs --base=http://127.0.0.1:8000    # the questionnaire app; stale since the frontend redesign (see docs/RUNBOOK.md)
```

## 4. Demo path

**Situation.** A student adviser in Manitoba, or a student in any province, asks: where is funding for Indigenous students, and how much of what we can see has been checked on the provider's own page?

**Action.** Start the app, open <http://127.0.0.1:8000/> and choose *Statistics*.

**Result.**
- The first row says 529 records, 13 / 13 regions covered, 38 across Canada, 484 for one region, and 257 with a listed amount.
- The map has north at the top and every region carries its count (Manitoba 130, British Columbia 95, Ontario 88, Alberta 62, Saskatchewan 50 … Prince Edward Island 2). Hover a region for its numbers; switch to *Tiles* to read the small provinces at equal size. The ranking below shows, for all 13 regions, how much comes from a provider's own page and how much only from the federal directory.
- Click Manitoba: every chart narrows to its 130 records, the 38 that apply across Canada and the 7 that state no region. The card on the right lists its communities, how many have a listed figure, its main providers and how old the sources are. *Explore these records* opens them.
- Open a directory entry: it says "As listed in the federal directory", carries the Government of Canada statement and shows the source sentences. Open a Vancouver Island University or SFU record: it was read on the provider's own page, with the quotes that support each amount and date.
- *AI search* (needs a configured model): type "I'm a Métis student in BC looking for training support". The answer lists source-linked records, each a record that exists in the dataset.

**Before and after.** Before: open the federal tool (540 entries, none states a deadline), then each provider's site to find the amount, the date and the rules, with no view of where support is or how old the information is. After: one board with 529 records in all 13 regions, each saying what it pays, when it is due when that is known, whether it was read on the provider's page, and where each fact came from. The Session 2 questionnaire app (`/app/`) still works, but for an SFU student it now lists 501 of the 529 records, most with eligibility the directory does not state; the site is the demo path. A three-minute script is in [docs/DEMO.md](docs/DEMO.md).

## 5. What works now, and what remains before Build Session 3

**Works now.** The dataset ([`data/awards.jsonl`](data/awards.jsonl)), a matching endpoint that returns evidence and flags missing information (`POST /match`), a freshness report ([docs/freshness-report.md](docs/freshness-report.md), `GET /reports/freshness`), the site with Explore, Statistics and AI search, and the questionnaire app, all on Windows (330 Python tests, 43 simulated-DOM checks and 36 real-browser checks pass). AI search was checked through a real model (DeepSeek `deepseek-chat`, [docs/LLM_PROVIDERS.md](docs/LLM_PROVIDERS.md)).

**Remains.** No student interviews or user tests have taken place yet. Everything shown was checked by the builders and by automated tests.
- *Put it in front of people:* deploy it (the site needs the Python service), get feedback from students and advisers, and test matching and AI search on manually labelled pairs.
- *Data:* UBC, which needs UBC's permission; most of the 486 directory entries still to be replaced by provider pages, starting with the thinnest regions (Prince Edward Island 2, Newfoundland and Labrador 2, Nunavut 3, Quebec 3); 5 provider pages fetched but not yet mapped and a few that refuse automated access; a person's review of the 529 records ("machine-checked" is not "reviewed"; none is reviewed yet); reading each provider's terms of use.
- *Product:* what the questionnaire app should do with 486 entries whose eligibility is not stated; a French version; tests beyond Chrome and Windows; a screen-reader test; automated checks on every push (there is no CI yet).
